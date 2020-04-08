import aiohttp
import json
import logging

import discord.ext.commands as commands

from .util import utils

log = logging.getLogger(__name__)


def setup(bot):
    if not bot.debug_instance:
        bot.add_cog(PublicStats(bot))


class PublicStats(commands.Cog):
    """Automated stats collection and publication."""
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.guild_count = 0
        self.shard_count = 0

    def cog_unload(self):
        self.session.close()

    @commands.Cog.listener()
    async def on_ready(self):
        await self.send_stats()

    @commands.Cog.listener()
    async def on_guild_join(self, guild):
        await self.send_stats()

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        await self.send_stats()

    async def send_stats(self):
        guild_count = len(self.bot.guilds)
        shard_count = self.bot.shard_count

        if self.guild_count == guild_count and self.shard_count == shard_count:
            return

        # Post to Discord Bots
        url = f'https://discord.bots.gg/api/v1/bots/{self.bot.user.id}/stats'
        headers = {
            'authorization': self.bot.conf.discord_bots_token,
            'content-type': 'application/json'
        }
        data = {
            'shardCount': shard_count,
            'guildCount': guild_count
        }
        async with self.session.post(url=url, headers=headers, data=json.dumps(data)) as resp:
            if resp.status < 200 or resp.status >= 300:
                log.warning(utils.HTTPError(resp, 'Error while posting stats to Discord Bots.'))

        # Save the new counts after the post succeeded
        self.guild_count = guild_count
        self.shard_count = shard_count
