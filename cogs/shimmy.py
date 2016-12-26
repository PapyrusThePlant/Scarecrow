import discord
import discord.ext.commands as commands

from .util import checks

SHIMMY_SERVER_ID = '140880261360517120'
NSFW_ROLE_ID = '261189004681019392'


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
