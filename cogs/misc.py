import random

import discord
import discord.ext.commands as commands

import paths
from .util import agarify, utils


def setup(bot):
    bot.add_cog(Misc(bot))


class Misc:
    """Miscellaneous commands."""
    def __init__(self, bot):
        self.bot = bot

    @commands.group(invoke_without_command=True)
    async def agarify(self, *, content):
        """Agarifies a string."""
        await self.bot.say(agarify.agarify(content))

    @agarify.command()
    async def user(self, *, user: discord.Member=None):
        """Agarifies a user's name."""
        await self.bot.say(agarify.agarify(user.display_name, True))

    @commands.command(aliases=['meow'])
    async def cat(self):
        """Meow !"""
        providers = [
            ('http://random.cat/meow', lambda d: d['file']),
            ('http://edgecats.net/random', lambda d: d)
        ]
        provider = random.choice(providers)
        url = provider[0]
        loader = provider[1]

        data = await utils.fetch_page(url, timeout=5)
        if data is None:
            content = 'Timed out on {} .'.format(url)
        else:
            content = loader(data)

        await self.bot.say(content)

    @commands.command()
    async def insult(self):
        """Poke the bear."""
        await self.bot.say(utils.random_line(paths.INSULTS))

    @commands.command()
    async def weebnames(self, wanted_gender=None):
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

            content += '[{}] {} {}\n'.format(gender, name, '({})'.format(remark) if remark else '')

        await self.bot.say_block(content)
