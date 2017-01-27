import logging

import discord.ext.commands as commands

import paths
from .util import checks, config

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Prefix(bot))


class PrefixesConfig(config.ConfigElement):
    def __init__(self, global_, **kwargs):
        self.global_ = global_
        self.server_specific = kwargs.get('server_specific', {})


class Prefix:
    def __init__(self, bot):
        self.bot = bot
        self.conf = config.Config(paths.PREFIXES_CONFIG, encoding='utf-8')
        self.saved_prefixes = self.bot.command_prefix
        self.bot.command_prefix = self.get_prefixes

    def __unload(self):
        self.bot.command_prefix = self.saved_prefixes

    def get_prefixes(self, bot, message):
        prefixes = self.conf.server_specific.get(message.server.id, []) + self.conf.global_
        if 'mention' in prefixes:
            prefixes.remove('mention')
            prefixes.append('{} '.format(message.server.me.mention))
        return prefixes

    @commands.group(name='prefix', no_pm=True)
    async def prefix_group(self):
        pass

    @commands.has_permissions(manage_server=True)
    @prefix_group.command(name='add', pass_context=True, no_pm=True)
    async def prefix_add(self, ctx, *, prefix):
        """Adds a command prefix specific to this server.

        Adding 'mention' will define the bot's mention as a prefix.
        """
        if prefix in self.get_prefixes(self.bot, ctx.message):
            await self.bot.say('This prefix is already in place on this server.')
            return

        sid = ctx.message.server.id

        # Add the prefix to the server specific
        if sid in self.conf.server_specific:
            self.conf.server_specific.get(sid).append(prefix)
        else:
            self.conf.server_specific[sid] = [prefix]

        # Save and acknowledge
        self.conf.save()
        await self.bot.say('\N{OK HAND SIGN}')

    @commands.has_permissions(manage_server=True)
    @prefix_group.command(name='remove', pass_context=True, no_pm=True)
    async def prefix_remove(self, ctx, *, prefix):
        """Removes a command prefix specific to this server."""
        sid = ctx.message.server.id
        prefixes = self.conf.server_specific.get(sid, None)

        if prefixes is None or prefix not in prefixes:
            await self.bot.say('Prefix not found.')
        else:
            prefixes.remove(prefix)
            if not prefixes:
                del self.conf.server_specific[sid]
            self.conf.save()

        await self.bot.say('\N{OK HAND SIGN}')
