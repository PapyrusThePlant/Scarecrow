import asyncio
import logging
import os
import re
import time
import traceback

import discord.ext.commands as commands

import paths
from cogs.util import config

log = logging.getLogger(__name__)


class BotConfig(config.ConfigElement):
    def __init__(self, token, description, **kwargs):
        self.description = description
        self.token = token
        self.commands_prefixes = kwargs.pop('commands_prefixes', ['mention'])


class Bot(commands.Bot):
    """Ooooooh ! Scary."""
    def __init__(self, conf_path=paths.SCARECROW_CONFIG):
        self.app_info = None
        self.owner = None
        self.do_restart = False
        self.start_time = time.time()
        self.conf = config.Config(conf_path, encoding='utf-8')

        prefixes = self.conf.commands_prefixes
        if 'mention' in prefixes:
            prefixes_cpy = prefixes.copy()
            prefixes_cpy.remove('mention')
            prefixes = commands.when_mentioned_or(*prefixes_cpy)
            del prefixes_cpy

        # Init the framework and load extensions
        super().__init__(description=self.conf.description, command_prefix=prefixes, help_attrs={'hidden': True})
        self.load_extensions(paths.COGS)

        # Accept restarts after everything has been initialised without issue
        self.do_restart = True

    def load_extensions(self, path):
        # Load all the cogs we find in the given path
        for entry in os.scandir(path):
            if entry.is_file():
                # Let's construct the module name from the file path
                tokens = re.findall('\w+', entry.path)
                if tokens[-1] != 'py':
                    continue
                del tokens[-1]
                extension = '.'.join(tokens)

                try:
                    self.load_extension(extension)
                except Exception as e:
                    log.warning('Failed to load extension {}\n{}: {}'.format(extension, type(e).__name__, e))

    def unload_extensions(self):
        # Unload every cog
        for extension in self.extensions.copy().keys():
            self.unload_extension(extension)

    async def on_command_error(self, exception, context):
        # Skip if a cog defines this event
        if self.extra_events.get('on_command_error', None):
            return

        # Skip if the command defines an error handler
        if hasattr(context.command, "on_error"):
            return

        # Skip check failures
        if isinstance(exception, commands.CheckFailure):
            return

        content = 'Ignoring exception in command {}:\n' \
                  '{}'.format(context.command,
                              ''.join(traceback.format_exception(type(exception), exception, exception.__traceback__)))
        log.error(content)

    async def on_error(self, event_method, *args, **kwargs):
        # Skip if a cog defines this event
        if self.extra_events.get('on_error', None):
            return

        content = 'Ignoring exception in {}:\n' \
                  '{}'.format(event_method, ''.join(traceback.format_exc()))
        log.error(content)

    async def on_ready(self):
        self.app_info = await self.application_info()
        self.owner = self.app_info.owner
        log.info('Logged in Discord as {0.name} (id: {0.id})'.format(self.user))

    async def on_message(self, message):
        # Ignore bot messages (that includes our own)
        if message.author.bot:
            return

        # if message.content.startswith ... :3
        await self.process_commands(message)

    def shutdown(self):
        self.do_restart = False
        # Log out of Discord
        asyncio.ensure_future(self.logout())

    def restart(self):
        self.do_restart = True
        # Log out of Discord
        asyncio.ensure_future(self.logout())

    def run(self):
        super().run(self.conf.token)
        self.unload_extensions()

    def say_block(self, content):
        content = '```\n{}\n```'.format(content)
        return self.say(content)
