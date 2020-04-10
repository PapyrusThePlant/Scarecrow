import logging
import random

import dice
import discord
import discord.ext.commands as commands
import pyparsing  # requirement of the dice module

import paths
from cogs.util import agarify, utils

log = logging.getLogger(__name__)


def setup(bot):
    bot.add_cog(Misc(bot))


class Misc(commands.Cog):
    """No comment."""
    @commands.group(invoke_without_command=True)
    async def agarify(self, ctx, *, content):
        """Agarifies a string."""
        await ctx.send(agarify.agarify(content))

    @agarify.command()
    async def user(self, ctx, *, user: discord.Member):
        """Agarifies a user's name."""
        await ctx.send(agarify.agarify(user.display_name, True))

    @commands.command(name='8ball')
    async def ball(self, ctx, *, question):
        """Scarecrow's 8-Ball reaches into the future, to find the answers to your questions.

        It knows what will be, and is willing to share this with you. Just send a question that can be answered by
        "Yes" or "No", then let Scarecrow's 8-Ball show you the way !
        """
        eight_ball_responses = [
            # Positive
            "It is certain",
            "It is decidedly so",
            "Without a doubt",
            "Yes, definitely",
            "You may rely on it",
            "As I see it, yes",
            "Most likely",
            "Outlook good",
            "Yes",
            "Signs point to yes",
            # Non committal
            "Reply hazy try again",
            "Ask again later",
            "Better not tell you now",
            "Cannot predict now",
            "Concentrate and ask again",
            # Negative
            "Don't count on it",
            "My reply is no",
            "My sources say no",
            "Outlook not so good",
            "Very doubtful"
        ]
        await ctx.send(random.choice(eight_ball_responses))

    @commands.command(aliases=['meow'])
    async def cat(self, ctx):
        """Meow !"""
        providers = [
            ('http://aws.random.cat/meow', lambda d: d['file']),
            ('http://edgecats.net/random', lambda d: d),
            ('http://thecatapi.com/api/images/get?format=src', lambda d: d)
        ]
        url, loader = random.choice(providers)

        try:
            data = await utils.fetch_page(url, timeout=5)
        except utils.HTTPError as e:
            log.info(e)
            content = f'Error when querying {url} . This has been logged.'
        else:
            if data is None:
                content = f'Timed out on {url} .'
            else:
                content = loader(data)

        await ctx.send(content)

    @commands.command()
    async def insult(self, ctx):
        """Poke the bear."""
        await ctx.send(utils.random_line(paths.INSULTS))

    @commands.command()
    async def roll(self, ctx, *, expression):
        """Rolls a dice.

        The expression works like a simple equation parser with some extra operators.
        The following operators are listed in order of precedence.
        The dice ('d') operator takes an amount (A) and a number of sides (S), and returns a list of A random numbers between 1 and S. For example: 4d6 may return [6, 3, 2, 4].
        If A is not specified, it is assumed you want to roll a single die. d6 is equivalent to 1d6.
        Basic integer operations are available: 16 / 8 * 4 + 2 - 1 -> 9.
        A set of rolls can be turned into an integer with the total (t) operator. 6d1t will return 6 instead of [1, 1, 1, 1, 1, 1]. Applying integer operations to a list of rolls will total them automatically.
        A set of dice rolls can be sorted with the sort (s) operator. 4d6s will not change the return value, but the dice will be sorted from lowest to highest.
        The lowest or highest rolls can be selected with ^ and v. 6d6^3 will keep the highest 3 rolls, whereas 6d6v3 will select the lowest 3 rolls.
        """
        try:
            res = dice.roll(expression)
        except (pyparsing.ParseBaseException, dice.ParseException) as e:
            await ctx.send(e)
        else:
            if isinstance(res, list):
                embed = discord.Embed(title='Rolls', description=', '.join([str(r) for r in res]), colour=discord.Colour.blurple())
                embed.add_field(name='Total', value=sum(res))
                embed.add_field(name='Minimum', value=min(res))
                embed.add_field(name='Maximum', value=max(res))
                await ctx.send(embed=embed)
            else:
                await ctx.send(f'Result : {res}')

    @commands.command()
    async def weebnames(self, ctx, wanted_gender=None):
        """Looking for a name for your new waifu?

        A prefered gender can be specified between f(emale), m(ale), x(mixed).
        """
        content = ''
        for i in range(1, 10):
            # Get a random name satisfying the wanted gender and kick the '\n' out
            def predicate(line):
                return line[0] == wanted_gender
            line = utils.random_line(paths.WEEBNAMES, predicate if wanted_gender else None)
            gender, name, remark = line[:-1].split('|')
            content += f'[{gender}] {name} {f"({remark})" if remark else ""}\n'

        await ctx.send(utils.format_block(content))
