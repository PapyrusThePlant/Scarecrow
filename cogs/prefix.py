import logging

import discord.ext.commands as commands

import paths
from .util import config, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Prefix(bot))


class Prefix(commands.Cog):
    """Custom prefixes per server."""
    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.PREFIXES_CONFIG, encoding='utf-8')
        self.saved_prefixes = self.bot.command_prefix
        self.bot.command_prefix = self.get_prefixes

    def cog_unload(self):
        self.bot.command_prefix = self.saved_prefixes

    def get_prefixes(self, bot, message):
        if message.guild is not None:
            prefixes = self.conf.guild_specific.get(message.guild.id, []) + self.conf.global_
        else:
            prefixes = [] + self.conf.global_

        if 'mention' in prefixes:
            prefixes[prefixes.index('mention')] = f'{message.guild.me.mention if message.guild else bot.user.mention} '

        return prefixes

    @commands.Cog.listener()
    async def on_guild_remove(self, guild):
        if guild.id in self.conf.guild_specific:
            del self.conf.guild_specific[guild.id]

    @commands.group(name='prefix')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def prefix_group(self, ctx):
        pass

    @prefix_group.command(name='add')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def prefix_add(self, ctx, prefix):
        """Adds a command prefix specific to this server.

        If you want a space after your prefix, enclose it in quotes.
        e.g :   @Scarecrow prefix add "pls bot "
                pls bot help
        """
        if prefix in self.get_prefixes(ctx.bot, ctx.message):
            raise commands.BadArgument('This prefix is already in place on this server.')

        sid = ctx.guild.id

        # Add the prefix to the server specific
        if sid in self.conf.guild_specific:
            self.conf.guild_specific.get(sid).append(prefix)
        else:
            self.conf.guild_specific[sid] = [prefix]

        # Save and acknowledge
        self.conf.save()
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @prefix_group.command(name='remove')
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def prefix_remove(self, ctx, prefix):
        """Removes a command prefix specific to this server."""
        sid = ctx.guild.id
        prefixes = self.conf.guild_specific.get(sid, None)

        if prefixes is None or prefix not in prefixes:
            raise commands.BadArgument('Prefix not found.')

        prefixes.remove(prefix)
        if not prefixes:
            del self.conf.guild_specific[sid]

        self.conf.save()
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')
