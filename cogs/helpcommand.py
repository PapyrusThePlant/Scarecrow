import discord
import discord.ext.commands


def setup(bot):
    bot.help_command = TreeHelpCommand()


def teardown(bot):
    bot.help_command = discord.ext.commands.DefaultHelpCommand()


class TreeHelpCommand(discord.ext.commands.DefaultHelpCommand):
    """Deviation from the default help command to list subcommands with extra indentation and formatting."""
    def __init__(self, **kwargs):
        super().__init__(indent=min(3, kwargs.pop('indent', 3)), **kwargs)

    def get_max_size(self, commands, depth=0):
        """Returns the largest name length of the specified command list, including their subcommands."""
        as_lengths = set()
        for command in commands:
            as_lengths.add(discord.utils._string_width(command.name) + depth)
            if isinstance(command, discord.ext.commands.Group):
                as_lengths.add(self.get_max_size(command.commands, depth + self.indent))

        return max(as_lengths, default=0)

    def add_indented_commands(self, commands, *, heading, max_size=None, indent=0, tree_base=''):
        """Indents a list of commands and their subcommands as a tree view."""
        if not commands:
            return

        if indent == 0:
            indent = self.indent

        if heading is not None:
            self.paginator.add_line(heading)
        max_size = max_size or self.get_max_size(commands)

        commands = sorted(list(commands), key=lambda c: c.name)
        get_width = discord.utils._string_width
        for command in commands:
            last_command = command == commands[-1]
            base_indent = self.indent * ' '
            if indent > self.indent:
                tree_core = '└' if last_command else '├'
                tree_indent = f'{tree_base}{tree_core}' + (self.indent - 2) * '─' + ' '
            else:
                tree_indent = ''
            name = command.name
            width = max_size - (get_width(name) - len(name))
            entry = f'{base_indent}{tree_indent + name:<{width}}  {command.short_doc}'
            self.paginator.add_line(self.shorten_text(entry))
            if isinstance(command, discord.ext.commands.Group):
                next_tree_base = tree_base + f'{"│":<{self.indent - 1}}' if not last_command and indent > self.indent else tree_base
                self.add_indented_commands(command.commands, heading=None, max_size=max_size, indent=indent + self.indent, tree_base=next_tree_base)
