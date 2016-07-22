import asyncio
import logging
from collections import Counter

import discord.ext.commands as commands
import discord.utils
import scarecrow.cogs.checks as checks
import scarecrow.cogs.utils as utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Admin(bot))


class Admin:
    """Bot management commands and events"""
    def __init__(self, bot):
        self.bot = bot
        self.banned_servers = []
        self.commands_used = Counter()

    @commands.command(hidden=True)
    @checks.is_owner()
    async def ban_server(self, server_id=None):
        """Adds a server to the bot's banned server list.

        Usage : ban_server <server id>

        Upon being invited to a banned server the bot will automatically leave it.
        """
        if server_id is not None:
            self.banned_servers.append(server_id)
            await self.bot.say(':ok_hand:')

    @commands.command(hidden=True)
    @checks.is_owner()
    async def unban_server(self, server_id):
        """Removes a server from the bot's banned server list.

        Usage : unban_server <server id>
        """
        if server_id in self.banned_servers:
            self.banned_servers.remove(server_id)
            await self.bot.say(':ok_hand:')

    @commands.command(hidden=True)
    @checks.is_owner()
    async def kill(self, who):
        if who == 'yourself':
            # Aww mean D:
            await self.bot.say('Committing sudoku...\nhttp://i.imgur.com/emefsOg.jpg')
            self.bot.shutdown()

    @commands.command()
    @checks.is_owner()
    async def restart(self):
        """Restarts the bot."""
        self.bot.restart()

    @commands.command()
    @checks.is_owner()
    async def reload(self):
        """Reloads the bot."""
        self.bot.reload()

    @commands.command()
    @checks.is_owner()
    async def shutdown(self):
        """Shuts the bot down."""
        self.bot.shutdown()

    @commands.command()
    @checks.is_owner()
    async def status(self, *, status=None):
        """Changes the bot's status."""
        await self.bot.change_status(discord.Game(name=status))

    async def on_command(self, command, ctx):
        name = command.name
        self.commands_used[name] += 1

        log.info('{0.server.name}:#{0.channel.name}:{0.author.name}:{0.author.id}:{0.content}'.format(ctx.message))

    async def on_server_join(self, server: discord.Server):
        # Notify the owner that the bot has been invited somewhere
        await self.bot.send_message(self.bot.owner, "Joined new server {0.name} ({0.id}).\n"
                                                    "Owner is {1.name} ({1.id})".format(server, server.owner))

        if server.id in self.banned_servers:
            # Hiiiik ! A bad server ! let's scare it and run away
            await self.bot.send_message(server.default_channel, utils.random_line('data/insults.txt'))
            await self.bot.leave_server(server)

            # Reassure our owner
            await self.bot.send_message(self.bot.owner, "Left that nasty server. Phew! That was close.")
            return

        # Say hi, people love it when you say hi
        message = await self.bot.send_message(server.default_channel,
                                              "Hi I am the bright bot that will enlighten your day !\n"
                                              "Say whatever you want to get my attention, I might just ignore it.\n"
                                              "I like biscuits, and I don't mean cookies.\n"
                                              "Though I do like cookies, which are not just biscuits.\n"
                                              "Just like scones. Not scone scones, but scones.\n"
                                              "Get it ?")
        asyncio.sleep(1)
        await self.bot.edit_message(message, 'lol jk.')
        asyncio.sleep(1)
        await self.bot.delete_message(message)
