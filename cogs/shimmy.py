import random

import discord
import discord.ext.commands as commands


SHIMMY_USER_ID = 140526957686161408
SHIMMY_GUILD_ID = 140880261360517120
NSFW_ROLE_ID = 261189004681019392
LOG_CHANNEL_ID = 373829704345452546

requestable_roles = {
    'Animal Crossing': 373406099098828800,
    'Battle Royale': 374318563374399488,
    'Battlerite': 392048585472213012,
    'Destiny 2': 374102233513590794,
    'nsfw': 261189004681019392
}

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
    bot.add_cog(Shimmy(bot))


class Shimmy(commands.Cog):
    """Exclusivities to Shimmy's discord server."""
    def __init__(self, bot):
        self.bot = bot
        self.nsfw_role = None
        self.log_channel = None

    def cog_check(self, ctx):
        return ctx.guild is not None and ctx.guild.id == SHIMMY_GUILD_ID

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if member.guild is None or member.guild.id != SHIMMY_GUILD_ID:
            return
        if self.log_channel is None:
            self.log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        await self.log_channel.send(f'{str(member)} (id {member.id}) joined.')

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        if member.guild is None or member.guild.id != SHIMMY_GUILD_ID:
            return
        if self.log_channel is None:
            self.log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        await self.log_channel.send(f'{str(member)} (id {member.id}) left or got removed.')

    @commands.Cog.listener()
    async def on_member_ban(self, guild, member):
        if guild is None or guild.id != SHIMMY_GUILD_ID:
            return
        if self.log_channel is None:
            self.log_channel = self.bot.get_channel(LOG_CHANNEL_ID)
        await self.log_channel.send(f'{str(member)} (id {member.id}) got banned.')

    @commands.command()
    @commands.guild_only()
    async def role(self, ctx, *, role_name):
        """Tries to add the wanted role to a member. Only game roles and NSFW can be requested with that command."""
        role = discord.utils.get(ctx.guild.roles, name=role_name)
        if role_name not in requestable_roles or role is None:
            raise commands.BadArgument(f'Cannot request role "{role_name}".')

        if role in ctx.author.roles:
            await ctx.author.remove_roles(role)
        else:
            await ctx.author.add_roles(role)
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
