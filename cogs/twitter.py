import asyncio
import functools
import logging
import multiprocessing
import os
import textwrap
import time
from queue import Empty as QueueEmpty

import tweepy

import discord
import discord.ext.commands as commands
import discord.utils as dutils
from discord.ext.commands.formatter import Paginator

import paths
from .util import config, oembed

log = logging.getLogger(__name__)


def setup(bot):
    log.info('Loading extension.')

    # Delete irrelevant sub-process logs
    for entry in os.scandir(paths.LOGS):
        if entry.is_file() and 'twitter' in entry.name:
            os.remove(entry.path)

    cog = Twitter(bot)
    bot.add_cog(cog)
    asyncio.ensure_future(cog.stream.start(), loop=bot.loop)


class TwitterError(commands.CommandError):
    pass


class TwitterConfig(config.ConfigElement):
    def __init__(self, credentials, **kwargs):
        self.credentials = credentials
        self.follows = kwargs.pop('follows', [])

    def remove_channels(self, *channels):
        """Removes a set of discord channels from the"""
        channels = set(c.id for c in channels)
        conf_to_remove = set()

        # Check every twitter channel
        for chan_conf in self.follows:
            # if the twitter channel is displayed in one of the given channels
            if set(c.id for c in chan_conf.discord_channels) & channels:
                dchans_to_remove = set(c for c in chan_conf.discord_channels if c.id in channels)
                chan_conf.discord_channels = [c for c in chan_conf.discord_channels if c not in dchans_to_remove]

                # If this channel is now displayed nowhere, mark it for suppression
                if not chan_conf.discord_channels:
                    conf_to_remove.add(chan_conf)

        if conf_to_remove:
            self.follows = [c for c in self.follows if c not in conf_to_remove]


class TwitterCredentials(config.ConfigElement):
    def __init__(self, consumer_key, consumer_secret, access_token, access_token_secret):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret


class FollowConfig(config.ConfigElement):
    def __init__(self, id, screen_name, **kwargs):
        self.id = id
        self.screen_name = screen_name
        self.discord_channels = kwargs.pop('discord_channels', [])
        self.latest_received = kwargs.pop('latest_received', 0)


class ChannelConfig(config.ConfigElement):
    def __init__(self, id, **kwargs):
        self.id = id
        self.received_count = kwargs.pop('received_count', 0)


class Twitter:
    """Twitter commands and events.

    Powered by tweepy (https://github.com/tweepy/tweepy)
    """
    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.TWITTER_CONFIG, encoding='utf-8')
        self.api = TweepyAPI(self.conf.credentials)
        self.stream = TweepyStream(self, self.conf, self.api)
        self.processed_tweets = 0

    def __unload(self):
        log.info('Unloading cog.')
        self.stream.quit()

    async def on_command_error(self, error, ctx):
        if isinstance(error, TwitterError):
            await ctx.bot.send_message(ctx.message.channel, error)

    async def on_ready(self):
        # Check if we've missed any tweet
        await self.fetch_missed_tweets()

    async def on_channel_delete(self, channel):
        if channel.server is not None:
            self.conf.remove_channels(channel)
            self.conf.save()
            await self.stream.start()

    async def on_server_remove(self, server):
        self.conf.remove_channels(*server.channels)
        self.conf.save()
        await self.stream.start()

    @commands.group(name='twitter')
    async def twitter_group(self):
        pass

    @twitter_group.command(name='fetch', pass_context=True, no_pm=True)
    async def twitter_fetch(self, ctx, channel, limit: int=1):
        """Retrieves the latest tweets from a channel and displays them.

        If a limit is given, at most that number of tweets will be displayed. Defaults to 1.
        """
        # Get the latest tweets from the user
        try:
            to_display = await self.get_latest_valid(screen_name=channel.lower(), limit=limit)
        except tweepy.TweepError as e:
            # The channel is probably protected
            if e.reason == 'Not authorized.':
                raise TwitterError('This channel is protected, its tweets cannot be fetched.') from e
            else:
                log.error(str(e))
                raise TwitterError('Unknown error, this has been logged.') from e

        # Display the kept tweets
        for tweet in to_display:
            embed = await self.prepare_embed(tweet)
            await self.bot.say(embed=embed)

    @twitter_group.command(name='follow', pass_context=True, no_pm=True)
    @commands.has_permissions(manage_server=True)
    async def twitter_follow(self, ctx, channel):
        """Follows a twitter channel.

        The tweets from the given twitter channel will be
        sent to the channel this command was used in.

        Following protected users is not supported by the Twitter API.
        See https://dev.twitter.com/streaming/overview/request-parameters#follow
        """
        discord_channel = ctx.message.channel

        # Check for required permissions
        if not discord_channel.permissions_for(discord_channel.server.me).embed_links:
            raise TwitterError('\N{WARNING SIGN} The `Embed Links` permission in this channel is required to display tweets properly. \N{WARNING SIGN}')

        channel = channel.lower()
        conf = dutils.get(self.conf.follows, screen_name=channel)
        if conf is None:
            # New twitter channel, retrieve the user info
            partial = functools.partial(self.api.get_user, screen_name=channel)
            try:
                user = await self.bot.loop.run_in_executor(None, partial)
            except tweepy.TweepError as e:
                if e.api_code == 50:
                    raise TwitterError('User not found.') from e
                else:
                    log.error(str(e))
                    raise TwitterError('Unknown error, this has been logged.') from e

            # The Twitter API does not support following protected users
            # https://dev.twitter.com/streaming/overview/request-parameters#follow
            if user.protected:
                raise TwitterError('This channel is protected and cannot be followed.')

            # Register the new channel
            conf = FollowConfig(user.id_str, channel)
            self.conf.follows.append(conf)

            try:
                # Restart the stream
                await self.stream.start()
            except tweepy.TweepError as e:
                self.conf.follows.remove(conf)
                log.error(str(e))
                raise TwitterError('Unknown error, this has been logged.') from e
        elif dutils.get(conf.discord_channels, id=discord_channel.id):
            raise TwitterError('Already following {} on this channel.'.format(channel))

        # Add new discord channel
        conf.discord_channels.append(ChannelConfig(discord_channel.id))
        self.conf.save()
        await self.bot.say('\N{OK HAND SIGN}')

    @twitter_group.command(name='search')
    async def twitter_search(self, query, limit=5):
        """Searches for a twitter user.

        To use a multi-word query, enclose it in quotes.
        """
        results = await self.bot.loop.run_in_executor(None, self.api.search_users, query, limit)
        if not results:
            raise TwitterError('No result')

        embed = discord.Embed(colour=0x738bd7)
        for user in results:
            embed.add_field(name=user.screen_name, value=textwrap.shorten(user.description, 1024), inline=False)
        await self.bot.say(embed=embed)

    @twitter_group.command(name='status', pass_context=True, no_pm=True)
    async def twitter_status(self, ctx):
        """Displays the status of the twitter stream."""
        server_channels = set(c.id for c in ctx.message.server.channels)

        followed_count = 0
        displayed_count = 0
        for chan_conf in self.conf.follows:
            # Check if this channel is displayed in the server
            if set(c.id for c in chan_conf.discord_channels) & server_channels:
                followed_count += 1
                displayed_count += sum(c.received_count for c in chan_conf.discord_channels if c.id in server_channels)

        # Calculate the average tweets processed per minute
        minutes = (time.time() - self.bot.start_time) / 60
        processed_average = self.processed_tweets / minutes
        processed_average = '< 1' if processed_average < 1 else round(processed_average)
        tweets_processed = '{} (avg {} / min)'.format(self.processed_tweets, processed_average)

        # Display the info
        if self.stream.running:
            embed = discord.Embed(title='Stream status', description='Online', colour=0x00ff00)
        else:
            embed = discord.Embed(title='Stream status', description='Offline', colour=0xff0000)
        embed.add_field(name='Tweets processed since startup', value=tweets_processed, inline=False)
        embed.add_field(name='Channels followed', value=followed_count)
        embed.add_field(name='Tweets displayed', value=displayed_count)

        await self.bot.say(embed=embed)

    @twitter_group.command(name='unfollow', pass_context=True, no_pm=True)
    @commands.has_permissions(manage_server=True)
    async def twitter_unfollow(self, ctx, channel):
        """Unfollows a twitter channel.

        The tweets from the given twitter channel will not be
        sent to the channel this command was used in anymore.
        """
        channel = channel.lower()
        conf = dutils.get(self.conf.follows, screen_name=channel)
        chan_conf = dutils.get(conf.discord_channels, id=ctx.message.channel.id) if conf is not None else None

        if chan_conf is None:
            raise TwitterError('Not following {} on this channel.'.format(channel))

        # Remove the discord channel from the twitter channel conf
        conf.discord_channels.remove(chan_conf)
        if not conf.discord_channels:
            # If there are no more discord channel to feed, unfollow the twitter channel
            self.conf.follows.remove(conf)
            del conf

            # Update the tweepy stream
            if len(self.conf.follows) > 0:
                await self.stream.start()
            else:
                self.stream.stop()

        self.conf.save()

        await self.bot.say('\N{OK HAND SIGN}')

    async def get_latest_valid(self, channel_id=None, screen_name=None, limit=0, since_id=0):
        if since_id == 0:
            # Because we could potentially end up fetching thousands of tweets here, let's force a limit
            limit = limit or 3
            partial = functools.partial(self.api.user_timeline, user_id=channel_id, screen_name=screen_name, exclude_replies=True, include_rts=True)
        else:
            partial = functools.partial(self.api.user_timeline, user_id=channel_id, screen_name=screen_name, exclude_replies=True, include_rts=True, since_id=since_id)

        latest = await self.bot.loop.run_in_executor(None, partial)
        valid = [t for t in latest if not self.skip_tweet(t, from_stream=False)]
        valid.sort(key=lambda t: t.id)
        return valid[-limit:]

    async def fetch_missed_tweets(self):
        missed = []
        # Gather the missed tweets
        for chan_conf in self.conf.follows:
            latest = await self.get_latest_valid(chan_conf.id, since_id=chan_conf.latest_received)
            if latest:
                log.info('Found {} tweets to display for @{}'.format(len(latest), chan_conf.screen_name))
            missed.extend(latest)

        missed.sort(key=lambda t: t.id)
        for tweet in missed:
            await self.tweepy_on_status(tweet)

    def prepare_tweet(self, tweet):
        if isinstance(tweet, dict):
            tweet = tweepy.Status.parse(self.api, tweet)

        tweet.tweet_web_url = 'https://twitter.com/i/web/status/{}'.format(tweet.id)
        tweet.tweet_url = 'https://twitter.com/{}/status/{}'.format(tweet.author.screen_name, tweet.id)
        urls = tweet.entities.get('urls', [])
        media = tweet.entities.get('media', [])

        if tweet.is_quote_status:
            tweet.quoted_status = self.prepare_tweet(tweet.quoted_status)
            sub_tweet = tweet.quoted_status
        elif hasattr(tweet, 'retweeted_status'):
            tweet.retweeted_status = self.prepare_tweet(tweet.retweeted_status)
            sub_tweet = tweet.retweeted_status
        else:
            sub_tweet = None

        # Remove the links to the attached media
        for medium in media:
            tweet.text = tweet.text.replace(medium['url'], '')

        # Replace links in the tweet with the expanded url for lisibility
        for url in urls.copy():
            if url['url'] is None or url['url'] == '' \
                    or url['expanded_url'] is None or url['expanded_url'] == '':
                # Because receiving something like this is possible:
                # "urls": [ {
                #     "indices": [ 141, 141 ],
                #     "url": "",
                #     "expanded_url": null
                #   } ],
                urls.remove(url)
            elif url['expanded_url'] == tweet.tweet_url \
                    or url['expanded_url'] == tweet.tweet_web_url \
                    or (sub_tweet is not None and (url['expanded_url'] == sub_tweet.tweet_url
                                                   or url['expanded_url'] == sub_tweet.tweet_web_url)):
                tweet.text = tweet.text.replace(url['url'], '').strip()
                urls.remove(url)
            else:
                tweet.text = tweet.text.replace(url['url'], url['expanded_url']).strip()

        # Avoid retweets without text to cause the embed to be illegal
        if not tweet.text:
            tweet.text = '\N{ZERO WIDTH SPACE}'

        return tweet

    async def prepare_embed(self, tweet):
        tweet = self.prepare_tweet(tweet)

        author = tweet.author
        author_url = 'https://twitter.com/{}'.format(author.screen_name)

        # Build the embed
        embed = discord.Embed(colour=discord.Colour(int(author.profile_link_color, 16)),
                              title=author.name,
                              url=tweet.tweet_url,
                              timestamp=tweet.created_at)
        embed.set_author(name='@{}'.format(author.screen_name), icon_url=author.profile_image_url, url=author_url)

        # Check for retweets and quotes to format the tweet
        if tweet.is_quote_status:
            sub_tweet = tweet.quoted_status
            embed.description = tweet.text
            embed.add_field(name='Retweet from @{} :'.format(sub_tweet.author.screen_name), value=sub_tweet.text)
        elif hasattr(tweet, 'retweeted_status'):
            sub_tweet = tweet.retweeted_status
            embed.add_field(name='Retweet from @{} :'.format(sub_tweet.author.screen_name), value=sub_tweet.text)
        else:
            sub_tweet = tweet
            embed.description = tweet.text

        # Parse the tweet's entities to extract media and include them as the embed's image
        urls = sub_tweet.entities.get('urls', [])
        media = sub_tweet.entities.get('media', [])
        if media:
            embed.set_image(url=media[0]['media_url_https'])
        elif urls:
            # Fetch oembed data from the url and use it as the embed's image
            url = urls[0]['expanded_url']
            try:
                data = await oembed.fetch_oembed_data(url)
            except Exception as e:
                log.warning(str(e))
            else:
                if data['type'] == 'photo':
                    embed.set_image(url=data['url'])
                else:
                    embed.set_image(url=data.get('thumbnail_url', None) or data.get('url', None))

        return embed

    def skip_tweet(self, status, from_stream=True):
        """Returns True if the given Twitter status is to be skipped."""
        log_status = 'author: {}, reply_to_status: {}, reply_to_user: {}, quoting: {}, retweet: {}, text: {}'
        log_status = log_status.format(status.author.screen_name,
                                       status.in_reply_to_status_id,
                                       status.in_reply_to_user_id,
                                       status.is_quote_status,
                                       hasattr(status, 'retweeted_status'),
                                       status.text)

        # Ignore replies
        if status.in_reply_to_status_id or status.in_reply_to_user_id:
            log.debug('Ignoring tweet (reply): ' + log_status)
            return True
        elif from_stream and status.author.id_str not in self.stream.get_follows():
            log.debug('Ignoring tweet (bad author): ' + log_status)
            return True
        else:
            log.debug('Dispatching tweet to handler: ' + log_status)
            return False

    async def tweepy_on_status(self, tweet):
        """Called by the stream when a tweet is received."""
        self.processed_tweets += 1
        if self.skip_tweet(tweet):
            return

        chan_conf = dutils.get(self.conf.follows, id=tweet.author.id_str)
        try:
            embed = await self.prepare_embed(tweet)
            content = None
        except:
            embed = None
            content = 'Failed to prepare embed for ' + tweet.web_url # If the preparation failed before setting weet.web_url imma kms
            log.error('Failed to prepare embed for ' + str(tweet._json))

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        for channel in chan_conf.discord_channels:
            discord_channel = self.bot.get_channel(channel.id)

            # Check if the channel still exists
            if discord_channel is None:
                log.error('Channel {} unavailable to display tweet {}.'.format(discord_channel.id, tweet.id_str))
                continue

            # Check for required permissions
            perms = discord_channel.permissions_for(discord_channel.server.me)
            if not perms.embed_links:
                log.warning('Improper permissions in channel {} to display tweet {}.'.format(discord_channel.id, tweet.id_str))
                try:
                    warning = '\N{WARNING SIGN} Missed tweet from {} : `Embed links` permission missing. \N{WARNING SIGN}'.format(tweet.author.screen_name)
                    await self.bot.send_message(discord_channel, warning)
                except discord.DiscordException as e:
                    log.error('Could not send warning to channel {}.\n{}'.format(discord_channel.id, e))
                continue

            # Send the embed to the appropriate channel
            log.debug('Scheduling discord message on channel ({}) : {}'.format(channel.id, tweet.text))
            await self.bot.send_message(discord_channel, content=content, embed=embed)

            # Update stats and latest id when processing newer tweets
            if tweet.id > chan_conf.latest_received:
                channel.received_count += 1
                chan_conf.latest_received = tweet.id
                self.conf.save()


class TweepyAPI(tweepy.API):
    """Auto login tweepy api object."""
    def __init__(self, conf):
        tweepy.API.__init__(self, wait_on_rate_limit=True)
        self.auth = tweepy.OAuthHandler(conf.consumer_key, conf.consumer_secret)
        self.auth.set_access_token(conf.access_token, conf.access_token_secret)
        log.info('Logged in Twitter as {username}'.format(username=self.verify_credentials().screen_name))


class SubProcessStream(multiprocessing.Process):
    """Aggregation of things to run a tweepy stream in a sub-process."""
    def __init__(self, mp_queue, credentials, follows, *args, **kwargs):
        self.mp_queue = mp_queue
        self.credentials = credentials
        self.follows = follows
        super().__init__(*args, name='Tweepy Stream', target=self.run_tweepy, **kwargs)

    def run_tweepy(self):
        """The entry point of the sub-process.

        The tweepy.API object isn't pickable so let's just re-create it in the sub-process.
        The tweepy.StreamListener instance then has to be created here too as a separate object instead of
        this class inheriting from it.
        Finally tweepy.Stream has to be instantiated here too to register the listener.

        This feels kinda ugly.
        """
        # Setup the logging for the sub-process
        rlog = logging.getLogger()
        rlog.setLevel(logging.INFO)
        handler = logging.FileHandler(paths.TWITTER_SUBPROCESS_LOG.format(pid=os.getpid()), encoding='utf-8')
        handler.setFormatter(logging.Formatter('{asctime} {levelname} {name} {message}', style='{'))
        rlog.addHandler(handler)

        # Do not join the queue's bg thread on exit
        self.mp_queue.cancel_join_thread()

        # Create the tweepy stream
        log.info('Creating and starting tweepy stream.')
        api = TweepyAPI(self.credentials)  # Re-creation, much efficient, wow
        listener = SubProcessStream.TweepyListener(self.mp_queue, api)
        stream = tweepy.Stream(api.auth, listener)
        log.info('Tweepy stream ready.')

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                log.info('Starting Tweepy stream.')
                stream.filter(follow=self.follows)
            except Exception as e:
                log.exception('Recovering from exception : {}'.format(e))
            else:
                log.info('Exiting sub-process.')
                return

    class TweepyListener(tweepy.StreamListener):
        def __init__(self, mp_queue, api=None):
            tweepy.StreamListener.__init__(self, api)
            self.mp_queue = mp_queue

        def on_data(self, data):
            """Called when raw data is received from connection."""
            if data is not None:
                # Send the data to the parent process
                logging.debug('Received raw data : ' + str(data))
                self.mp_queue.put(data)


class TweepyStream(tweepy.StreamListener):
    """Abstraction of the tweepy streaming api."""
    def __init__(self, handler, conf, api=None):
        if api is None:
            api = TweepyAPI(conf)
        super().__init__(api)
        self.handler = handler
        self.conf = conf
        self.sub_process = None
        self.mp_queue = None
        self.daemon = None

    @property
    def running(self):
        """Returns whether or not a twitter stream is running."""
        return self.sub_process and self.sub_process.is_alive()

    async def start(self):
        """Starts the tweepy Stream."""
        # Avoid being rate limited by twitter when restarting the stream with the same follow list.
        if self.sub_process and not set(self.sub_process.follows) != set(self.get_follows()):
            return

        # Kill the current stream before starting a new one
        self.stop()

        # No need to start a stream if we're not following anyone
        if not self.conf.follows:
            return

        # Create a new multi-processes queue, a new stream object and a new Process
        log.info('Creating new sub-process.')
        self.mp_queue = multiprocessing.Queue()
        self.mp_queue.cancel_join_thread()
        self.sub_process = SubProcessStream(self.mp_queue, self.conf.credentials, self.get_follows())
        log.info('Created new sub-process.')

        # Schedule the polling daemon (it will take care of starting the child process)
        self.daemon = asyncio.ensure_future(self._run())

    def stop(self):
        """Stops the tweepy Stream."""
        if self.running:
            log.info('Stopping sub process (pid {}).'.format(self.sub_process.pid))
            self.sub_process.terminate()
            self.sub_process.join()
            log.info('Stopped sub process (pid {}).'.format(self.sub_process.pid))
            self.daemon.cancel()
            log.info('Cancelled polling daemon for sub process {}.'.format(self.sub_process.pid))

            # Cleanup the stream
            log.info('Cleaning sub-process (pid {}).'.format(self.sub_process.pid))
            self.mp_queue.close()
            self.mp_queue = None
            self.sub_process = None
            self.daemon = None

    def quit(self):
        """Prepares for a safe unloading."""
        self.stop()
        self.handler = None

    def get_follows(self):
        """Returns a list containing the twitter ID of the channels we're following."""
        return [c.id for c in self.conf.follows]

    async def _run(self):
        """Polling daemon that checks the multi-processes queue for data and dispatches it to `on_data`."""
        self.sub_process.start()
        log.info('Started sub process (pid {}).'.format(self.sub_process.pid))

        # Wait until the process is actually started to not consider it dead when it's not even born yet
        while not self.sub_process.is_alive():
            try:
                # Wtb milliseconds async sleep omg
                await asyncio.wait_for(asyncio.sleep(1), 0.1)
            except asyncio.TimeoutError:
                pass

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                data = self.mp_queue.get(False)  # Do not block
            except QueueEmpty:
                if not self.sub_process.is_alive():
                    log.warning('Sub process (pid {}) appears dead.'.format(self.sub_process.pid))
                    asyncio.ensure_future(self.stop())

                # Arbitrary sleep time after an unsuccessful poll
                await asyncio.sleep(4)
            except Exception as e:
                # Might be triggered when the sub_process is terminated while putting data in the queue
                log.error('Queue polling error: ' + str(e))
                break
            else:
                if data is not None:
                    # Process the data sent by the subprocess
                    self.on_data(data)

    def on_status(self, status):
        """Called when a new status arrives."""
        log.debug('Received status: ' + str(status._json))

        # Feed the handler with the tweet
        asyncio.ensure_future(self.handler.tweepy_on_status(status))
