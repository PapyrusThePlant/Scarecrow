import discord.ext.commands.formatter as formatter
from discord.ext.commands.core import GroupMixin


def setup(bot):
    bot.formatter = HelpFormatter()


class HelpFormatter(formatter.HelpFormatter):
    """Deviation from the default formatter to list subcommands with extra indentation and formatting."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_indent = '   '

    def _add_subcommands_to_page(self, max_width, commands, base_indent=None):
        """Adds commands/subcommands and their description to the paginator."""
        iterator = iter(sorted(commands))
        for name, command in iterator:
            if name in command.aliases:
                # skip aliases
                continue

            # Ugly indent shenanigans
            if base_indent:
                if iterator.__length_hint__() > 0:
                    indent = base_indent + '\u251c\u2500 '
                else:
                    indent = base_indent + '\u2514\u2500 '
            else:
                indent = self.base_indent

            entry = '{0}{1:<{width}} {2}'.format(indent, name, command.short_doc, width=max_width - len(indent))
            shortened = self.shorten(entry)
            self._paginator.add_line(shortened)

            if isinstance(command, GroupMixin):
                subcommands = [(n, c) for n, c in command.commands.items()]
                indent = indent.replace('\u251c\u2500', '\u2502 ').replace('\u2514\u2500', '  ')  # wew wth
                self._add_subcommands_to_page(max_width, subcommands, indent)

    def _get_max_width(self, command, depth=1):
        """Tricks and ponies to get the appropriate max_width."""
        if not isinstance(command, GroupMixin):
            return len(command.name) + depth * len(self.base_indent)

        return max([self._get_max_width(c, depth + 1) for c in command.commands.values()])

    @property
    def max_name_size(self):
        """Returns the size of the longest element found in the commands and their subcommands.
        Takes the indent for subcommands into accounts for the calculation"""
        try:
            command = self.command if not self.is_cog() else self.context.bot
            if command.commands:
                return max(map(lambda c: self._get_max_width(c) if self.show_hidden or not c.hidden else 0, command.commands.values()))
            return 0
        except AttributeError:
            return len(self.command.name)
