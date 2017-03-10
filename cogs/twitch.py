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

    def remove_channels(self, *channels):
        """Unregister the given channels from every followed channel, and
        removes any followed channel that end up without any channel.
        """
        channels = set(c.id for c in channels)
        conf_to_remove = set()

        # Check every followed channel
        for channel_id, destinations in self.follows.items():
            # Remove the given channels from this followed channel
            for channel in channels:
                try:
                    destinations.remove(channel)
                except ValueError:
                    pass
            if not destinations:
                conf_to_remove.add(channel_id)

        # Cleanpu the followed channels
        if conf_to_remove:
            self.follows = {k: v for k, v in self.follows.items() if k not in conf_to_remove}


class Twitch:
    "Follow Twitch channel and display alerts in Discord when one goes live."
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
            streams = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel':channels})
            self.live_cache = {s['channel']['_id']: s for s in streams['streams']}

        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            # Poll every minute
            await asyncio.sleep(60)

            # Get the streams statuses in chunks of 100
            channels = list(self.conf.follows.keys())
            for i in range(0, len(channels), 100):
                chunk = channels[i:i + 100]
                streams_chunk = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel':', '.join(chunk), 'limit': 100})
                for stream in streams_chunk['streams']:
                    if stream['channel']['_id'] not in self.live_cache:
                        try:
                            await self.notify(stream)
                        except Exception as e:
                            log.error('Notification error: {}'.format(e))
                        self.live_cache[stream['channel']['_id']] = stream

    async def notify(self, stream):
        user_id = str(stream['channel']['_id'])

        # Build the embed
        embed = discord.Embed(title=stream['channel']['status'], url=stream['channel']['url'], colour=0x738bd7)
        embed.set_author(name=stream['channel']['display_name'])
        embed.set_thumbnail(url=stream['channel']['logo'])
        embed.set_image(url=stream['preview']['large'])
        embed.add_field(name='Playing', value=stream['game'])
        embed.add_field(name='Delay', value='{} seconds.'.format(stream['delay']))

        # Make sure we're ready to send messages
        await self.bot.wait_until_ready()

        # Send the notification to every interesed channel
        for channel_id in self.conf.follows[user_id]:
            destination = self.bot.get_channel(channel_id)
            await destination.send(embed=embed)

    async def get_user(self, channel):
        data = await utils.fetch_page('https://api.twitch.tv/kraken/users', session=self.session, params={'login':channel})
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
    async def twitch_follow(self, ctx, channel):
        """Follows a twitch channel.

        When the given Twitch channel goes online, a notification will be sent
        in the Discord channel this command was used in.
        """
        user = await self.get_user(channel)
        user_id = user['_id']

        # Register it in the conf
        if user_id not in self.conf.follows.keys():
            self.conf.follows[user_id] = [ctx.channel.id]
        elif ctx.channel.id in self.conf.follows[user_id]:
            raise commands.BadArgument('Already following "{}" on this channel.'.format(channel))
        else:
            self.conf.follows[user_id].append(ctx.channel.id)
        self.conf.save()

        # Update the live streams cache if the stream is live
        streams = await utils.fetch_page('https://api.twitch.tv/kraken/streams', session=self.session, params={'channel':user_id})
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
            raise commands.BadArgument('Not following "{}" on this channel.'.format(channel))

        # Remove the discord channel from the conf and clean it up
        self.conf.follows[user_id].remove(ctx.channel.id)
        if not self.conf.follows[user_id]:
            del self.conf.follows[user_id]
        self.conf.save()

        # Cleanup the live streams cache
        try:
            self.live_cache[user_id]
        except KeyError:
            pass

        await ctx.send('\N{OK HAND SIGN}')
