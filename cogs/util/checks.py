import discord.ext.commands as commands


def is_server_owner():
    """Commands decorator adding a check which makes the command available to the server owner only."""
    def predicate(ctx):
        return ctx.author.id == ctx.bot.owner.id or ctx.author.id == ctx.guild.owner.id

    return commands.check(predicate)


def is_owner():
    """Commands decorator adding a check which makes the command available to the bot owner only."""
    def predicate(ctx):
        return ctx.author.id == ctx.bot.owner.id

    return commands.check(predicate)


def in_guild(guild_id):
    """Commands decorator adding a check which makes the command available from the given server only."""
    def predicate(ctx):
        guild = ctx.guild
        return guild is not None and guild.id == guild_id

    return commands.check(predicate)
