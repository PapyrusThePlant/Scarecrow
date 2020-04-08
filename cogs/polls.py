import asyncio

import discord
import discord.ext.commands as commands


def setup(bot):
    bot.add_cog(Polls(bot))


class Polls(commands.Cog):
    """Polls commands"""
    def __init__(self, bot):
        self.bot = bot
        self.keycaps_emojis = [f'{i}\u20e3' for i in range(1, 10)]
        self.keycaps_emojis.append('\N{KEYCAP TEN}')

    @commands.command(name='instantpoll', aliases=['ip'])
    @commands.guild_only()
    async def instant_poll(self, ctx, title, *options):
        """Creates a poll.

        To have a title and/or options with multiple words, surround
        them with double quotes. e.g:
            `@Scarecrow#8745 ip "Is this a good feature?" yes "I'm not sure" no`

        Note that there can be at most 10 options to choose from.
        """
        if len(options) > 10:
            raise commands.BadArgument('Too many options (max 10).')

        poll = discord.Embed(title=title, colour=discord.Colour.blurple())
        poll.description = '\n'.join(f'{self.keycaps_emojis[i]} {o}' for i, o in enumerate(options))
        poll.set_author(name=f'{ctx.author.display_name} ({ctx.author})', icon_url=ctx.author.avatar_url)
        poll.set_footer(text='Vote using reactions !')

        message = await ctx.send(embed=poll)
        for i in range(len(options)):
            await message.add_reaction(self.keycaps_emojis[i])

    @commands.command()
    @commands.guild_only()
    async def poll(self, ctx):
        """Interactively create a poll.

        This is a more user friendly version of the `instantpoll` command.
        """
        to_delete = [ctx.message]

        def check(msg):
            return msg.channel == ctx.channel and msg.author == ctx.author

        # Start with the poll's title
        to_delete.append(await ctx.send("Yay let's make a poll !\nWhat will its title be?"))
        try:
            title = await ctx.bot.wait_for('message', check=check, timeout=60)
        except asyncio.TimeoutError:
            raise commands.UserInputError(f'{ctx.author.mention} You took too long, aborting poll creation.')
        to_delete.append(title)

        # Loop and register the poll's options until the user says we're done
        to_delete.append(await ctx.send('Ok ! Now tell me a maximum of 10 options to choose from, in order.'))
        options = []
        while True:
            to_delete.append(await ctx.send(f"What will be entry #{len(options) + 1}? (type `No more options` when you're done)"))
            try:
                entry = await ctx.bot.wait_for('message', check=check, timeout=60)
            except asyncio.TimeoutError:
                raise commands.UserInputError(f'{ctx.author.mention} You took too long, aborting poll creation.')
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
