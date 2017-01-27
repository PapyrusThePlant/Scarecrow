import discord.ext.commands as commands


def is_server_owner():
    """Commands decorator adding a check which makes the command available to the server owner only."""
    def predicate(ctx):
        return ctx.message.author in [ctx.bot.owner, ctx.message.server.owner]

    return commands.check(predicate)


def is_owner():
    """Commands decorator adding a check which makes the command available to the bot owner only."""
    def predicate(ctx):
        return ctx.message.author == ctx.bot.owner

    return commands.check(predicate)


def in_server(server_id):
    """Commands decorator adding a check which makes the command available from the given server only."""
    def predicate(ctx):
        server = ctx.message.server
        return server is not None and server.id == server_id

    return commands.check(predicate)