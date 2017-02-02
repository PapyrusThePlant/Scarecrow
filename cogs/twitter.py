import asyncio
import functools
import json
import logging
import multiprocessing
import os
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
    asyncio.ensure_future(cog.stream.start())


class TwitterError(commands.CommandError):
    pass


class TwitterConfig(config.ConfigElement):
    def __init__(self, credentials, **kwargs):
        self.credentials = credentials
        self.follows = kwargs.pop('follows', [])


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

    def __unload(self):
        log.info('Unloading cog.')
        self.stream.quit()

    async def on_command_error(self, error, ctx):
        if isinstance(error, TwitterError):
            await ctx.bot.send_message(ctx.message.channel, error)

    @commands.group(name='twitter')
    async def twitter_group(self):
        pass

    @twitter_group.command(name='fetch', pass_context=True, no_pm=True)
    @commands.has_permissions(manage_server=True)
    async def twitter_fetch(self, ctx, channel, limit=3):
        """Retrieves the lastest tweets from a channel and displays them.

        If a limit is given, at most that number of tweets will be displayed. Defaults to 3.
        """
        to_display = []
        if channel == 'all':
            # Retrieve all the channels for the current feed
            servers_chans = set(c.id for c in ctx.message.server.channels)
            confs = [conf for conf in self.conf.follows if servers_chans.intersection(c.id for c in conf.discord_channels)]
            if not confs:
                raise TwitterError('Not following any channel on this server.')

            # Get the latests X tweets from every channel
            for conf in confs:
                to_display.extend(await self.get_latest_valids(conf.id, limit))

            # Order them again when all have been retrieved
            to_display.sort(key=lambda t: t.id)
        else:
            channel = channel.lower()
            conf = dutils.get(self.conf.follows, screen_name=channel)
            servers_channels = set(c.id for c in ctx.message.server.channels)
            if conf is None or not servers_channels.intersection(c.id for c in conf.discord_channels):
                raise TwitterError('Not following {} on this server.'.format(channel))

            # Get the latest tweets from the user, filter the one we display and only keep the {limit} most recent ones
            to_display = await self.get_latest_valids(conf.id, limit)

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
        """
        discord_channel = ctx.message.channel

        # Check for required permissions
        if not discord_channel.permissions_for(discord_channel.server.me).embed_links:
            raise TwitterError('\N{WARNING SIGN} The permission to embed links in this channel is required to display tweets properly \N{WARNING SIGN}')

        channel = channel.lower()
        conf = dutils.get(self.conf.follows, screen_name=channel)
        if conf is None:
            try:
                # New twitter channel, register it
                user = self.api.get_user(channel)
                conf = FollowConfig(user.id_str, channel)
                self.conf.follows.append(conf)

                # Restart the stream
                await self.stream.start()
            except tweepy.error.TweepError as e:
                self.conf.follows.remove(conf)
                log.error(''.format(str(e)))
                raise TwitterError('Unknown error, this has been logged.')
        elif dutils.get(conf.discord_channels, id=discord_channel.id):
            # Already following on twitter, check if the discord channel is new
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
        results = self.api.search_users(query, limit)
        if not results:
            await self.bot.say('No result')
            return

        paginator = Paginator()
        fmt = '{0:{width}}: {1}\n'
        max_width = max([len(u.screen_name) for u in results])
        for user in results:
            paginator.add_line(fmt.format(user.screen_name, user.description.replace('\n', ''), width=max_width))

        for page in paginator.pages:
            await self.bot.say(page)

    @twitter_group.command(name='status', pass_context=True, no_pm=True)
    async def twitter_status(self, ctx, scope='server'):
        """Displays the status of the twitter stream.

        The scope can either be 'channel' 'server' or 'global'.
        If nothing is specified the default scope is 'server'.
        """
        # Define the channel checker and tweets counter according to the given scope
        if scope == 'global':
            predicate = lambda: True
            counter = lambda: sum(c.received_count for c in chan_conf.discord_channels)
        elif scope == 'server':
            def predicate(): return discord_channels & set(c.id for c in ctx.message.server.channels)
            def counter(): return sum(c.received_count for c in chan_conf.discord_channels if c.id in set(ch.id for ch in ctx.message.server.channels))
        elif scope == 'channel':
            def predicate(): return ctx.message.channel.id in discord_channels
            def counter(): return sum(c.received_count for c in chan_conf.discord_channels if c.id == ctx.message.channel.id)
        else:
            raise TwitterError("Invalid scope '{}'. Value must picked from {}.".format(scope, "['channel', 'server', 'global']"))

        # Gather the twitter channels we're following and the number of tweet received
        received_count = 0
        following = []
        for chan_conf in self.conf.follows:
            discord_channels = set(c.id for c in chan_conf.discord_channels)
            if predicate():
                following.append(chan_conf.screen_name)
                received_count += counter()

        if not following:
            following.append('No one')

        # Display the info
        embed = discord.Embed()
        embed.description = 'Online' if self.stream.running else 'Offline'
        embed.colour = (255 << 8) if self.stream.running else 255 << 16
        embed.add_field(name=str(scope).title() + ' follows', value=', '.join(following))
        embed.add_field(name='Tweets received', value=received_count)

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

    async def get_latest_valids(self, channel_id, limit=0, since_id=0):
        if since_id == 0:
            if limit == 0:
                # Because we could potentielly end up fetching thousands of tweets here, let's force a limit
                limit = 3
            partial = functools.partial(self.api.user_timeline, user_id=channel_id, exclude_replies=True, include_rts=True)
        else:
            partial = functools.partial(self.api.user_timeline, user_id=channel_id, exclude_replies=True, include_rts=True, since_id=since_id)

        latests = await self.bot.loop.run_in_executor(None, partial)
        valids = [t for t in latests if not self.stream.skip_tweet(t)]
        valids.sort(key=lambda t: t.id)
        return valids[-limit:]

    async def _fetch_missed_tweets(self):
        missed = []
        # Gather the missed tweets
        for chan_conf in self.conf.follows:
            missed.extend(await self.get_latest_valids(chan_conf.id, since_id=chan_conf.latest_received))

        missed.sort(key=lambda t: t.id)
        for tweet in missed:
            await self.tweepy_on_status(tweet)

    async def on_ready(self):
        # Check if we've missed any tweet
        await self._fetch_missed_tweets()

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
            if url['expanded_url'] == tweet.tweet_url \
                    or url['expanded_url'] == tweet.tweet_web_url \
                    or (sub_tweet is not None and url['expanded_url'] == sub_tweet.tweet_url)\
                    or (sub_tweet is not None and url['expanded_url'] == sub_tweet.tweet_web_url):
                tweet.text = tweet.text.replace(url['url'], '')
                urls.remove(url)
            else:
                tweet.text = tweet.text.replace(url['url'], url['expanded_url'])

        tweet.text = tweet.text.strip()
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
                log.warning('Failed to retrieve oembed data for url \'{}\' : {}'.format(url, e))
            else:
                if data['type'] == 'photo':
                    embed.set_image(url=data['url'])
                else:
                    embed.set_image(url=data.get('thumbnail_url', None) or data.get('url', None))

        return embed

    async def tweepy_on_status(self, tweet):
        """Called by the stream when a tweet is received."""
        chan_conf = dutils.get(self.conf.follows, id=tweet.author.id_str)
        embed = await self.prepare_embed(tweet)

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        for channel in chan_conf.discord_channels:
            discord_channel = self.bot.get_channel(channel.id)

            # Check for required permissions
            perms = discord_channel.permissions_for(discord_channel.server.me)
            if not perms.send_messages:
                await self.bot.send_message(discord_channel.server.owner, '')
            if not perms.embed_links:
                raise TwitterError('\N{WARNING SIGN} Missed tweet from {} : Embed links permission missing.'.format(tweet.author.screen_name))

            # Send the embed to the appropriate channel
            log.debug('Scheduling discord message on channel ({}) : {}'.format(channel.id, tweet.text))
            await self.bot.send_message(discord_channel, embed=embed)

            # Update stats and latest id when processing newer tweets
            if tweet.id > chan_conf.latest_received:
                channel.received_count += 1
                chan_conf.latest_received = tweet.id
                self.conf.save()


class TweepyAPI(tweepy.API):
    """Auto login tweepy api object."""
    def __init__(self, conf):
        tweepy.API.__init__(self)
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
        if not self.conf.follows:
            return

        # Avoid being rate limited by twitter when restarting the stream with the same follow list.
        if self.sub_process and not set(self.sub_process.follows) != set(self.get_follows()):
            return

        # Kill the current subprocess before starting a new one
        self.stop()

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

    def skip_tweet(self, status):
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
        # Ignore tweets from authors we're not following (shouldn't happen)
        elif status.author.id_str not in self.get_follows():
            log.debug('Ignoring tweet (bad author): ' + log_status)
            return True
        else:
            log.debug('Dispatching tweet to handler: ' + log_status)
            return False

    def on_status(self, status):
        """Called when a new status arrives."""
        log.debug('Received status: ' + str(status._json))

        if not self.skip_tweet(status):
            # Feed the handler with the tweet
            asyncio.ensure_future(self.handler.tweepy_on_status(status))
