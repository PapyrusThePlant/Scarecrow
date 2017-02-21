import logging
from collections import Counter

import discord.utils
import discord.ext.commands as commands

import paths
from .util import checks, config, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Admin())


class IgnoredConfig(config.ConfigElement):
    def __init__(self, **kwargs):
        self.channels = kwargs.pop('channels', [])
        self.guilds = kwargs.pop('guilds', [])
        self.users = utils.dict_keys_to_int(kwargs.pop('users', {}))


class Admin:
    """Bot management commands and events."""
    def __init__(self):
        self.commands_used = Counter()
        self.ignored = config.Config(paths.IGNORED_CONFIG, encoding='utf-8')

    def __global_check(self, ctx):
        """A global check used on every command."""
        author = ctx.author
        guild = ctx.guild
        if author == ctx.bot.owner:
            return True

        if guild is not None:
            # Check if we're ignoring the guild
            if guild.id in self.ignored.guilds:
                return False

            # Guild owners can't be ignored
            if author.id == guild.owner.id:
                return True

            # Check if the user is banned from using the bot
            if author.id in self.ignored.users.get(guild.id, {}):
                return False

            # Check if the channel is banned, bypass this if the user has the manage guild permission
            channel = ctx.channel
            perms = channel.permissions_for(author)
            if not perms.manage_guild and channel.id in self.ignored.channels:
                return False
        return True

    def resolve_target(self, ctx, target):
        if target == 'channel':
            return ctx.channel, self.ignored.channels
        elif target == 'guild' or target == 'server':
            return ctx.guild, self.ignored.guilds

        # Try converting to a text channel
        try:
            conv = commands.TextChannelConverter()
            conv.prepare(ctx, target)
            channel = conv.convert()
        except commands.BadArgument:
            pass
        else:
            return channel, self.ignored.channels

        # Try converting to a user
        try:
            conv = commands.MemberConverter()
            conv.prepare(ctx, target)
            member = conv.convert()
        except commands.BadArgument:
            pass
        else:
            guild_id = ctx.guild.id
            try:
                return member, self.ignored.users[guild_id]
            except KeyError:
                self.ignored.users[guild_id] = []
                return member, self.ignored.users[guild_id]

        # Convert to a guild
        try:
            conv = utils.GuildConverter()
            conv.prepare(ctx, target)
            guild = conv.convert()
        except:
            pass
        else:
            return guild, self.ignored.guilds

        # Nope
        raise commands.BadArgument('"{}" not found.'.format(target))

    def validate_ignore_target(self, ctx, target):
        owner_id = ctx.bot.owner.id
        # Only let the bot owner unignore a guild owner
        if isinstance(target, discord.Member):
            # Do not ignore the bot owner
            if owner_id == target.id:
                raise commands.BadArgument('Cannot ignore/unignore the bot owner.')

            # Only allow the bot owner to unignore the guild owner
            if target.id == ctx.guild.owner.id and ctx.author.id != owner_id:
                raise commands.BadArgument('Only the bot owner can ignore/unignore the owner of a server.')
        elif isinstance(target, discord.Guild):
            # Only allow the bot owner to ignore guilds
            if ctx.author.id != owner_id:
                raise commands.BadArgument('Only the bot owner can ignore/unignore servers.')
        elif isinstance(target, discord.VoiceChannel):
            # Do not ignore voice channels
            raise commands.BadArgument('Cannot ignore/unignore voice channels.')

    @commands.command(no_pm=True)
    @commands.has_permissions(manage_guild=True)
    async def ignore(self, ctx, *, target):
        """Ignores a channel, a user (server-wide), or a whole server.

        The target can be a name, an ID, the keyword 'channel' or 'server'.
        """
        target, conf = self.resolve_target(ctx, target)
        self.validate_ignore_target(ctx, target)

        # Save the ignore
        conf.append(target.id)
        self.ignored.save()

        # Leave the server or acknowledge the ignore being successful
        if isinstance(target, discord.Guild):
            await target.leave()
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command(no_pm=True)
    @commands.has_permissions(manage_guild=True)
    async def unignore(self, ctx, *, target):
        """Un-ignores a channel, a user (server-wide), or a whole server."""
        target, conf = self.resolve_target(ctx, target)
        self.validate_ignore_target(ctx, target)

        try:
            conf.remove(target.id)
        except ValueError:
            await ctx.send('Target not found.')
        else:
            self.ignored.save()
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command()
    @checks.is_owner()
    async def restart(self, ctx):
        """Restarts the bot."""
        ctx.bot.restart()

    @commands.command()
    @checks.is_owner()
    async def shutdown(self, ctx):
        """Shuts the bot down."""
        ctx.bot.shutdown()

    @commands.command()
    @checks.is_owner()
    async def status(self, ctx, *, status=None):
        """Changes the bot's status."""
        await ctx.bot.change_presence(game=discord.Game(name=status))

    async def on_command(self, ctx):
        self.commands_used[ctx.command.qualified_name] += 1
        if ctx.guild is None:
            log.info('DM:{0.name}:{0.id}:{1}'.format(ctx.author, ctx.message.content))
        else:
            log.info('{0.name}:{0.id}:{1.name}:{1.id}:{2.name}:{2.id}:{3}'.format(ctx.guild, ctx.channel, ctx.author, ctx.message.content))

    async def on_guild_join(self, guild):
        # Log that the bot has been added somewhere
        log.info('GUILD_JOIN:{0.name}:{0.id}:{1.name}:{1.id}:'.format(guild, guild.owner))
        if guild.id in self.ignored.guilds:
            log.info('IGNORED GUILD:{0.name}:{0.id}:'.format(guild))
            await guild.leave()

    async def on_guild_remove(self, guild):
        # Log that the bot has been removed from somewhere
        log.info('GUILD_REMOVE:{0.name}:{0.id}:{1.name}:{1.id}:'.format(guild, guild.owner))
