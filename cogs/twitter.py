import asyncio
import functools
import json
import html
import logging
import multiprocessing
import os
from queue import Empty as QueueEmpty

import tweepy

import discord
import discord.ext.commands as commands

import paths
from .util import checks, config, oembed, utils

log = logging.getLogger(__name__)


def setup(bot):
    log.debug('Loading extension.')
    cog = Twitter(bot)
    bot.add_cog(cog)
    if bot.is_ready():
        cog.stream.start()


class TwitterError(commands.CommandError):
    pass


class TwitterConfig(config.ConfigElement):
    def __init__(self, credentials, **kwargs):
        self.credentials = credentials
        self.follows = kwargs.pop('follows', {})

    def remove_channels(self, *channels):
        """Unregister the given channels from every FollowConfig, and
        removes any FollowConfig that end up without any channel.
        """
        removed = 0
        unfollowed = 0
        conf_to_remove = set()

        # Check every FollowConfig
        for follow_conf in self.follows.values():
            for channel in channels:
                try:
                    del follow_conf.discord_channels[channel.id]
                except KeyError:
                    pass
                else:
                    removed += 1

                # If this FollowConfig ended up with 0 channel, save it to remove it later
                if not follow_conf.discord_channels:
                    conf_to_remove.add(follow_conf)

        # Remove the FollowConfig we don't need
        for follow_conf in conf_to_remove:
            del self.follows[follow_conf.id]
            unfollowed += 1

        return removed, unfollowed


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
        self.discord_channels = utils.dict_keys_to_int(kwargs.pop('discord_channels', {}))
        self.latest_received = kwargs.pop('latest_received', 0)


class ChannelConfig(config.ConfigElement):
    def __init__(self, id, feed_creator, **kwargs):
        self.id = id
        self.feed_creator = feed_creator
        self.message = kwargs.pop('message', None)


class Twitter:
    """Follow Twitter accounts and stream their tweets in Discord.

    Powered by tweepy (https://github.com/tweepy/tweepy)
    """
    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.TWITTER_CONFIG, encoding='utf-8')
        self.api = TweepyAPI(self.conf.credentials)
        self.stream = TweepyStream(self, self.conf, self.api)
        self.latest_received = 0
        self.fetcher = None

    def __unload(self):
        log.info('Unloading cog.')
        self.stream.quit()

    async def __error(self, ctx, error):
        """Local command error handler."""
        if isinstance(error, TwitterError):
            try:
                await ctx.send(error)
            except discord.Forbidden:
                await ctx.author.send(f'Missing the `Send Messages` permission to send the following error to {ctx.message.channel.mention}: {error}')

    async def on_guild_channel_delete(self, channel):
        removed, unfollowed = self.conf.remove_channels(channel)
        log.info(f'Deletion of channel {channel.id} removed {removed} feeds and unfollowed {unfollowed}.')
        self.conf.save()
        self.stream.start()

    async def on_guild_remove(self, guild):
        removed, unfollowed = self.conf.remove_channels(*guild.channels)
        log.info(f'removal from guild {guild.id} removed {removed} feeds and unfollowed {unfollowed}.')
        self.conf.save()
        self.stream.start()

    async def on_ready(self):
        self.stream.start()

    async def get_confs(self, ctx, handle, create=False):
        sane_handle = handle.lower().lstrip('@')
        conf = discord.utils.get(self.conf.follows.values(), screen_name=sane_handle)
        if conf is None:
            # Retrieve the user info in case his screen name changed
            partial = functools.partial(self.api.get_user, screen_name=sane_handle)
            try:
                user = await ctx.bot.loop.run_in_executor(None, partial)
            except tweepy.TweepError as e:
                if e.api_code == 50:
                    raise TwitterError(f'User "{handle}" not found.') from e
                else:
                    log.error(str(e))
                    raise TwitterError('Unknown error from the Twitter API, this has been logged.') from e
            conf = self.conf.follows.get(user.id_str)

            # Update the saved screen name if it changed
            if conf is not None:
                conf.screen_name = user.screen_name.lower()
                self.conf.save()
            elif create:
                # The Twitter API does not support following protected users
                # https://dev.twitter.com/streaming/overview/request-parameters#follow
                if user.protected:
                    raise TwitterError('This channel is protected and cannot be followed.')

                if self.latest_received == 0:
                    partial = functools.partial(self.api.user_timeline, user_id=user.id, count=1)
                    latest = await ctx.bot.loop.run_in_executor(None, partial)
                    self.latest_received = latest[0].id
                # Register the new channel
                conf = FollowConfig(user.id_str, sane_handle, latest_received=self.latest_received)
                self.conf.follows[conf.id] = conf

                try:
                    # Restart the stream
                    self.stream.start()
                except tweepy.TweepError as e:
                    del self.conf.follows[conf.id]
                    log.error(str(e))
                    raise TwitterError('Unknown error from the Twitter API, this has been logged.') from e

        chan_conf = conf.discord_channels.get(ctx.message.channel.id) if conf is not None else None
        return conf, chan_conf

    @commands.group(name='twitter')
    async def twitter_group(self, ctx):
        pass

    @twitter_group.command(name='setmessage', aliases=['editmessage'])
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def twitter_setmessage(self, ctx, handle, *, message=None):
        """Sets a custom message for all the tweets of a given Twitter channel.

        If a message was already set, it will be overridden. Omitting
        the message will remove it for that feed.
        """
        conf, chan_conf = await self.get_confs(ctx, handle)
        if chan_conf is None:
            raise TwitterError(f'Not following {handle} on this channel.')
        chan_conf.message = message
        self.conf.save()
        await ctx.send('\N{OK HAND SIGN}')

    @twitter_group.command(name='fetch')
    @commands.guild_only()
    async def twitter_fetch(self, ctx, handle, limit: int=1):
        """Retrieves the latest tweets from a channel and displays them.

        If the channel is followed on the server, every tweets missed since
        the last displayed one will be fetched and displayed in the Discord
        channel receiving this feed.

        You do not need to include the '@' before the Twitter channel's
        handle, it will avoid unwanted mentions in Discord.

        If a limit is given, at most that number of tweets will be displayed. Defaults to 1.
        """
        sane_handle = handle.lower().lstrip('@')
        conf, chan_conf = await self.get_confs(ctx, handle)

        await ctx.message.add_reaction('\N{HOURGLASS WITH FLOWING SAND}')
        async with ctx.typing():
            try:
                if conf:
                    missed = await self.get_latest_valid(conf.id, since_id=conf.latest_received)
                else:
                    missed = await self.get_latest_valid(screen_name=sane_handle, limit=limit)
            except tweepy.TweepError as e:
                if e.reason == 'Not authorized.':
                    if conf:
                        await self.notify_channels(f'Could not check for missed tweets for {conf.screen_name}. The channel is protected, consider unfollowing it.', *conf.discord_channels.values())
                    else:
                        raise TwitterError('This channel is protected, its tweets cannot be fetched.') from e

                if e.api_code == 34:
                    raise TwitterError(f'User "{handle}" not found.') from e
                else:
                    log.error(str(e))
                    raise TwitterError('Unknown error from the Twitter API, this has been logged.') from e
            else:
                if missed:
                    for tweet in missed:
                        if conf:
                            await self.tweepy_on_status(tweet)
                        else:
                            embed = await self.prepare_embed(tweet)
                            await ctx.send(embed=embed)

        if conf:
            try:
                await ctx.message.delete()
            except discord.NotFound:
                pass # The user probably deleted his message before we tried to do it

    @twitter_group.command(name='follow')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def twitter_follow(self, ctx, handle, *, message=None):
        """Follows a Twitter channel.

        The tweets from the given Twitter channel will be
        sent to the channel this command was used in. If provided,
        the message will be attached to every tweet, so be wary of
        mention spam with this.

        You do not need to include the '@' before the Twitter channel's
        handle, it will avoid unwanted mentions in Discord.

        Following protected users is not supported by the Twitter API.
        See https://dev.twitter.com/streaming/overview/request-parameters#follow
        """
        # Check for required permissions
        perms = ctx.channel.permissions_for(ctx.guild.me)
        if not perms.send_messages:
            raise TwitterError(f'The `Send Messages` permission in {ctx.channel.mention} is required to display tweets.')
        if not perms.embed_links:
            raise TwitterError(f'The `Embed Links` permission in {ctx.channel.mention} is required to display tweets properly.')

        conf, chan_conf = await self.get_confs(ctx, handle, create=True)
        if chan_conf:
            raise TwitterError(f'Already following "{handle}" on this channel.')

        # Add new discord channel
        conf.discord_channels[ctx.channel.id] = ChannelConfig(ctx.channel.id, ctx.author.id, message=message)
        self.conf.save()
        await ctx.send('\N{OK HAND SIGN}')

    @twitter_group.command(name='search')
    async def twitter_search(self, ctx, query, limit=5):
        """Searches for a Twitter user.

        To use a multi-word query, enclose it in quotes.
        """
        try:
            results = await ctx.bot.loop.run_in_executor(None, self.api.search_users, query, limit)
        except tweepy.TweepError as e:
            log.error(str(e))
            raise TwitterError('Unknown error from the Twitter API, this has been logged.') from e
        if not results:
            raise TwitterError('No result.')

        if len(results) > 1:
            embed = discord.Embed(colour=discord.Colour.blurple())
            for user in results:
                name = f'{user.name} - @{user.screen_name}'
                urls = user.entities.get('description', None).get('urls', [])
                description = self.replace_entities(user.description, urls) if user.description else 'No description.'
                embed.add_field(name=name, value=description, inline=False)
        else:
            user = results[0]
            urls = user.entities.get('description', None).get('urls', [])
            description = self.replace_entities(user.description, urls) if user.description else 'No description.'
            embed = discord.Embed(colour=discord.Colour.blurple(), title=user.name, description=description, url=f'https://twitter.com/{user.screen_name}')
            embed.set_author(name=f'@{user.screen_name}')
            embed.set_thumbnail(url=user.profile_image_url_https)
            embed.add_field(name='Tweets', value=user.statuses_count)
            embed.add_field(name='Followers', value=user.followers_count)
        await ctx.send(embed=embed)

    @twitter_group.command(name='list')
    @commands.guild_only()
    async def twitter_list(self, ctx):
        """Lists the followed channels on the server."""
        follows = {}
        channels = set(c.id for c in ctx.guild.text_channels) # for faster `in` lookup

        # Map channel ids to a list of screen names followed in that channel
        for twitter_id, conf in self.conf.follows.items():
            for channel_id in conf.discord_channels.keys():
                if channel_id in channels:
                    channel = discord.utils.get(ctx.guild.text_channels, id=channel_id)
                    follows.setdefault(channel, []).append(conf.screen_name)

        if not follows:
            raise TwitterError('Not following any channel on this server.')

        # Build the embed response
        embed = discord.Embed(description='Followed channels:', colour=discord.Colour.blurple())
        for channel, channels in sorted(follows.items(), key=lambda t: t[0].position):
            handles = ', '.join(f'@\N{ZERO WIDTH SPACE}{c}' for c in sorted(channels))
            embed.add_field(name=f'#{channel.name}', value=handles, inline=False)

        await ctx.send(embed=embed)

    @twitter_group.command(name='status')
    async def twitter_status(self, ctx):
        """Displays the status of the Twitter stream."""
        if self.stream.running:
            embed = discord.Embed(title='Stream status', description='Online', colour=discord.Colour.green())
        else:
            embed = discord.Embed(title='Stream status', description='Offline', colour=discord.Colour.red())

        await ctx.send(embed=embed)

    @twitter_group.command(name='unfollow')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def twitter_unfollow(self, ctx, handle):
        """Unfollows a Twitter channel.

        The tweets from the given Twitter channel will not be
        sent to the channel this command was used in anymore.

        You do not need to include the '@' before the Twitter channel's
        handle, it will avoid unwanted mentions in Discord.
        """
        conf, chan_conf = await self.get_confs(ctx, handle)
        if chan_conf is None:
            raise TwitterError(f'Not following {handle} on this channel.')

        # Remove the Discord channel from the Twitter channel conf
        del conf.discord_channels[chan_conf.id]
        del chan_conf

        # If there are no more Discord channel to feed, unfollow the Twitter channel
        if not conf.discord_channels:
            del self.conf.follows[conf.id]
            del conf

            # Update the tweepy stream
            if self.conf.follows:
                self.stream.start()
            else:
                self.stream.stop()

        self.conf.save()
        await ctx.send('\N{OK HAND SIGN}')

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

    async def notify_channels(self, message, *channels):
        for channel in channels:
            await self.notify_channel(message, channel)

    async def notify_channel(self, message, channel):
        ch = self.bot.get_channel(channel.id)
        try:
            await ch.send(message)
        except discord.Forbidden:
            message = f'Missing `Send Messages` permission in {ch.mention} to display:\n{message}'
            creator = discord.utils.get(ch.members, id=channel.feed_creator)
            try:
                await creator.send(message)
            except:
                pass # Oh well.

    def replace_entities(self, text, urls, additional_matches=()):
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
            elif url['expanded_url'] in additional_matches:
                text = text.replace(url['url'], '').strip()
                urls.remove(url)
            else:
                text = text.replace(url['url'], url['expanded_url']).strip()
        return text

    def prepare_tweet(self, tweet, nested=False):
        if isinstance(tweet, dict):
            tweet = tweepy.Status.parse(self.api, tweet)

        tweet.tweet_web_url = f'https://twitter.com/i/web/status/{tweet.id}'
        tweet.tweet_url = f'https://twitter.com/{tweet.author.screen_name}/status/{tweet.id}'

        if not nested and tweet.is_quote_status:
            if not hasattr(tweet, 'quoted_status'):
                # Original tweet is unavailable
                tweet.quoted_status = None
            else:
                tweet.quoted_status = self.prepare_tweet(tweet.quoted_status, nested=True)
            sub_tweet = tweet.quoted_status
        elif not nested and hasattr(tweet, 'retweeted_status'):
            tweet.retweeted_status = self.prepare_tweet(tweet.retweeted_status, nested=True)
            sub_tweet = tweet.retweeted_status
        else:
            sub_tweet = None

        # Remove the links to the attached media
        for medium in tweet.entities.get('media', []):
            tweet.text = tweet.text.replace(medium['url'], '')

        # Replace links in the tweet with the expanded url for lisibility
        matches = [tweet.tweet_url, tweet.tweet_web_url]
        if sub_tweet:
            matches.extend([sub_tweet.tweet_url, sub_tweet.tweet_web_url])
        tweet.text = self.replace_entities(tweet.text, tweet.entities.get('urls', []), additional_matches=matches)

        # Decode html entities
        tweet.text = html.unescape(tweet.text).strip()

        # Avoid retweets without text to cause the embed to be illegal
        if not tweet.text:
            tweet.text = '\N{ZERO WIDTH SPACE}'

        return tweet

    async def prepare_embed(self, tweet):
        tweet = self.prepare_tweet(tweet)

        author = tweet.author
        author_url = f'https://twitter.com/{author.screen_name}'

        # Build the embed
        embed = discord.Embed(colour=discord.Colour(int(author.profile_link_color, 16)),
                              title=author.name,
                              url=tweet.tweet_url,
                              timestamp=tweet.created_at)
        embed.set_author(name=f'@{author.screen_name}', icon_url=author.profile_image_url, url=author_url)

        # Check for retweets and quotes to format the tweet
        if tweet.is_quote_status:
            sub_tweet = tweet.quoted_status
            embed.description = tweet.text
            if not sub_tweet:
                # Original tweet is unavailable
                embed.add_field(name='Retweet unavailable', value='The retweeted status is unavailable.')
                sub_tweet = tweet
            else:
                embed.add_field(name=f'Retweet from @{sub_tweet.author.screen_name} :', value=sub_tweet.text)
        elif hasattr(tweet, 'retweeted_status'):
            sub_tweet = tweet.retweeted_status
            embed.add_field(name=f'Retweet from @{sub_tweet.author.screen_name} :', value=sub_tweet.text)
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
            except oembed.OembedException as e:
                log.debug(e)
            else:
                # Some providers return their errors in the resp content with a 200
                if 'type' not in data:
                    return embed

                if data['type'] == 'photo':
                    image_url = data['url']
                else:
                    image_url = data.get('thumbnail_url', data.get('url', url))

                # Sometimes we get an empty image_url
                if image_url:
                    embed.set_image(url=image_url)
        return embed

    def skip_tweet(self, status, from_stream=True):
        """Returns True if the given Twitter status is to be skipped."""
        if status.in_reply_to_status_id or status.in_reply_to_user_id:
            # Ignore replies
            return True
        elif from_stream and status.author.id_str not in self.conf.follows:
            # The stream includes replies to tweets from channels we're following, ignore them
            return True
        else:
            return False

    async def tweepy_on_status(self, tweet):
        """Called by the stream when a tweet is received."""
        if tweet.id > self.latest_received:
            self.latest_received = tweet.id

        if self.skip_tweet(tweet):
            return

        tweet_str = json.dumps(tweet._json, separators=(',', ':'), ensure_ascii=True)
        log.debug(f'Received tweet: {tweet_str}')

        conf = self.conf.follows.get(tweet.author.id_str)

        # Update the saved screen name if it changed
        if conf.screen_name != tweet.author.screen_name:
            conf.screen_name = tweet.author.screen_name.lower()
            self.conf.save()

        try:
            embed = await self.prepare_embed(tweet)
        except Exception as e:
            content = f'Failed to prepare embed for {tweet.tweet_web_url}'
            log.error(f'{content}\nError : {e}\nTweet : {tweet_str} ')
            await self.notify_channels(f'{content}. This has been logged.', *conf.discord_channels.values())
            return

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        for chan_conf in conf.discord_channels.copy().values():
            destination = self.bot.get_channel(chan_conf.id)
            if destination is None:
                log.warning(f'Channel {chan_conf.id} is unavailable, ignoring.')
                continue

            try:
                # Send the message to the appropriate channel
                await destination.send(chan_conf.message, embed=embed)
            except discord.Forbidden:
                # Notify if we're missing permissions
                await self.notify_channel(f'Insufficient permissions to display {tweet.tweet_url}.', chan_conf)
            except Exception as e:
                log.exception(f'Ignoring exception when sending tweet : {e}')
            else:
                # Update stats and latest id when processing newer tweets
                if tweet.id > conf.latest_received:
                    conf.latest_received = tweet.id
                    self.conf.save()


class TweepyAPI(tweepy.API):
    """Auto login tweepy api object."""
    def __init__(self, conf):
        tweepy.API.__init__(self, wait_on_rate_limit=True)
        self.auth = tweepy.OAuthHandler(conf.consumer_key, conf.consumer_secret)
        self.auth.set_access_token(conf.access_token, conf.access_token_secret)
        log.info(f'Logged in Twitter as {self.verify_credentials().screen_name}')


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
        handler = logging.FileHandler(paths.TWITTER_SUBPROCESS_LOG, encoding='utf-8')
        handler.setFormatter(logging.Formatter(f'{os.getpid()} {{asctime}} {{levelname}} {{name}} {{message}}', style='{'))
        rlog.addHandler(handler)

        # Do not join the queue's bg thread on exit
        self.mp_queue.cancel_join_thread()

        # Create the tweepy stream
        log.info('Creating tweepy stream.')
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
                log.exception(f'Recovering from exception : {e}')
            else:
                log.info('Exiting normally.')
                return

    class TweepyListener(tweepy.StreamListener):
        def __init__(self, mp_queue, api=None):
            tweepy.StreamListener.__init__(self, api)
            self.mp_queue = mp_queue

        def on_data(self, data):
            """Called when raw data is received from connection."""
            if data is not None:
                # Send the data to the parent process
                logging.debug(f'Received raw data : {data}')
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
        """Returns whether or not a Twitter stream is running."""
        return self.sub_process and self.sub_process.is_alive()

    def start(self):
        """Starts the tweepy Stream."""
        # Avoid being rate limited by Twitter when restarting the stream with the same follow list.
        if self.sub_process and not set(self.sub_process.follows) != set(self.conf.follows.keys()):
            return

        # Kill the current stream before starting a new one
        self.stop()

        # No need to start a stream if we're not following anyone
        if not self.conf.follows:
            return

        # Create a new multi-processes queue, a new stream object and a new Process
        log.info('Creating sub-process.')
        self.mp_queue = multiprocessing.Queue()
        self.mp_queue.cancel_join_thread()
        self.sub_process = SubProcessStream(self.mp_queue, self.conf.credentials, list(self.conf.follows.keys()))

        # Schedule the polling daemon (it will take care of starting the child process)
        self.daemon = asyncio.ensure_future(self._run())

    def stop(self):
        """Stops the tweepy Stream."""
        if self.running:
            log.info(f'Stopping stream/daemon and cleaning up {self.sub_process.pid}.')
            self.sub_process.terminate()
            self.sub_process.join()
            self.daemon.cancel()
            self.mp_queue.close()
            self.mp_queue = None
            self.sub_process = None
            self.daemon = None

    def restart(self):
        self.stop()
        self.start()

    def quit(self):
        """Prepares for a safe unloading."""
        self.stop()
        self.handler = None

    async def _run(self):
        """Polling daemon that checks the multi-processes queue for data and dispatches it to `on_data`."""
        self.sub_process.start()
        log.info(f'Started daemon for {self.sub_process.pid}.')

        # Wait until the process is actually started to not consider it dead when it's not even born yet
        while not self.sub_process.is_alive():
            try:
                await asyncio.sleep(0.1)
            except asyncio.TimeoutError:
                pass

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                data = self.mp_queue.get(False)  # Do not block
            except QueueEmpty:
                if not self.sub_process.is_alive():
                    log.info(f'{self.sub_process.pid} appears dead. Restarting sub process.')
                    self.restart()
                    return

                # Arbitrary sleep time after an unsuccessful poll
                await asyncio.sleep(4)
            except Exception as e:
                # Might be triggered when the sub_process is terminated while putting data in the queue
                log.error(f'Queue polling error, exiting daemon. {e}')
                break
            else:
                if data is not None:
                    # Process the data sent by the subprocess
                    self.on_data(data)

    def on_status(self, status):
        """Called when a new status arrives."""
        # Feed the handler with the tweet
        asyncio.ensure_future(self.handler.tweepy_on_status(status))
