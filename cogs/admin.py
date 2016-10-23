import asyncio
import logging
from collections import Counter

import discord.ext.commands as commands
import discord.utils

import paths
from .util import checks, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Admin(bot))


class Admin:
    """Bot management commands and events."""
    def __init__(self, bot):
        self.bot = bot
        self.commands_used = Counter()

    def __check(self, ctx):
        """A global check used on every command."""
        author = ctx.message.author
        if author == ctx.bot.owner:
            return True

        conf = self.bot.conf
        server = ctx.message.server

        # Check if we're ignoring the server
        if server.id in conf.ignored_servers:
            return False

        # Check if the user is banned from using the bot
        if author in conf.ignored_users[server.id]:
            return False

        # Check if the channel is banned, bypass this if the user has the administrator permission
        channel = ctx.message.channel
        perms = channel.permissions_for(author)
        if not perms.administrator and channel.id in conf.ignored_channels:
            return False

        return True

    def resolve_target(self, ctx, target):
        conf = self.bot.conf

        if target == 'channel':
            target = ctx.message.channel, conf.ignored_channels
        elif target == 'server':
            return ctx.message.server, conf.ignored_servers

        # Try converting to a channel
        try:
            channel = commands.ChannelConverter(ctx, target).convert()
        except commands.errors.BadArgument:
            pass
        else:
            return channel, conf.ignored_channels

        # Try converting to a user
        try:
            user = commands.MemberConverter(ctx, target).convert()
        except commands.errors.BadArgument:
            pass
        else:
            return user, conf.ignored_users[ctx.message.server.id]

        # Try converting to a channel
        server = utils.ServerConverter(ctx, target).convert()
        return server, conf.ignored_servers

    @commands.command(pass_context=True)
    @checks.has_permissions(manage_server=True)
    async def ignore(self, ctx, *, target):
        """Ignores either a channel, a user (server-wide), or a whole server.

        A server owner cannot be ignored on his own server.
        If the bot is invited to an ignored server, it will leave it.
        """
        target, conf = self.resolve_target(ctx, target)

        # Do not ignore the server owner
        if isinstance(target, discord.Member) and ctx.server.owner_id == target.id:
            return

        # Save the ignore
        conf.append(target.id)
        self.bot.conf.save()

        # Leave the server or acknowledge the ignore being successful
        if isinstance(target, discord.Server):
            await self.bot.leave_server(target)
        else:
            await self.bot.say(':ok_hand:')

    @commands.command(pass_context=True)
    @checks.has_permissions(manage_server=True)
    async def unignore(self, ctx, *, target):
        """Un-ignores either a channel, a user (server-wide), or a whole server."""
        target, conf = self.resolve_target(ctx, target)
        conf.remove(target.id)
        self.bot.conf.save()
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
    async def restart(self, mode=None):
        """Restarts the bot."""
        if mode is not None and mode != 'deep':
            await self.bot.say("Unknown restart mode.")
            return
        self.bot.restart(mode)

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

        if server.id in self.bot.conf.ignored_servers:
            # Hiiiik ! A bad server ! let's scare it and run away
            await self.bot.send_message(server.default_channel, utils.random_line(paths.INSULTS))
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
