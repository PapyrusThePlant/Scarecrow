import asyncio
import inspect
import io
import os
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
        self.repl_sessions = set()

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
        """Cogs management commands.

        If no subcommand is invoked, lists loaded cogs.
        """
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

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def debug(self, ctx, *, code: str):
        """Yet another eval command."""
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

    @commands.command(pass_context=True, hidden=True)
    @checks.is_owner()
    async def repl(self, ctx):
        """Yet another Read-Eval-Print-Loop."""
        msg = ctx.message

        variables = {
            'ctx': ctx,
            'bot': self.bot,
            'message': msg,
            'server': msg.server,
            'channel': msg.channel,
            'author': msg.author,
            'last': None,
        }

        if msg.channel.id in self.repl_sessions:
            await self.bot.say('Already running a REPL session in this channel. Exit it with `quit`.')
            return

        self.repl_sessions.add(msg.channel.id)
        await self.bot.say('Enter code to execute or evaluate. `exit()` or `quit` to exit.')
        while True:
            response = await self.bot.wait_for_message(author=msg.author, channel=msg.channel,
                                                       check=lambda m: m.content.startswith('`'))

            content = response.content
            if content.startswith('```') and content.endswith('```'):
                cleaned = '\n'.join(content.split('\n')[1:-1])
            else:
                cleaned = content.strip('` \n')

            if cleaned in ('quit', 'exit', 'exit()'):
                await self.bot.say('Exiting.')
                self.repl_sessions.remove(msg.channel.id)
                return

            executor = exec
            if cleaned.count('\n') == 0:
                # single statement, potentially 'eval'
                try:
                    code = compile(cleaned, '<repl session>', 'eval')
                except SyntaxError:
                    pass
                else:
                    executor = eval

            if executor is exec:
                try:
                    code = compile(cleaned, '<repl session>', 'exec')
                except SyntaxError as e:
                    error = '```py\n{0.text}{1:>{0.offset}}\n{2}: {0}```'.format(e, '^', type(e).__name__)
                    await self.bot.say(error)
                    continue

            variables['message'] = response

            fmt = None
            stdout = io.StringIO()

            try:
                with redirect_stdout(stdout):
                    result = executor(code, variables)
                    if inspect.isawaitable(result):
                        result = await result
            except Exception as e:
                value = stdout.getvalue()
                fmt = '```py\n{}{}\n```'.format(value, traceback.format_exc())
            else:
                value = stdout.getvalue()
                if result is not None:
                    fmt = '```py\n{}{}\n```'.format(value, result)
                    variables['last'] = result
                elif value:
                    fmt = '```py\n{}\n```'.format(value)

            try:
                if fmt is not None:
                    if len(fmt) > 2000:
                        await self.bot.send_message(msg.channel, 'Content too big to be printed.')
                    else:
                        await self.bot.send_message(msg.channel, fmt)
            except discord.Forbidden:
                pass
            except discord.HTTPException as e:
                await self.bot.send_message(msg.channel, 'Unexpected error: `{}`'.format(e))

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
