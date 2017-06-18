import asyncio
import logging

import aiohttp
import discord
import discord.ext.commands as commands

import paths
from .util import config, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Twitch(bot))


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
        self.live_cache = {}
        self.daemon = bot.loop.create_task(self._daemon())

    def __unload(self):
        self.session.close()
        self.daemon.cancel()

    async def on_channel_delete(self, channel):
        if channel.guild is not None:
            self.conf.remove_channels(channel)
            self.conf.save()

    async def on_guild_remove(self, guild):
        self.conf.remove_channels(*guild.channels)
        self.conf.save()

    async def _daemon(self):
        # Live cache initialisation
        channels = ','.join(self.conf.follows.keys())
        if channels:
            try:
                streams = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel': channels})
            except utils.HTTPError as e:
                # Re-schedule the daemon on error
                log.info(f'Error on initial poll, rescheduling. {e}')
                self.daemon = self.bot.loop.create_task(self._daemon())
                return
            else:
                self.live_cache = {str(s['channel']['_id']): s for s in streams['streams']}

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                await self.poll_streams()
            except Exception as e:
                log.info(f'Polling error, retrying in 10 seconds: {e}')
                await asyncio.sleep(10)
            else:
                await asyncio.sleep(60)

    async def poll_streams(self):
        live_cache = {}

        # Get the streams statuses in chunks of 100
        channels = list(self.conf.follows.keys())
        for i in range(0, len(channels), 100):
            chunk = channels[i:i + 100]
            try:
                streams_chunk = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel': ', '.join(chunk), 'limit': 100})
            except utils.HTTPError as e:
                raise Exception(f'HTTP error when fetching streams chunk #{i / 100 + 1}') from e

            # Extract the newly live streams
            for stream in streams_chunk['streams']:
                stream_id = str(stream['channel']['_id'])
                live_cache[stream_id] = stream

        # Send notifications for the streams that went live after we successfully retrieved all the chunks
        for stream_id in live_cache:
            if stream_id not in self.live_cache:
                try:
                    await self.notify(live_cache[stream_id])
                except Exception as e:
                    log.error(f'Notification error: {e}')

        # Update the live cache
        del self.live_cache
        self.live_cache = live_cache

    async def notify(self, stream):
        # Build the embed
        embed = discord.Embed(title='Click here to join the fun !', url=stream['channel']['url'], colour=0x738bd7)
        embed.set_author(name=stream['channel']['display_name'])
        embed.set_thumbnail(url=stream['channel']['logo'])
        embed.set_image(url=stream['preview']['large'])
        embed.add_field(name=stream['channel']['status'], value='Playing ' + stream['game'])

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        # Send the notification to every interested channel
        for channel_id, message in self.conf.follows[str(stream['channel']['_id'])].items():
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
    async def twitch_group(self, ctx):
        pass

    @twitch_group.command(name='follow', no_pm=True)
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
            self.live_cache[user_id] = streams['streams'][0]

        await ctx.send('\N{OK HAND SIGN}')

    @twitch_group.command(name='unfollow', no_pm=True)
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
            try:
                del self.live_cache[user_id]
            except KeyError:
                pass

        self.conf.save()

        await ctx.send('\N{OK HAND SIGN}')
