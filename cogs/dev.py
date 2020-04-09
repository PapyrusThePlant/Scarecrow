import asyncio
import gc
import inspect
import io
import textwrap
import traceback
from contextlib import redirect_stdout
from collections import Counter

import discord
from discord.ext import commands
import psutil

import paths
from cogs.util import utils


def setup(bot):
    bot.add_cog(Dev(bot))


class Dev(commands.Cog):
    """Nope, not for you."""
    def __init__(self, bot):
        self.bot = bot

    def cog_check(self, ctx):
        # Owner commands only
        return ctx.author.id == ctx.bot.owner.id

    @commands.group(name='cogs', invoke_without_command=True)
    async def cogs_group(self, ctx):
        """Lists currently loaded cogs."""
        entries = []

        for name in sorted(ctx.bot.cogs):
            cog = ctx.bot.cogs[name]

            # Get the first line of the doc
            help_doc = inspect.getdoc(cog)
            help_doc = '' if help_doc is None else help_doc.split('\n', 1)[0]
            if isinstance(help_doc, bytes):
                help_doc = help_doc.decode('utf-8')

            entries.append((name, help_doc))

        content = utils.indented_entry_to_str(entries)
        await ctx.send(utils.format_block(content))

    @cogs_group.command(name='load')
    async def cogs_load(self, ctx, *, name: str):
        """Loads a cog from name."""
        module_path = f'{paths.COGS_DIR_NAME}.{name.lower()}'
        if module_path in ctx.bot.extensions:
            raise commands.BadArgument(f'"{name}" already loaded.')

        try:
            ctx.bot.load_extension(module_path)
        except ImportError as e:
            raise commands.BadArgument(f'Could not find module "{name}".') from e

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @cogs_group.command(name='reload')
    async def cogs_reload(self, ctx, name: str):
        """Reloads a cog."""
        module_path = f'{paths.COGS_DIR_NAME}.{name.lower()}'
        if module_path not in ctx.bot.extensions:
            raise commands.BadArgument(f'"{name}" not loaded.')

        ctx.bot.unload_extension(module_path)
        ctx.bot.load_extension(module_path)

        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @cogs_group.command(name='unload')
    async def cogs_unload(self, ctx, *, name: str):
        """Unloads a cog."""
        module_path = f'{paths.COGS_DIR_NAME}.{name.lower()}'
        if module_path not in ctx.bot.extensions:
            raise commands.BadArgument(f'"{name}" not loaded.')

        ctx.bot.unload_extension(module_path)
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.group(invoke_without_command=True)
    async def debug(self, ctx, *, code: str):
        """Yet another eval command."""
        # Cleanup the code blocks
        if code.startswith('```') and code.endswith('```'):
            code = '\n'.join(code.splitlines()[1:-1])
        code = code.strip('` ')

        # Wrap the code inside a coroutine to allow asynchronous keywords
        code = f'async def painting_of_a_happy_little_tree(ctx):\n{textwrap.indent(code, "    ")}'
        stdout = io.StringIO()
        env = dict(globals())

        try:
            # First exec to create the coroutine
            exec(code, env)
            coro = env.pop('painting_of_a_happy_little_tree')(ctx)
        except SyntaxError as e:
            content = f'{e.text}{"^":>{e.offset}}\n{type(e).__name__}{e.msg}'
        else:
            try:
                with redirect_stdout(stdout):
                    result = await coro
            except:
                content = f'{stdout.getvalue()}{traceback.format_exc()}'
            else:
                # Execution succeeded, save the return value and build the output content
                content = stdout.getvalue()
                if result is not None:
                    content += str(result)

        # Send the feedback
        if content:
            if len(content) <= 1990:
                await ctx.send(utils.format_block(content, language='py'))
            else:
                paginator = commands.Paginator()
                for line in content.splitlines():
                    try:
                        paginator.add_line(line)
                    except RuntimeError as e:
                        await ctx.send(str(e))

                for page in paginator.pages:
                    await ctx.send(page)
        else:
            await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command()
    async def memory(self, ctx, n=10):
        """Memory info."""
        members = 0
        uniques = set()
        for member in ctx.bot.get_all_members():
            members += 1
            uniques.add(member.id)
        memory = f'{psutil.Process().memory_full_info().uss / 1048576:.2f} Mb'
        objects = Counter(type(o).__name__ for o in gc.get_objects())
        objects_str = utils.format_block(objects.most_common(n), language='py')

        await ctx.send(f'Guilds: {len(ctx.bot.guilds)}\nMembers: {members} ({len(uniques)} uniques)\nMemory: {memory}\nObjects: {objects_str}')

    @commands.command()
    async def update(self, ctx):
        """Updates the bot."""
        embed = discord.Embed(colour=discord.Colour.blurple(), description='Updating bot...')
        message = await ctx.send(embed=embed)

        process = await asyncio.create_subprocess_exec('git', 'pull', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await process.communicate()

        if stderr:
            embed.add_field(name='stderr', value=utils.format_block(stderr.decode()))
        if stdout:
            embed.add_field(name='stdout', value=utils.format_block(stdout.decode()))

        if stdout or stderr:
            await message.edit(embed=embed)
