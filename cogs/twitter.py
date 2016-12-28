import asyncio
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
from .util import checks, config, oembed, utils

log = logging.getLogger(__name__)


def setup(bot):
    log.info('Loading extension.')

    # Delete irrelevant sub-process logs
    for entry in os.scandir(paths.LOGS):
        if entry.is_file() and 'twitter' in entry.name:
            os.remove(entry.path)

    bot.add_cog(Twitter(bot))


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

    @commands.group(name='twitter')
    async def twitter_group(self):
        pass

    @twitter_group.command(name='fetch', pass_context=True)
    @checks.has_permissions(manage_server=True)
    async def twitter_fetch(self, ctx, channel, limit=3, delete_message=True):
        """Retrieves the last tweets from a channel and displays them."""
        if channel == 'all':
            # Retrieve all the channels for the current feed
            discord_channel = ctx.message.channel.id
            channels = [c for c in self.conf.follows if discord_channel in c.discord_channels]

            # Invoke this command
            for channel in channels:
                ctx.invoke(self.twitter_fetch, ctx, channel.screen_name, delete_message=False)

        conf = dutils.get(self.conf.follows, screen_name=channel)
        if conf is None or dutils.get(conf.discord_channels, id=ctx.message.channel.id) is None:
            await self.bot.say('Not following ' + channel + ' on this channel.')
            return

        # TODO : Use 'since_id=chan_conf.latest_received', atm twitter answers that it's not a valid parameter...
        latest_tweets = self.api.user_timeline(user_id=conf.id, exclude_replies=True, include_rts=False)

        # Display tweets up to the given limit
        for tweet in latest_tweets:
            if limit == 0:
                break
            if not self.stream.skip_tweet(tweet):
                await self.tweepy_on_status(tweet)
                limit -= 1

        # Clean the feed
        if delete_message:
            await self.bot.delete_message(ctx.message)

    @twitter_group.command(name='follow', pass_context=True)
    @checks.has_permissions(manage_server=True)
    async def twitter_follow(self, ctx, channel):
        """Follows a twitter channel.

        The tweets from the given twitter channel will be
        sent to the channel this command was used in.
        """
        conf = dutils.get(self.conf.follows, screen_name=channel)
        discord_channel = ctx.message.channel
        if conf is None:
            try:
                # New twitter channel, register it
                user = self.api.get_user(channel)
                conf = FollowConfig(user.id_str, channel)
                self.conf.follows.append(conf)

                # Restart the stream
                await self.stream.start()
            except tweepy.error.TweepError as e:
                await self.bot.say(e)
                self.conf.follows.remove(conf)
                return
        elif dutils.get(conf.discord_channels, id=discord_channel.id):
            # Already following on twitter, check if the discord channel is new
            await self.bot.say('Already following ' + channel + ' on this channel.')
            return

        # Add new discord channel
        conf.discord_channels.append(ChannelConfig(discord_channel.id))
        self.conf.save()

        member = discord_channel.server.me
        if not discord_channel.permissions_for(member).embed_links:
            await self.bot.say(':warning: I need embed links permission in this channel to display tweets properly.')

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

    @twitter_group.command(name='status', pass_context=True)
    async def twitter_status(self, ctx, scope='server'):
        """Displays the status of the twitter stream.

        The scope can either be 'channel' 'server' or 'global'.
        If nothing is specified the default scope is 'server'.
        """
        # Verify the scope
        scopes = ('channel', 'server', 'global')
        if scope not in scopes:
            await self.bot.say("Invalid scope '{}'. Value must picked from {}.".format(scope, str(scopes)))
            return

        # Gather the twitter channels we're following and the number of tweet received in the given scope
        received_count = 0
        following = []
        for chan_conf in self.conf.follows:
            discord_channels = set(c.id for c in chan_conf.discord_channels)
            if scope == 'global':
                following.append(chan_conf.screen_name)
                received_count += sum(c.received_count for c in chan_conf.discord_channels)
            elif scope == 'server' and discord_channels & set(c.id for c in ctx.message.server.channels):
                following.append(chan_conf.screen_name)
                server_channels = set(ch.id for ch in ctx.message.server.channels)
                received_count += sum(c.received_count for c in chan_conf.discord_channels if c.id in server_channels)
            elif scope == 'channel' and ctx.message.channel.id in discord_channels:
                following.append(chan_conf.screen_name)
                received_count += sum(c.received_count for c in chan_conf.discord_channels if c.id == ctx.message.channel.id)

        if not following:
            following.append('No one')

        # Display the info
        embed = discord.Embed()
        embed.description = 'Online' if self.stream.running else 'Offline'
        embed.colour = (255 << 8) if self.stream.running else 255 << 16
        embed.add_field(name=str(scope).title() + ' follows', value=', '.join(following))
        embed.add_field(name='Tweets received', value=received_count)

        await self.bot.say(embed=embed)

    @twitter_group.command(name='unfollow', pass_context=True)
    @checks.is_server_owner()
    async def twitter_unfollow(self, ctx, channel):
        """Unfollows a twitter channel.

        The tweets from the given twitter channel will not be
        sent to the channel this command was used in anymore.
        """
        conf = dutils.get(self.conf.follows, screen_name=channel)
        chan_conf = dutils.get(conf.discord_channels, id=ctx.message.channel.id) if conf is not None else None

        if chan_conf is None:
            await self.bot.say('Not following ' + channel + ' on this channel.')
            return

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

    async def _fetch_missed_tweets(self):
        missed = []
        for chan_conf in self.conf.follows:
            # TODO : Use 'since_id=chan_conf.latest_received', atm twitter answers that it's not a valid parameter...
            latest_tweets = self.api.user_timeline(user_id=chan_conf.id, exclude_replies=True, include_rts=False)

            # Gather the missed tweets
            missed = []
            for tweet in latest_tweets:
                if tweet.id > chan_conf.latest_received:
                    missed.append(tweet)

        missed.sort(key=lambda t: t.id)
        for tweet in missed:
            if not self.stream.skip_tweet(tweet):
                await self.tweepy_on_status(tweet)

    async def on_ready(self):
        # Check if we've missed any tweet
        asyncio.ensure_future(self._fetch_missed_tweets())

    async def tweepy_on_status(self, tweet):
        """Called by the stream when a tweet is received."""
        author = tweet.author
        chan_conf = dutils.get(self.conf.follows, id=author.id_str)
        author_url = 'http://twitter.com/{}'.format(author.screen_name)
        tweet_url = '{}/status/{}'.format(author_url, tweet.id)

        urls = tweet.entities.get('urls', [])
        media = tweet.entities.get('media', [])

        # Remove the links to the attached media
        for medium in media:
            tweet.text = tweet.text.replace(medium['url'], '')

        # Replace links in the tweet with the expanded url for lisibility
        for url in urls:
            tweet.text = tweet.text.replace(url['url'], url['expanded_url'])

        # Build the embed
        embed = discord.Embed(colour=discord.Colour(int(author.profile_link_color, 16)),
                              title=author.name,
                              url=tweet_url,
                              description=tweet.text,
                              timestamp=tweet.created_at)
        embed.set_author(name='@{}'.format(author.screen_name), icon_url=author.profile_image_url, url=author_url)

        # Parse the tweet's entities to extract media and include them as the embed's image
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

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        for channel in chan_conf.discord_channels:
            # Send the embed to the appropriate channel
            log.debug('Scheduling discord message on channel ({}) : {}'.format(channel.id, tweet.text))
            await self.bot.send_message(self.bot.get_channel(channel.id), embed=embed)

            # Increment the received tweets count and save the id of the last tweet received from this channel
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


class SubProcessStream:
    """Aggregation of things to run a tweepy stream in a sub-process."""
    def __init__(self, mp_queue, credentials, follows):
        self.mp_queue = mp_queue
        self.credentials = credentials
        self.follows = follows

    def run(self):
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

        asyncio.ensure_future(self.start())

    @property
    def running(self):
        """Returns whether or not a twitter stream is running."""
        return self.sub_process and self.sub_process.is_alive()

    async def start(self):
        """Starts the tweepy Stream."""
        if not self.conf.follows:
            return

        # TODO : Avoid being rate limited when restarting the stream with the same follow list.
        # Starting the stream with the same follow list than the moment it was shut down gets us rate limited by the
        # Twitter api, the subprocess exits with no error and the daemon cleans the stream up before exiting too

        # Kill the current subprocess before starting a new one
        self.stop()

        # Wait for the cleanup in the polling daemon before creating a new subprocess
        while self.sub_process:
            await asyncio.sleep(1)

        # Create a new multi-processes queue, a new stream object and a new Process
        log.info('Creating new sub-process.')
        self.mp_queue = multiprocessing.Queue()
        self.mp_queue.cancel_join_thread()
        stream = SubProcessStream(self.mp_queue, self.conf.credentials, self.get_follows())
        self.sub_process = multiprocessing.Process(target=stream.run,
                                                   name='Tweepy_Stream')
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
        # Ignore quotes
        elif status.is_quote_status:
            log.debug('Ignoring tweet (quote): ' + log_status)
            return True
        # Ignore retweets
        elif hasattr(status, 'retweeted_status'):
            log.debug('Ignoring tweet (retweet): ' + log_status)
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
