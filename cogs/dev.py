import asyncio
import inspect
import io
import textwrap
import traceback
from contextlib import redirect_stdout

import discord
from discord.ext import commands

from .util import checks, utils


def setup(bot):
    bot.add_cog(Dev(bot))


class Dev:
    """Dev tools and commands, mostly owner only."""
    def __init__(self, bot):
        self.bot = bot
        self.debug_env = {}
        self.cleanup_task = None
        self.clear_debug_env()

    def _resolve_module_name(self, name):
        if name in self.bot.cogs:
            return self.bot.cogs[name].__module__
        elif name in self.bot.extensions:
            return name
        elif name in [ext.split('.')[-1] for ext in self.bot.extensions.keys()]:
            return 'cogs.{}'.format(name)
        else:
            return None

    @commands.group(name='cogs', pass_context=True, invoke_without_command=True)
    async def cogs_group(self, ctx):
        """Lists currently loaded cogs."""
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
        module_path = 'cogs.{}'.format(name.lower())
        if module_path in self.bot.extensions:
            await self.bot.say('{} already loaded.'.format(name))
        else:
            try:
                self.bot.load_extension(module_path)
            except ImportError:
                await self.bot.say('Could not find module.')
            else:
                await self.bot.say('\N{OK HAND SIGN}')

    @cogs_group.command(name='reload')
    @checks.is_owner()
    async def cogs_reload(self, name: str):
        """Reloads a cog."""
        module_path = self._resolve_module_name(name)
        if module_path is None:
            await self.bot.say('{} not loaded.'.format(name))
            return

        self.bot.unload_extension(module_path)
        self.bot.load_extension(module_path)

        await self.bot.say('\N{OK HAND SIGN}')

    @cogs_group.command(name='unload')
    @checks.is_owner()
    async def cogs_unload(self, *, name: str):
        """Unloads a cog."""
        module_path = self._resolve_module_name(name)
        if module_path is None:
            await self.bot.say('{} not loaded.'.format(name))
            return

        self.bot.unload_extension(module_path)
        await self.bot.say('\N{OK HAND SIGN}')

    @commands.group(pass_context=True, invoke_without_command=True)
    @checks.is_owner()
    async def debug(self, ctx, *, code: str):
        """Yet another eval command."""
        # Cleanup the code blocks
        if code.startswith('```') and code.endswith('```'):
            code = '\n'.join(code.splitlines()[1:-1])
        code = code.strip('` ')

        # Wrap the code inside a coroutine to allow asyncronous keywords
        code = 'async def painting_of_a_happy_little_tree(ctx):\n' + textwrap.indent(code, '    ')
        stdout = io.StringIO()

        try:
            # First exec to create the coroutine
            exec(code, self.debug_env)
            coro = self.debug_env.pop('painting_of_a_happy_little_tree')(ctx)
        except SyntaxError as e:
            content = '{0.text}{1:>{0.offset}}\n{2}: {0.msg}'.format(e, '^', type(e).__name__)
        else:
            # Save a reference to the coro's frame before executing it
            coro_frame = coro.cr_frame
            try:
                with redirect_stdout(stdout):
                    result = await coro
            except:
                content = '{}{}'.format(stdout.getvalue(), traceback.format_exc())
            else:
                # Execution succeeded, save the return value and build the output content
                self.debug_env['_last'] = result
                content = stdout.getvalue()
                if result is not None:
                    content += str(result)

                # Re-schedule the cleanup
                if self.cleanup_task:
                    self.cleanup_task.cancel()
                self.cleanup_task = ctx.bot.loop.call_later(180, self.clear_debug_env)
            finally:
                # Update the execution environment with the coroutine's locals
                self.debug_env.update(coro_frame.f_locals)
                del coro_frame

        # Send the feedback
        if content:
            await self.bot.say_block(content)
        else:
            await self.bot.add_reaction(ctx.message, '\N{WHITE HEAVY CHECK MARK}')

    def clear_debug_env(self):
        if self.cleanup_task:
            self.cleanup_task.cancel()
            self.cleanup_task = None
        self.debug_env.clear()
        self.debug_env.update(globals())

    @debug.command()
    @checks.is_owner()
    async def clear(self):
        """Clears the execution environment."""
        self.clear_debug_env()

    @commands.command()
    @checks.is_owner()
    async def update(self):
        """Updates the bot."""
        embed = discord.Embed(colour=0x738bd7, description='Updating bot...')
        message = await self.bot.say(embed=embed)

        process = await asyncio.create_subprocess_exec('git', 'pull', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if stdout:
            embed.add_field(name='stdout', value="```\n {} \n```".format(stdout.decode()))
        if stderr:
            embed.add_field(name='stderr', value="```\n {} \n```".format(stderr.decode()))

        if stdout or stderr:
            await self.bot.edit_message(message, embed=embed)
