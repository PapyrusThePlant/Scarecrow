import asyncio
import datetime
import re

import discord
import discord.ext.commands as commands

import paths
from .util import config, utils


def setup(bot):
    bot.add_cog(Polls(bot))


class Polls:
    """Polls commands"""
    def __init__(self, bot):
        self.bot = bot
        self.keycaps_emojis = [f'{i}\u20e3' for i in range(1, 10)]
        self.keycaps_emojis.append('\N{KEYCAP TEN}')

    @commands.command(name='instantpoll', aliases=['ip'])
    async def instant_poll(self, ctx, title, *options):
        """Creates a poll.

        There can be at most 10 options."""
        if len(options) > 10:
            raise commands.BadArgument('Too many options (max 10).')

        poll = discord.Embed(title=title, colour=0x738bd7)
        poll.description = '\n'.join(f'{self.keycaps_emojis[i]} {o}' for i, o in enumerate(options))
        poll.set_author(name=f'{ctx.message.author.display_name} ({ctx.message.author})', icon_url=ctx.message.author.avatar_url)
        poll.set_footer(text='Vote using reactions !')

        message = await ctx.send(embed=poll)
        for i in range(len(options)):
            await message.add_reaction(self.keycaps_emojis[i])

    @commands.command()
    async def poll(self, ctx):
        """Interactively create a poll.

        This is a more user friendly version of the instantpoll command.
        """
        message = ctx.message
        to_delete = [message]

        def check(msg):
            return msg.channel == message.channel and msg.author == message.author

        # Start with the poll's title
        to_delete.append(await ctx.send("Yay let's make a poll !\nWhat will its title be?"))
        title = await ctx.bot.wait_for('message', check=check, timeout=60)
        if not title:
            raise commands.UserInputError(f'{message.author.mention} You took too long, aborting poll creation.')
        to_delete.append(title)

        # Loop and register the poll's options until the user says we're done
        to_delete.append(await ctx.send('Ok ! Now tell me a maximum of 10 options to choose from, in order.'))
        options = []
        while True:
            to_delete.append(await ctx.send(f"What will be entry #{len(options) + 1}? (type `No more options` when you're done)"))
            entry = await ctx.bot.wait_for('message', check=check, timeout=60)
            if not entry:
                raise commands.UserInputError('{message.author.mention} You took too long, aborting poll creation.')
            to_delete.append(entry)

            if entry.content.lower() == 'no more options':
                break

            options.append(entry.content)

        # Create the poll
        await ctx.invoke(self.instant_poll, title.content, *options)

        # Cleanup
        try:
            await ctx.channel.delete_messages(to_delete, reason='Poll command cleanup.')
        except:
            pass
