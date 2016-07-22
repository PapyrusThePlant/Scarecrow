import asyncio
import logging
import multiprocessing
from queue import Empty as QueueEmpty

import tweepy

import discord
import discord.ext.commands as commands
import discord.utils as dutils
from discord.ext.commands.formatter import Paginator

import scarecrow.cogs.checks as checks
import scarecrow.cogs.utils as utils
import scarecrow.config as config

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Twitter(bot))


class TwitterConfig(config.Config):
    def __init__(self, file, **options):
        self.consumer_key = None
        self.consumer_secret = None
        self.access_token = None
        self.access_token_secret = None

        self.default_format = None
        self.received_count = None
        self.follows = None

        super().__init__(file, **options)

        if self.follows is None:
            self.follows = []


class FollowConfig(config.ConfigElement):
    def __init__(self, data):
        self.id = None
        self.screen_name = None
        self.discord_channels = None

        super().__init__(data)

        if self.discord_channels is None:
            self.discord_channels = []


class DiscordChannelConfig(config.ConfigElement):
    def __init__(self, data):
        self.id = None
        self.format = None
        self.received_count = None

        super().__init__(data)

        if self.received_count is None:
            self.received_count = 0


class Twitter:
    """Twitter commands and events"""
    def __init__(self, bot):
        self.bot = bot
        self.conf = TwitterConfig(config.TWITTER_CONFIG, encoding='utf-8')
        self.api = TweepyAPI(self.conf)
        self.stream = TweepyStream(self, self.conf, self.api)

    @classmethod
    def __about(cls):
        entries = [
            ('Twitter library', 'tweepy (Python)'),
            ('Get it on', 'https://github.com/tweepy/tweepy')
        ]
        return utils.indented_entry_to_str(entries)

    def __unload(self):
        self.stream.quit()

    async def _validate_format(self, fmt):
        """Validates a custom format for the tweets or falls back to the default's."""
        if fmt is None:
            fmt = self.conf.default_format
            return_fmt = None
        else:
            return_fmt = fmt

        try:
            content = 'Sample tweet with {} format:\n'.format('new' if return_fmt else 'default')
            content += fmt.format(author='SAMPLE_AUTHOR', text='SAMPLE TEXT', url='https://sample-url.com')
        except:
            content = 'Invalid format, falling back to the default one.'
            return_fmt = None

        await self.bot.say(content, delete_after=10)
        return return_fmt

    @commands.group(name='twitter')
    async def twitter_group(self):
        pass

    @twitter_group.command(name='follow', pass_context=True)
    @checks.has_permissions(manage_server=True)
    async def twitter_follow(self, ctx, channel, *, format=None):
        """Follows a twitter channel.

        The tweets from the given twitter channel will be
        sent to the channel this command was used in.
        The format is a python string that will be formatted with the
        arguments 'author', 'text' and 'url' corresponding to
        the tweet's author, the tweet's content and the tweet's
        url.
        """
        conf = dutils.get(self.conf.follows, screen_name=channel)
        channel_id = ctx.message.channel.id
        if conf is not None:
            # Already following on twitter, check if the discord channel is new
            if dutils.get(conf.discord_channels, id=channel_id):
                await self.bot.say('Already following ' + channel + ' on this channel.')
                return
        else:
            # New twitter channel, register it
            try:
                conf = self.stream.follow(channel)
            except tweepy.error.TweepError as e:
                await self.bot.say(e.args[0]['message'])
                return

        format = await self._validate_format(format)

        # Add new discord channel
        conf_elem = DiscordChannelConfig({'id': channel_id, 'format': format})
        conf.discord_channels.append(conf_elem)
        self.conf.save()

        await self.bot.say(':ok_hand:')

    @twitter_group.command(name='format', pass_context=True)
    @checks.is_server_owner()
    async def twitter_format(self, ctx, channel, *, format=None):
        """Edits the format a channel is displayed with.

        The format is a python string that will be formatted with the
        arguments 'author', 'text' and 'url' corresponding to
        the tweet's author, the tweet's content and the tweet's
        url.
        """
        conf = dutils.get(self.conf.follows, screen_name=channel)
        if conf is None:
            await self.bot.say('Not following {}.'.format(channel))
            return
        chan_conf = dutils.get(conf.discord_channels, id=ctx.message.channel.id)
        if chan_conf is None:
            await self.bot.say('Not following {} on this channel.'.format(channel))
            return

        # Validate the new format
        if format == 'default':
            format == self.conf.default_format
        elif format is None:
            format = chan_conf.format
        format = await self._validate_format(format)

        # Apply the new format
        chan_conf.format = format
        self.conf.save()

        await self.bot.say(':ok_hand:')

    @twitter_group.command(name='search')
    async def twitter_search(self, query, limit=5):
        """Searches for a twitter user.

        To use a multi-word query, enclose it in quotes"""
        results = self.api.search_users(query, limit)
        if not results:
            await self.bot.say('No result')
            return

        paginator = Paginator()
        fmt = '{0:{width}}: {1}\n'
        # this is slower according to timeit: max_width = max(map(lambda u: len(u.screen_name), results))
        max_width = max([len(u.screen_name) for u in results])

        for user in results:
            paginator.add_line(fmt.format(user.screen_name, user.description.replace('\n', ''), width=max_width))

        for page in paginator.pages:
            await self.bot.say(page)

    @twitter_group.command(name='status', pass_context=True)
    async def twitter_status(self, ctx, scope='channel'):
        """Displays the status of the twitter stream.

        The scope can either be 'channel' 'server' or 'global'.
        If nothing is specified the default scope is 'channel'.
        """
        scopes = ('channel', 'server', 'global')
        if scope not in scopes:
            await self.bot.say("Invalid scope '{}'. Value must picked from {}.".format(scope, str(scopes)))
            return

        received_count = self.conf.received_count if scope == 'global' else 0

        follows = self.conf.follows
        following = []
        for chan_conf in follows:
            discord_channels = set(c.id for c in chan_conf.discord_channels)

            # switch (scope):
            #    case 'channel':
            #        if not ctx.message.channel.id in discord_channels:
            #            break
            #    case 'server':
            #        if not discord_channels & set(c.id for c in ctx.message.server.channels):
            #            break
            #        received_count += chan_conf.received_count
            #    case 'global':
            #        following.append(chan_conf.screen_name)
            #        break
            if scope == 'global':
                following.append(chan_conf.screen_name)
            elif (scope == 'server' and discord_channels & set(c.id for c in ctx.message.server.channels))\
                    or(scope == 'channel' and ctx.message.channel.id in discord_channels):
                following.append(chan_conf.screen_name)
                received_count += sum(c.received_count for c in chan_conf.discord_channels)

        if not following:
            following.append('No one')

        entries = [
            ('Stream status', 'online' if self.stream.running else 'offline'),
            (str(scope).title() + ' follows', ', '.join(following)),
            ('Tweets received', received_count)
        ]
        await self.bot.say_block(utils.indented_entry_to_str(entries, sep=': '))

    @twitter_group.command(name='unfollow', pass_context=True)
    @checks.is_server_owner()
    async def twitter_unfollow(self, ctx, channel):
        """Unfollows a twitter channel.

        The tweets from the given twitter channel will not b
        sent to the channel this command was used in anymore.
        """
        conf = dutils.get(self.conf.follows, screen_name=channel)
        discord_channel = None if conf is None else dutils.get(conf.discord_channels, id=ctx.message.channel.id)

        if discord_channel is None:
            await self.bot.say('Not following ' + channel + ' on this channel.')
            return

        conf.discord_channels.remove(discord_channel)
        if not conf.discord_channels:
            self.stream.unfollow(channel)
            del conf
        self.conf.save()

        await self.bot.say(':ok_hand:')

    def tweepy_on_status(self, author_id, author, text, status_id):
        """Called by the stream when a tweet is received."""
        self.conf.received_count += 1

        chan_conf = dutils.get(self.conf.follows, id=author_id)
        url = 'http://twitter.com/{}/status/{}'.format(author, status_id)

        for channel in chan_conf.discord_channels:
            channel.received_count += 1
            if channel.format is not None:
                fmt = channel.format
            else:
                fmt = self.conf.default_format

            content = fmt.format(author=author, text=text, url=url)
            log.info('Scheduling discord message on channel ({}) : {}'.format(channel.id, content))
            asyncio.ensure_future(self.bot.send_message(discord.Object(id=channel.id), content), loop=self.bot.loop)


class TweepyAPI(tweepy.API):
    """Auto login tweepy api object."""
    def __init__(self, conf):
        tweepy.API.__init__(self)
        self.auth = tweepy.OAuthHandler(conf.consumer_key, conf.consumer_secret)
        self.auth.set_access_token(conf.access_token, conf.access_token_secret)
        log.info('Logged in Twitter as {username}'.format(username=self.verify_credentials().screen_name))


class SubProcessStream:
    """Aggregation of things to run a tweepy stream in a sub-process."""
    def __init__(self, mp_queue, conf, follows):
        self.mp_queue = mp_queue
        self.conf = conf
        self.follows = follows

    def run(self):
        """The entry point of the sub-process.

        The tweepy.API object isn't pickable so let's just re-create it in the sub-process.
        The tweepy.StreamListener instance then has to be created here too as a separate object instead of
        this class inheriting from it.
        Finally tweepy.Stream has to be instanciated here too to register the listener.

        This feels kinda ugly.
        """
        log.info('Creating and starting tweepy stream.')
        api = TweepyAPI(self.conf)  # Re-creation, much efficient, wow
        listener = SubProcessStream.TweepyListener(self.mp_queue, api)
        stream = tweepy.Stream(api.auth, listener)
        log.info('Tweepy stream ready.')
        stream.filter(follow=self.follows)

    class TweepyListener(tweepy.StreamListener):
        def __init__(self, mp_queue, api=None):
            tweepy.StreamListener.__init__(self, api)
            self.mp_queue = mp_queue

        def on_data(self, data):
            """Called when raw data is received from connection."""
            # Send the data to the parent process
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

        asyncio.ensure_future(self.start())

    def follow(self, name):
        """Adds a twitter channel to the follow list.
        If the channel name is incorrect the exception from the user lookup will be forwarded upward.
        """
        # Get the twitter id
        user = self.api.get_user(name)
        chan_conf = FollowConfig({"id": user.id_str, "screen_name": name})
        self.conf.follows.append(chan_conf)

        # Update the stream filter
        asyncio.ensure_future(self.start())

        return chan_conf

    def _get_follows(self):
        """Returns a list containing the twitter ID of the channels we're following."""
        return [c.id for c in self.conf.follows]

    @property
    def initialised(self):
        """Returns wether or not the stream object has been initialised."""
        return True if self.sub_process else False

    def quit(self):
        """Prepares for a safe unloading."""
        self.stop()
        self.handler = None

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
                    log.info('Sub process (pid {}) appears dead, clean it up.'.format(self.sub_process.pid))
                    # When the subprocess is killed, clean things up and return
                    self.mp_queue = None
                    self.sub_process = None
                    # Lol cleanup, gc, halp :3
                    return

                # Arbitrary sleep time after an unsuccessful poll
                await asyncio.sleep(4)
            except Exception as e:
                # Might be triggered when the sub_process is terminated while putting data in the queue
                log.error('Queue polling error: ' + str(e))
                self.mp_queue = None
                self.sub_process = None
                return
            else:
                # Process the data sent by the subprocess
                self.on_data(data)

    @property
    def running(self):
        """Returns wether or not a twitter stream is running."""
        return self.sub_process and self.sub_process.is_alive()

    async def start(self):
        """Starts the tweepy Stream."""
        if not self.conf.follows:
            return

        # Kill the current subprocess before starting a new one
        if self.running:
            self.stop()

        # Wait for the cleanup in the polling daemon before creating a new subprocess
        while self.sub_process:
            await asyncio.sleep(1)

        # Create a new multi-processes queue, a new stream object and a new Process
        self.mp_queue = multiprocessing.Queue()
        stream = SubProcessStream(self.mp_queue, self.conf, self._get_follows())
        self.sub_process = multiprocessing.Process(target=stream.run,
                                                   name='Tweepy_Stream')
        log.info('Created new sub_process (pid {}).'.format(self.sub_process.pid))

        # Schedule the polling daemon (it will take care of starting the child process)
        asyncio.ensure_future(self._run())

    def stop(self):
        """Stops the tweepy Stream."""
        if self.running:
            log.info('Stopping sub process (pid {}).'.format(self.sub_process.pid))
            self.sub_process.terminate()

    def unfollow(self, name):
        """Removes a twitter channel from the follow list and update the tweepy Stream."""
        for chan_conf in self.conf.follows:
            if chan_conf.screen_name == name:
                self.conf.follows.remove(chan_conf)
                break

        # Update the tweepy stream
        if len(self.conf.follows) > 0:
            asyncio.ensure_future(self.start())
        else:
            self.stop()

    def on_status(self, status):
        """Called when a new status arrives."""
        log.debug('Received status: ' + str(status._json))

        log_status = 'author: {}, reply_to_status: {}, reply_to_user: {}, quoting: {}, retweet: {}, text: {}'
        log_status = log_status.format(status.author.screen_name,
                                       status.in_reply_to_status_id,
                                       status.in_reply_to_user_id,
                                       status.is_quote_status,
                                       hasattr(status, 'retweeted_status'),
                                       status.text)

        # Ignore replies
        if status.in_reply_to_status_id or status.in_reply_to_user_id:
            log.info('Ignoring tweet (reply): ' + log_status)
            return
        # Ignore quotes
        elif status.is_quote_status:
            log.info('Ignoring tweet (quote): ' + log_status)
            return
        # Ignore retweets
        elif hasattr(status, 'retweeted_status'):
            log.info('Ignoring tweet (retweet): ' + log_status)
            return
        # Ignore tweets from authors we're not following (shouldn't happen)
        elif status.author.id_str not in self._get_follows():
            log.info('Ignoring tweet (bad author): ' + log_status)
            return
        else:
            log.info('Dispatching tweet to handler: ' + log_status)

        # Feed the handler with the tweet
        self.handler.tweepy_on_status(status.author.id_str, status.author.screen_name, status.text, status.id)
