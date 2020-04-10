import asyncio
import datetime
import logging

import aiohttp
import discord
import discord.ext.commands as commands

import paths
from utils import config, utils

log = logging.getLogger(__name__)


def setup(bot):
    raise NotImplementedError()
    cog = Twitch(bot)
    bot.add_cog(cog)
    cog.start()


class TwitchError(commands.CommandError):
    pass


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
        for stream_id, destinations in self.follows.items():
            # Remove the given channels from this followed channel
            for channel in channels:
                try:
                    del destinations.channels[channel]
                except KeyError:
                    pass
            if not destinations.channels:
                conf_to_remove.add(stream_id)

        # Cleanup the followed channels
        for stream_id in conf_to_remove:
            del self.follows[stream_id]


class FollowConfig(config.ConfigElement):
    def __init__(self, stream_id, live=False, preview_url=None, preview_updates=0, **kwargs):
        self.stream_id = stream_id
        self.live = live
        self.preview_url = preview_url
        self.preview_updates = preview_updates
        self.channels = utils.dict_keys_to_int(kwargs.pop('channels', {}))

    async def put_offline(self, bot):
        for channel_conf in self.channels.values():
            await channel_conf.put_offline(bot)
        self.preview_updates = 0
        self.live = False

    async def update(self, bot, stream_info):
        url = f'{self.preview_url}?v={str(self.preview_updates + 1)}'
        for channel_id, chan_conf in self.channels.items():
            message = await chan_conf.get_message(bot)
            if not message or not message.embeds: # Sometimes embeds disappear
                await chan_conf.put_offline(bot)
                continue

            # Update the stream preview, title and played game
            embed = message.embeds[0]
            embed.set_image(url=url)
            embed.title = stream_info['channel']['status']
            embed.description = f'Playing [{stream_info["game"]}](https://www.twitch.tv/directory/game/{stream_info["game"]})'

            await message.edit(embed=embed)
        self.preview_updates += 1


class ChannelConfig(config.ConfigElement):
    def __init__(self, id, content, message_id=None, **kwargs):
        self.id = id
        self.content = content
        self.message_id = message_id
        self._message = None

    async def get_message(self, bot):
        if self._message is None:
            self._message = await bot.get_message(bot.get_channel(self.id), self.message_id)
        return self._message

    async def put_offline(self, bot):
        if self.message_id is None:
            return

        # Get the notification's embed
        message = await self.get_message(bot)
        if not message or not message.embeds: # Sometimes embeds disappear
            self.message_id = None
            self._message = None
            return

        embed = message.embeds[0]

        # Remove the image preview, modify the title and timestamp
        del embed._image
        embed.title = 'Offline'
        embed.description = None
        embed.timestamp = datetime.datetime.utcnow()

        # Send the edit and remove the message's reference in the conf
        await message.edit(embed=embed)
        self.message_id = None
        self._message = None


class Twitch:
    """Follow Twitch channel and display alerts in Discord when one goes live."""
    api_base = 'https://api.twitch.tv/kraken'

    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.TWITCH_CONFIG, encoding='utf-8')
        default_headers = {
            'Client-ID': self.conf.client_id,
            'Accept': 'application/vnd.twitchtv.v5+json'
        }
        self.session = aiohttp.ClientSession(loop=bot.loop, headers=default_headers)
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
        self.start()

    def start(self):
        if self.daemon is None:
            self.daemon = self.bot.loop.create_task(self._daemon())

    async def _daemon(self):
        # ERMAHGERD ! MAH FRAVRIT LERP !
        while True:
            try:
                streams = await self.poll_streams()
            except Exception as e:
                log.info(f'Polling error: {e}')
            else:
                await self.bot.wait_until_ready()
                for stream_id, follow_conf in self.conf.follows.copy().items():
                    if follow_conf.live:
                        if stream_id not in streams:
                            try:
                                # Stream went offline, remove the preview images
                                await follow_conf.put_offline(self.bot)
                            except Exception as e:
                                log.error(f'Preview removal error: {e}')
                        else:
                            try:
                                # Stream is still online, update its info
                                await follow_conf.update(streams[stream_id])
                            except Exception as e:
                                log.error(f'Update error: {e}')
                    elif stream_id in streams:
                        # Stream came online, save the preview url and send notifications
                        stream_info = streams[stream_id]
                        follow_conf.preview_url = stream_info['preview']['template'].format(width=640, height=360)
                        try:
                            await self.notify(stream_info)
                        except Exception as e:
                            log.error(f'Notification error: {e}')
                        else:
                            follow_conf.live = True
                    self.conf.save()
            finally:
                await asyncio.sleep(60)

    async def poll_streams(self):
        streams = {}

        # Get the streams statuses in chunks of 100
        channels = list(self.conf.follows.keys())
        for i in range(0, len(channels), 100):
            chunk = channels[i:i + 100]
            try:
                streams_chunk = await utils.fetch_page(f'{self.api_base}/streams', session=self.session, params={'channel': ', '.join(chunk), 'limit': 100})
            except utils.HTTPError as e:
                raise Exception(f'HTTP error when fetching streams chunk #{i / 100 + 1} : {e}') from e

            # Extract the newly live streams
            for stream_info in streams_chunk['streams']:
                stream_id = str(stream_info['channel']['_id'])
                streams[stream_id] = stream_info

        return streams

    async def notify(self, stream_info):
        # Build the embed
        embed = discord.Embed(url=stream_info['channel']['url'],
                              colour=discord.Colour.blurple(),
                              title=stream_info['channel']['status'],
                              description=f'Playing [{stream_info["game"]}](https://www.twitch.tv/directory/game/{stream_info["game"]})')
        embed.set_author(name=stream_info['channel']['display_name'])
        embed.set_thumbnail(url=stream_info['channel']['logo'])
        embed.set_image(url=stream_info['preview']['large'])
        embed.timestamp = datetime.datetime.strptime(stream_info['created_at'], '%Y-%m-%dT%H:%M:%SZ')

        # Send the notification to every interested channel
        for channel_id, chan_conf in self.conf.follows[str(stream_info['channel']['_id'])].channels.items():
            destination = self.bot.get_channel(channel_id)
            if not destination.permissions_for(self.bot.user).embed_links:
                await destination.send(f'Missing permissions to embed links to send stream notification for {stream_info["channel"]["url"]}. Retrying later.')
            else:
                chan_conf._message = await destination.send(chan_conf.content, embed=embed)
                chan_conf.message_id = chan_conf._message.id
                self.conf.save()

    async def get_user(self, channel):
        try:
            data = await utils.fetch_page(f'{self.api_base}/users', session=self.session, params={'login': channel})
        except utils.HTTPError as e:
            if e.code == 400:
                raise commands.BadArgument(e.message)
            else:
                raise e
        count = data['_total']
        if count == 0:
            raise commands.BadArgument('Channel not found.')
        elif count > 1:
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
        """Follows a Twitch channel.

        When the given Twitch channel goes online, a notification will be sent
        in the Discord channel this command was used in.

        The message will be sent along the stream notification.
        """
        user = await self.get_user(channel)
        user_id = user['_id']
        channel_id = ctx.channel.id

        if channel not in self.conf.follows.keys():
            self.conf.follows[user_id] = FollowConfig(user_id)
        elif channel_id in self.conf.follows[user_id].channels:
            raise commands.BadArgument(f'Already following "{channel}" on this channel.')

        self.conf.follows[user_id].channels[channel_id] = ChannelConfig(channel_id, message)
        self.conf.save()

        # Check if the channel is live
        streams = await utils.fetch_page(f'{self.api_base}/streams', session=self.session, params={'channel': user_id})
        if streams['_total'] == 1:
            self.conf.follows[user_id].preview_url = streams['streams'][0]['preview']['template'].format(width=640, height=360)
            await self.notify(streams['streams'][0])
            self.conf.follows[user_id].live = True

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

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
        if user_id not in self.conf.follows.keys() or ctx.channel.id not in self.conf.follows[user_id].channels:
            raise commands.BadArgument(f'Not following "{channel}" on this channel.')

        # Remove the discord channel from the conf and clean it up if no one else follow that stream
        await self.conf.follows[user_id].channels[ctx.channel.id].put_offline(self.bot)
        del self.conf.follows[user_id].channels[ctx.channel.id]
        if not self.conf.follows[user_id].channels:
            del self.conf.follows[user_id]
        self.conf.save()

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
