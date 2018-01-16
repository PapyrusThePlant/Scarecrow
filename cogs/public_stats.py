import aiohttp
import json
import logging

from .util import utils

log = logging.getLogger(__name__)


def setup(bot):
    if not bot.debug_instance:
        bot.add_cog(PublicStats(bot))


class PublicStats:
    """Automated stats collection and publication."""
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.guild_count = 0

    def __unload(self):
        self.session.close()

    async def on_ready(self):
        await self.send_stats()

    async def on_guild_join(self, guild):
        await self.send_stats()

    async def on_guild_remove(self, guild):
        await self.send_stats()

    async def send_stats(self):
        guild_count = len(self.bot.guilds)
        if self.guild_count == guild_count:
            return

        # Post to DiscordBots
        url = f'https://bots.discord.pw/api/bots/{self.bot.user.id}/stats'
        headers = {
            'authorization': self.bot.conf.dbots_token,
            'content-type': 'application/json'
        }
        data = {
            'server_count': guild_count
        }
        async with self.session.post(url=url, headers=headers, data=json.dumps(data)) as resp:
            if resp.status < 200 or resp.status >= 300:
                log.warning(utils.HTTPError(resp, 'Error while posting stats to DBots'))

        # Save the new server count after the post succeeded
        self.guild_count = guild_count