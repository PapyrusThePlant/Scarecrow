import logging
from collections import Counter

import discord.ext.commands as commands
import discord.utils

import paths
from .util import checks, config, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Admin(bot))


class IgnoredConfig(config.ConfigElement):
    def __init__(self, **kwargs):
        self.channels = kwargs.pop('channels', [])
        self.servers = kwargs.pop('servers', [])
        self.users = kwargs.pop('users', {})


class Admin:
    """Bot management commands and events."""
    def __init__(self, bot):
        self.bot = bot
        self.commands_used = Counter()
        self.ignored = config.Config(paths.IGNORED_CONFIG, encoding='utf-8')

    def __check(self, ctx):
        """A global check used on every command."""
        author = ctx.message.author
        if author == ctx.bot.owner or author == ctx.message.server.owner:
            return True

        server = ctx.message.server

        # Check if we're ignoring the server
        if server.id in self.ignored.servers:
            return False

        # Check if the user is banned from using the bot
        if author.id in self.ignored.users.get(server.id, {}):
            return False

        # Check if the channel is banned, bypass this if the user has the administrator permission
        channel = ctx.message.channel
        perms = channel.permissions_for(author)
        if not perms.administrator and channel.id in self.ignored.channels:
            return False

        return True

    def resolve_target(self, ctx, target):
        if target == 'channel':
            target = ctx.message.channel, self.ignored.channels
        elif target == 'server':
            return ctx.message.server, self.ignored.servers

        # Try converting to a channel
        try:
            channel = commands.ChannelConverter(ctx, target).convert()
        except commands.BadArgument:
            pass
        else:
            return channel, self.ignored.channels

        # Try converting to a user
        try:
            user = commands.MemberConverter(ctx, target).convert()
        except commands.BadArgument:
            pass
        else:
            server_id = ctx.message.server.id
            r_conf = self.ignored.users.get(server_id, None)
            if r_conf is None:
                self.ignored.users[server_id] = []
            return user, self.ignored.users[server_id]

        # Convert to a server, let it raise commands.errors.BadArgument if we still can't make sense of the target
        server = utils.ServerConverter(ctx, target).convert()
        return server, self.ignored.servers

    async def valid_ignore_target(self, ctx, target):
        # Only let the bot owner unignore a server owner
        if isinstance(target, discord.Member):
            # Do not ignore the bot owner
            if self.bot.owner.id == target.id:
                await self.bot.say('Cannot ignore the bot owner.')
                return False

            # Only allow the bot owner to unignore the server owner
            if target.id == ctx.message.server.owner.id and ctx.message.author.id != self.bot.owner.id:
                await self.bot.say('Only the bot owner can unignore the owner of a server.')
                return False
        elif isinstance(target, discord.Server):
            # Only allow the bot owner to ignore servers
            if ctx.message.author.id != self.bot.owner.id:
                await self.bot.say('Only the bot owner can ignore/unignore servers.')
                return False
        elif isinstance(target, discord.Channel):
            # Do not ignore voice channels or channels from other servers
            if target.type != discord.ChannelType.text:
                await self.bot.say('Cannot ignore/unignore voice channels.')
                return False

        # Let's ignore this fucker
        return True

    @commands.command(pass_context=True, no_pm=True)
    @commands.has_permissions(manage_server=True)
    async def ignore(self, ctx, *, target):
        """Ignores a channel, a user (server-wide), or a whole server.

        The target can be a name, an ID, the keyword 'channel' or 'server'.
        """
        if target == 'channel':
            target = ctx.message.channel.id
        elif target == 'server':
            target = ctx.message.server.id
        target, conf = self.resolve_target(ctx, target)

        # Check if the target is valid to ignore
        if not await self.valid_ignore_target(ctx, target):
            return

        # Save the ignore
        conf.append(target.id)
        self.ignored.save()

        # Leave the server or acknowledge the ignore being successful
        if isinstance(target, discord.Server):
            await self.bot.leave_server(target)
        else:
            await self.bot.say('\N{OK HAND SIGN}')

    @commands.command(pass_context=True, no_pm=True)
    @commands.has_permissions(manage_server=True)
    async def unignore(self, ctx, *, target):
        """Un-ignores a channel, a user (server-wide), or a whole server."""
        target, conf = self.resolve_target(ctx, target)

        # Check if the target is valid to unignore
        if not await self.valid_ignore_target(ctx, target):
            return

        try:
            conf.remove(target.id)
        except ValueError:
            await self.bot.say('Target not found.')
        else:
            self.ignored.save()
            await self.bot.say('\N{OK HAND SIGN}')

    @commands.command(hidden=True, pass_context=True, no_pm=True)
    @checks.is_owner()
    async def kill(self, ctx, *, who):
        if who == 'yourself':
            # Aww mean D:
            await self.bot.say('Committing sudoku...\nhttp://i.imgur.com/emefsOg.jpg')
            self.bot.do_restart = False
            self.bot.shutdown()
            return

        if not ctx.message.channel.permissions_for(ctx.message.server.me).kick_members:
            await self.bot.say('My power is not over 9000, sorry.')
            return

        try:
            member = commands.MemberConverter(ctx, who).convert()
        except commands.BadArgument:
            await self.bot.say('Member not found.')
        else:
            if member.id == self.bot.owner.id:
                await self.bot.say('Cannot kill the bot owner.')
            elif member.id == ctx.message.server.owner.id:
                await self.bot.say('Cannot kill the server owner.')
            else:
                await self.bot.say('http://i.imgur.com/k3n09s9.png')
                await self.bot.kick(member)

    @commands.command()
    @checks.is_owner()
    async def restart(self):
        """Restarts the bot."""
        self.bot.restart()

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
        # Log the command usage
        self.commands_used[command.qualified_name] += 1
        m = ctx.message
        if m.server is not None:
            log.info('{0.name}:{0.id}:{1.name}:{1.id}:{2.name}:{2.id}:{3}'.format(m.server, m.channel, m.author, m.content))
        else:
            log.info('DM:{0.name}:{0.id}:{1}'.format(m.author, m.content))

    async def on_server_join(self, server: discord.Server):
        # Log that the bot has been added somewhere
        log.info('GUILD_JOIN:{0.name}:{0.id}:{1.name}:{1.id}:'.format(server, server.owner))
        if server.id in self.ignored.servers:
            log.info('IGNORED SERVER:{0.name}:{0.id}:'.format(server))

    async def on_server_remove(self, server: discord.Server):
        # Log that the bot has been removed from somewhere
        log.info('GUILD_REMOVE:{0.name}:{0.id}:{1.name}:{1.id}:'.format(server, server.owner))
