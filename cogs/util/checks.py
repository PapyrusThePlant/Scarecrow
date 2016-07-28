import discord.ext.commands as commands


def has_permissions(**perms):
    """Commands decorator adding a check which makes the command available if the permissions are satisfied."""
    def predicate(ctx):
        author = ctx.message.author
        if author == ctx.bot.owner or author == ctx.message.server.owner:
            return True

        resolved = ctx.message.channel.permissions_for(author)

        missing = []
        for key, has_perm in perms.items():
            if getattr(resolved, key, None) != has_perm:
                if has_perm:
                    missing.append(key.replace('_', ' '))
                else:
                    # Silently fail on unwanted permission
                    return False

        # Notify the missing permissions
        if missing:
            fmt = "Missing the following permissions to execute command '{}' : {}"
            content = fmt.format(ctx.command.name, missing)
            ctx.bot.loop.create_task(ctx.bot.say(content))
            return False

        return True

    return commands.check(predicate)


def has_roles(**roles):
    """Commands decorator adding a check which makes the command available if the roles are satisfied."""
    def predicate(ctx):
        author = ctx.message.author
        if author == ctx.bot.owner or author == ctx.message.server.owner:
            return True

        resolved = [r.name for r in author.roles]

        missing = []
        for role, has_role in roles.items():
            if has_role and role not in resolved:
                missing.append(role.replace('_', ' '))
            elif not has_role and role in resolved:
                # Silently fail on unwanted role
                return False

        # Notify the missing roles
        if missing:
            fmt = "Missing the following roles to execute command '{}' : {}"
            content = fmt.format(ctx.command.name, missing)
            ctx.bot.loop.create_task(ctx.bot.say(content))
            return False

        return True
    return commands.check(predicate)


def is_server_owner():
    """Commands decorator adding a check which makes the command available to the server owner only."""
    def predicate(ctx):
        author = ctx.message.author
        return author == ctx.bot.owner or author == ctx.server.owner

    return commands.check(predicate)


def is_owner():
    """Commands decorator adding a check which makes the command available to the bot owner only."""
    def predicate(ctx):
        return ctx.message.author == ctx.bot.owner

    return commands.check(predicate)
