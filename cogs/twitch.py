import asyncio
import logging

import aiohttp
import discord
import discord.ext.commands as commands

import paths
from .util import config, utils

log = logging.getLogger(__name__)


def setup(bot):
    cog = Twitch(bot)
    bot.add_cog(cog)
    
    # Force the on_ready call if the bot is already ready
    if bot.is_ready():
        bot.loop.create_task(cog.on_ready())


class TwitchConfig(config.ConfigElement):
    def __init__(self, client_id, **kwargs):
        self.client_id = client_id
        self.follows = kwargs.get('follows', {})
        for k, v in self.follows.items():
            self.follows[k] = utils.dict_keys_to_int(v)

    def remove_channels(self, *channels):
        """Unregister the given channels from every followed channel, and
        removes any followed channel that end up without any channel.
        """
        channels = set(c.id for c in channels)
        conf_to_remove = set()

        # Check every followed channel
        for stream_id, destinations in self.follows.items():
            # Remove the given channels from this followed channel
            for channel in channels:
                try:
                    del destinations[channel]
                except KeyError:
                    pass
            if not destinations:
                conf_to_remove.add(stream_id)

        # Cleanup the followed channels
        for stream_id in conf_to_remove:
            del self.follows[stream_id]


class Twitch:
    """Follow Twitch channel and display alerts in Discord when one goes live."""
    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.TWITCH_CONFIG, encoding='utf-8')
        default_headers = {
            'Client-ID': self.conf.client_id,
            'Accept': 'application/vnd.twitchtv.v5+json'
        }
        self.session = aiohttp.ClientSession(loop=bot.loop, headers=default_headers)
        self.live_cache = set()
        self.daemon = None

    def __unload(self):
        self.session.close()
        self.daemon.cancel()

    async def on_guild_channel_delete(self, channel):
        self.conf.remove_channels(channel)
        self.conf.save()

    async def on_guild_remove(self, guild):
        self.conf.remove_channels(*guild.channels)
        self.conf.save()

    async def on_ready(self):
        if not self.daemon:
            self.daemon = self.bot.loop.create_task(self._daemon())

    async def _daemon(self):
        if self.conf.follows:
            # Live cache initialisation
            while not self.live_cache:
                try:
                    streams = await self.poll_streams()
                except Exception as e:
                    log.info(f'Error on initial poll, retrying in 20 seconds: {e}')
                    await asyncio.sleep(20)
                else:
                    self.live_cache = set(streams.keys())

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                streams = await self.poll_streams()
            except Exception as e:
                log.info(f'Polling error, retrying in 60 seconds: {e}')
            else:
                # Send notifications for the streams that went live after we successfully retrieved all the chunks
                for stream_id in streams:
                    if stream_id not in self.live_cache:
                        try:
                            await self.notify(streams[stream_id])
                        except Exception as e:
                            log.error(f'Notification error: {e}')

                # Update the live cache
                self.live_cache.clear()
                self.live_cache = set(streams.keys())
            finally:
                await asyncio.sleep(60)

    async def poll_streams(self):
        streams = {}

        # Get the streams statuses in chunks of 100
        channels = list(self.conf.follows.keys())
        for i in range(0, len(channels), 100):
            chunk = channels[i:i + 100]
            try:
                streams_chunk = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel': ', '.join(chunk), 'limit': 100})
            except utils.HTTPError as e:
                raise Exception(f'HTTP error when fetching streams chunk #{i / 100 + 1}') from e

            # Extract the newly live streams
            for stream_info in streams_chunk['streams']:
                stream_id = str(stream_info['channel']['_id'])
                streams[stream_id] = stream_info

        return streams

    async def notify(self, stream_info):
        # Build the embed
        embed = discord.Embed(title='Click here to join the fun !', url=stream_info['channel']['url'], colour=discord.Colour.blurple())
        embed.set_author(name=stream_info['channel']['display_name'])
        embed.set_thumbnail(url=stream_info['channel']['logo'])
        embed.set_image(url=stream_info['preview']['large'])
        embed.add_field(name=stream_info['channel']['status'], value='Playing ' + stream_info['game'])

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        # Send the notification to every interested channel
        for channel_id, message in self.conf.follows[str(stream_info['channel']['_id'])].items():
            destination = self.bot.get_channel(channel_id)
            await destination.send(message, embed=embed)

    async def get_user(self, channel):
        data = await utils.fetch_page('https://api.twitch.tv/kraken/users', session=self.session, params={'login': channel})
        if data['_total'] == 0:
            raise commands.BadArgument('Channel not found.')
        elif data['_total'] > 1:
            raise commands.BadArgument('More than one channel found.')

        return data['users'][0]

    @commands.group(name='twitch')
    @commands.has_permissions(manage_guild=True)
    async def twitch_group(self, ctx):
        pass

    @twitch_group.command(name='follow')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def twitch_follow(self, ctx, channel, *, message=''):
        """Follows a twitch channel.

        When the given Twitch channel goes online, a notification will be sent
        in the Discord channel this command was used in.

        The message will be sent along the stream notification.
        """
        user = await self.get_user(channel)
        user_id = user['_id']

        # Register it in the conf
        if user_id not in self.conf.follows.keys():
            self.conf.follows[user_id] = {ctx.channel.id: message}
        elif ctx.channel.id in self.conf.follows[user_id]:
            raise commands.BadArgument(f'Already following "{channel}" on this channel.')
        else:
            self.conf.follows[user_id][ctx.channel.id] = message
        self.conf.save()

        # Update the live streams cache if the stream is live
        streams = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel': user_id})
        if streams['_total'] == 1 and user_id not in self.live_cache:
            self.live_cache.add(user_id)

        await ctx.send('\N{OK HAND SIGN}')

    @twitch_group.command(name='unfollow')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def twitch_unfollow(self, ctx, channel):
        """Unfollows a twitch channel.

        The notifications about the given channel will not be displayed in
        the Discord channel this command was used in anymore.
        """
        user = await self.get_user(channel)
        user_id = user['_id']
        if user_id not in self.conf.follows.keys() or ctx.channel.id not in self.conf.follows[user_id]:
            raise commands.BadArgument(f'Not following "{channel}" on this channel.')

        # Remove the discord channel from the conf and clean it up if no other channel follows that stream
        del self.conf.follows[user_id][ctx.channel.id]
        if not self.conf.follows[user_id]:
            del self.conf.follows[user_id]
            # Cleanup the live streams cache
            self.live_cache.remove(user_id)

        self.conf.save()

        await ctx.send('\N{OK HAND SIGN}')
