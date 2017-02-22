import aiohttp
import json
import logging

from .util import utils

log = logging.getLogger(__name__)


def setup(bot):
    if not bot.debug_instance:
        bot.add_cog(PublicStats(bot))


class PublicStats:
    def __init__(self, bot):
        self.bot = bot
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.server_count = 0

    async def on_ready(self):
        await self.send_stats()

    async def on_server_join(self, server):
        await self.send_stats()

    async def on_server_remove(self, server):
        await self.send_stats()

    async def send_stats(self):
        server_count = len(self.bot.servers)
        if self.server_count == server_count:
            return

        # Post to DiscordBots
        url = 'https://bots.discord.pw/api/bots/{}/stats'.format(self.bot.user.id)
        headers = {
            'authorization': self.bot.conf.dbots_token,
            'content-type': 'application/json'
        }
        data = {
            'server_count': server_count
        }
        async with self.session.post(url=url, headers=headers, data=json.dumps(data)) as resp:
            if resp.status != 200:
                log.warning(utils.HTTPError(resp, 'Error while posting stats to DBots'))

        # Save the new server count after the post succeeded
        self.server_count = server_count