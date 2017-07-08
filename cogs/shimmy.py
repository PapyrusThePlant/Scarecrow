import random

import discord
import discord.ext.commands as commands


SHIMMY_USER_ID = 140526957686161408
SHIMMY_GUILD_ID = 140880261360517120
NSFW_ROLE_ID = 261189004681019392


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


def setup(bot):
    bot.add_cog(Shimmy())


class Shimmy:
    """Exclusivities to Shimmy's discord server."""
    def __init__(self):
        self.nsfw_role = None

    def __local_check(self, ctx):
        return ctx.guild is not None and ctx.guild.id == SHIMMY_GUILD_ID

    @commands.command()
    @commands.guild_only()
    async def nsfw(self, ctx):
        """Tries to add the NSFW role to a member."""
        if self.nsfw_role is None:
            self.nsfw_role = discord.utils.get(ctx.guild.roles, id=NSFW_ROLE_ID)

        await ctx.author.add_roles(self.nsfw_role)
        await ctx.message.add_reaction('\N{WHITE HEAVY CHECK MARK}')

    @commands.command()
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def stream(self, ctx, *, description=None):
        shimmy = ctx.guild.get_member(SHIMMY_USER_ID)
        embed = discord.Embed(title='Click here to join the fun !', url='https://twitch.tv/shimmyx')
        embed.set_author(name=shimmy.display_name, icon_url=shimmy.avatar_url)
        embed.description = description or "Guess who's streaming? It's ~~slothsenpai~~ shimmysenpai ! Kyaa\~\~"

        await ctx.send(content='@here', embed=embed)
        await ctx.message.delete()

    @commands.command()
    async def ball(self, ctx, *, question):
        """Scarecrow's 8-Ball reaches into the future, to find the answers to your questions.

        It knows what will be, and is willing to share this with you. Just send a question that can be answered by
        "Yes" or "No", then let Scarecrow's 8-Ball show you the way !
        """
        await ctx.send(random.choice(eight_ball_responses))
