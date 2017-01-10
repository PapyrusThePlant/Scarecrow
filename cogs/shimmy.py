import random

import discord
import discord.ext.commands as commands

from .util import checks

SHIMMY_SERVER_ID = '140880261360517120'
NSFW_ROLE_ID = '261189004681019392'


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
    # Non cmmmittal
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


def setup(bot):
    bot.add_cog(Shimmy(bot))


class Shimmy:
    """Commands exclusive to Shimmy's discord server."""
    def __init__(self, bot):
        self.bot = bot

    @commands.command(pass_context=True)
    @checks.in_server(SHIMMY_SERVER_ID)
    async def nsfw(self, ctx):
        """Tries to add the NSFW role to a member."""
        await self.bot.add_roles(ctx.message.author, discord.Object(id=NSFW_ROLE_ID))
        await self.bot.say('\N{WHITE HEAVY CHECK MARK} Access granted.', delete_after=3)
        await self.bot.delete_message(ctx.message)

    @commands.command(aliases=['eight', '8'])
    @checks.in_server(SHIMMY_SERVER_ID)
    async def ball(self, *, question):
        await self.bot.say(random.choice(eight_ball_responses))
