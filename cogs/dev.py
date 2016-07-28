import inspect

from discord.ext import commands

from .util import checks, utils


def setup(bot):
    bot.add_cog(Dev(bot))


class Dev:
    """Dev tools and commands, owner only"""
    def __init__(self, bot):
        self.bot = bot

    def _resolve_module_name(self, name):
        if name in self.bot.cogs:
            return self.bot.cogs[name].__module__
        elif name in self.bot.extensions:
            return name
        elif name in [ext.split('.')[-1] for ext in self.bot.extensions.keys()]:
            return 'scarecrow.cogs.{}'.format(name)
        else:
            return None

    @commands.group(name='cogs', pass_context=True, invoke_without_command=True)
    @checks.is_owner()
    async def cogs_group(self, ctx):
        """Cogs management commands.

        If no subcommand is invoked, lists loaded cogs."""
        if ctx.subcommand_passed is not None:
            return

        entries = []

        for name in self.bot.cogs:
            cog = self.bot.cogs[name]

            # Get the first line of the doc
            help_doc = inspect.getdoc(cog)
            help_doc = '' if help_doc is None else help_doc.split('\n', 1)[0]
            if isinstance(help_doc, bytes):
                help_doc = help_doc.decode('utf-8')

            entries.append((name, help_doc))

        content = utils.indented_entry_to_str(entries)
        await self.bot.say_block(content)

    @cogs_group.command(name='load')
    @checks.is_owner()
    async def cogs_load(self, *, name: str):
        """Loads a cog from name."""
        module_path = 'scarecrow.cogs.{}'.format(name)

        if module_path in self.bot.extensions:
            await self.bot.say('{} already loaded.'.format(name))
        else:
            try:
                self.bot.load_extension(module_path)
            except ImportError:
                await self.bot.say('Could not find module.')
            else:
                await self.bot.say(':ok_hand:')

    @cogs_group.command(name='reload')
    @checks.is_owner()
    async def cogs_reload(self, name: str):
        """Reloads a cog from name."""
        module_path = self._resolve_module_name(name)
        if module_path is None:
            await self.bot.say('{} not loaded.'.format(name))
            return

        self.bot.unload_extension(module_path)
        self.bot.load_extension(module_path)

        await self.bot.say(':ok_hand:')

    @cogs_group.command(name='unload')
    @checks.is_owner()
    async def cogs_unload(self, *, name: str):
        """Unloads a cog from name."""
        module_path = self._resolve_module_name(name)
        if module_path is None:
            await self.bot.say('{} not loaded.'.format(name))
            return

        self.bot.unload_extension(module_path)
        await self.bot.say(':ok_hand:')

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def debug(self, ctx, *, code: str):
        """eval()"""
        code = code.strip('` ')

        env = {
            'cog': self,
            'bot': self.bot,
            'ctx': ctx,
            'message': ctx.message,
            'channel': ctx.message.channel,
            'server': ctx.message.server
        }

        env.update(globals())

        try:
            result = eval(code, env)
            if inspect.isawaitable(result):
                result = await result
        except Exception as e:
            content = type(e).__name__ + ': ' + str(e)
        else:
            content = result

        await self.bot.say_block(content)
