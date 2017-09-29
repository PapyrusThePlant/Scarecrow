import logging
from collections import Counter

import discord.utils
import discord.ext.commands as commands

import paths
from .util import checks, config, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Admin(bot))


class IgnoredConfig(config.ConfigElement):
    def __init__(self, **kwargs):
        self.channels = kwargs.pop('channels', [])
        self.guilds = kwargs.pop('guilds', [])
        self.users = utils.dict_keys_to_int(kwargs.pop('users', {}))


class Admin:
    """Bot management commands and events."""
    def __init__(self, bot):
        self.commands_used = Counter()
        self.ignored = config.Config(paths.IGNORED_CONFIG, encoding='utf-8')
        self.bot = bot

    def __global_check_once(self, ctx):
        """A global check used on every command."""
        author = ctx.author
        guild = ctx.guild
        if author == ctx.bot.owner:
            return True

        if guild is not None:
            # Check if we're ignoring the guild
            if guild.id in self.ignored.guilds:
                return False

            if ctx.channel.id in self.ignored.channels:
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

    async def resolve_target(self, ctx, target):
        if target == 'channel':
            return ctx.channel, self.ignored.channels
        elif target == 'guild' or target == 'server':
            return ctx.guild, self.ignored.guilds

        # Try converting to a text channel
        try:
            channel = await commands.TextChannelConverter().convert(ctx, target)
        except commands.BadArgument:
            pass
        else:
            return channel, self.ignored.channels

        # Try converting to a user
        try:
            member = await commands.MemberConverter().convert(ctx, target)
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
            guild = await utils.GuildConverter().convert(ctx, target)
        except:
            pass
        else:
            return guild, self.ignored.guilds

        # Nope
        raise commands.BadArgument(f'"{target}" not found.')

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

    @commands.command(aliases=['checkpermissions'])
    async def checkperms(self, ctx):
        name = ctx.bot.user.name
        perms_str = 'Read Messages, Send Messages, Manage Messages, Embed Links, Read Message History, Use External Emojis, Add Reactions'
        perms = discord.Permissions(486464)

        # Check the integration role
        role = discord.utils.get(ctx.guild.roles, name=name)
        if not role or not perms <= role.permissions:
            raise commands.UserInputError(f'Please make sure the integration role `{name}` has all the following permissions and is added to the bot :\n'
                                          f'{perms_str}.\n'
                                          f'Note that you can also kick and re-invite the bot with its default permissions.')

        # Check every channel for overwrites
        failed = []
        for channel in sorted(ctx.guild.text_channels, key=lambda c: c.position):
            if not perms <= channel.permissions_for(ctx.guild.me):
                failed.append(channel)
        if failed:
            raise commands.UserInputError(f'Please make sure the channel permissions overwrites for the following channels do not remove these permissions from the bot :\n'
                                          f'{perms_str}.\n'
                                          f'{" ".join(c.mention for c in failed)}')

        await ctx.send('All good.')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def ignore(self, ctx, *, target):
        """Ignores a channel, a user (server-wide), or a whole server.

        The target can be a name, an ID, the keyword 'channel' or 'server'.
        """
        target, conf = await self.resolve_target(ctx, target)
        self.validate_ignore_target(ctx, target)

        # Save the ignore
        conf.append(target.id)
        self.ignored.save()

        # Leave the server or acknowledge the ignore being successful
        if isinstance(target, discord.Guild):
            await target.leave()
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def unignore(self, ctx, *, target):
        """Un-ignores a channel, a user (server-wide), or a whole server."""
        target, conf = await self.resolve_target(ctx, target)
        self.validate_ignore_target(ctx, target)

        try:
            conf.remove(target.id)
        except ValueError:
            await ctx.send('Target not found.')
        else:
            self.ignored.save()
            await ctx.send('\N{OK HAND SIGN}')

    def get_prune_candidates(self, bot):
        candidates = [g for g in bot.guilds if len([m for m in g.members if m.bot]) >= len(g.members) / 2]
        twitter_destinations = set(chan_id for f in bot.cogs['Twitter'].conf.follows.values() for chan_id in f.discord_channels)
        twitch_destinations = set(chan_id for f in bot.cogs['Twitch'].conf.follows.values() for chan_id in f.keys())

        for guild in candidates:
            guild_channels = set(c.id for c in guild.text_channels)
            if twitter_destinations.intersection(guild_channels) or twitch_destinations.intersection(guild_channels):
                candidates.remove(guild)

        return candidates

    @commands.group(name='prune_guilds', invoke_without_command=True)
    @checks.is_owner()
    async def prune_guilds_group(self, ctx):
        targets = self.get_prune_candidates(ctx.bot)
        if targets:
            log.info(f'Leaving {len(targets)} guilds.')

        for guild in targets:
            await guild.leave()

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @prune_guilds_group.command(name='count')
    @checks.is_owner()
    async def prune_guilds_count(self, ctx):
        await ctx.send(len(self.get_prune_candidates(ctx.bot)))

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
        self.bot.conf.status = status
        self.bot.conf.save()

    async def on_command(self, ctx):
        self.commands_used[ctx.command.qualified_name] += 1
        if ctx.guild is None:
            log.info(f'DM:{ctx.author.name}:{ctx.author.id}:{ctx.message.content}')
        else:
            log.info(f'{ctx.guild.name}:{ctx.guild.id}:{ctx.channel.name}:{ctx.channel.id}:{ctx.author.name}:{ctx.author.id}:{ctx.message.content}')

    async def on_guild_join(self, guild):
        # Log that the bot has been added somewhere
        log.info(f'GUILD_JOIN:{guild.name}:{guild.id}:{guild.owner.name}:{guild.owner.id}:')
        if guild.id in self.ignored.guilds:
            log.info(f'IGNORED GUILD:{guild.name}:{guild.id}:')
            await guild.leave()

    async def on_guild_remove(self, guild):
        # Log that the bot has been removed from somewhere
        log.info(f'GUILD_REMOVE:{guild.name}:{guild.id}:{guild.owner.name}:{guild.owner.id}:')
