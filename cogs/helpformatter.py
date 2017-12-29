import inspect
import itertools

import discord
import discord.ext.commands as commands
from discord.ext.commands.core import GroupMixin, Command


def setup(bot):
    bot.formatter = HelpFormatter()


def teardown(bot):
    bot.formatter = commands.HelpFormatter()


class HelpFormatter(commands.HelpFormatter):
    """Deviation from the default formatter to list subcommands with extra indentation and formatting."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_indent = '   '

    async def _add_subcommands_to_page(self, max_width, commands, base_indent=None):
        """Adds commands/subcommands and their description to the paginator."""
        async def predicate(name, cmd):
            try:
                return name not in cmd.aliases and await cmd.can_run(self.context)
            except:
                return False

        to_display = [(name, cmd) for name, cmd in commands if await predicate(name, cmd)]
        iterator = iter(sorted(to_display))
        for name, command in iterator:
            # Ugly indent shenanigans
            if base_indent:
                if iterator.__length_hint__() > 0:
                    indent = f'{base_indent}\u251c\u2500 '
                else:
                    indent = f'{base_indent}\u2514\u2500 '
            else:
                indent = self.base_indent

            entry = f'{indent}{name:<{max_width - len(indent)}} {command.short_doc}'
            shortened = self.shorten(entry)
            self._paginator.add_line(shortened)

            if isinstance(command, GroupMixin):
                indent = indent.replace('\u251c\u2500', '\u2502 ').replace('\u2514\u2500', '  ')  # wew wth
                await self._add_subcommands_to_page(max_width, command.all_commands.items(), indent)

    def _get_max_width(self, command, depth=1):
        """Tricks and ponies to get the appropriate max_width."""
        command_length = len(command.name) + depth * len(self.base_indent)
        if isinstance(command, GroupMixin):
            return max([self._get_max_width(c, depth + 1) for c in command.commands] + [command_length])
        else:
            return command_length

    @property
    def max_name_size(self):
        """Returns the size of the longest element found in the commands and their subcommands.
        Takes the indent for subcommands into accounts for the calculation"""
        try:
            command = self.command if not self.is_cog() else self.context.bot
            if command.commands:
                return max([self._get_max_width(c) if self.show_hidden or not c.hidden else 0 for c in command.commands])
            return 0
        except AttributeError:
            return len(self.command.name)

    async def format(self):
        """Handles the actual behaviour involved with formatting.

        To change the behaviour, this method should be overridden.

        Returns
        --------
        list
            A paginated output of the help command.
        """
        self._paginator = discord.ext.commands.Paginator()

        # we need a padding of ~80 or so

        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)

        if description:
            # <description> portion
            self._paginator.add_line(description, empty=True)

        if isinstance(self.command, Command):
            # <signature portion>
            signature = self.get_command_signature()
            self._paginator.add_line(signature, empty=True)

            # <long doc> section
            if self.command.help:
                self._paginator.add_line(self.command.help, empty=True)

            # end it here if it's just a regular command
            if not self.has_subcommands():
                self._paginator.close_page()
                return self._paginator.pages

        max_width = self.max_name_size

        def category(tup):
            cog = tup[1].cog_name
            # we insert the zero width space there to give it approximate
            # last place sorting position.
            return cog + ':' if cog is not None else '\u200bNo Category:'

        filtered = await self.filter_command_list()
        if self.is_bot():
            data = sorted(filtered, key=category)
            for category, commands in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                commands = sorted(commands)
                if len(commands) > 0:
                    self._paginator.add_line(category)

                await self._add_subcommands_to_page(max_width, commands)
        else:
            filtered = sorted(filtered)
            if filtered:
                self._paginator.add_line('Commands:')
                await self._add_subcommands_to_page(max_width, filtered)

        # add the ending note
        self._paginator.add_line()
        ending_note = self.get_ending_note()
        self._paginator.add_line(ending_note)
        return self._paginator.pages
