import asyncio
import logging
import os
import re
import time
import traceback

import discord
import discord.ext.commands as commands

import paths
from cogs.util import config

log = logging.getLogger(__name__)


class BotConfig(config.ConfigElement):
    def __init__(self, token, description, **kwargs):
        self.description = description
        self.token = token
        self.status = kwargs.get('status', None)
        for k, v in kwargs.items():
            setattr(self, k, v)


class Bot(commands.Bot):
    def __init__(self, conf_path=paths.BOT_CONFIG, debug_instance=False):
        self.app_info = None
        self.owner = None
        self.do_restart = False
        self.start_time = time.time()
        self.conf = config.Config(conf_path, encoding='utf-8')
        self.debug_instance = debug_instance

        # Init the framework and load extensions
        super().__init__(description=self.conf.description,
                         command_prefix=commands.when_mentioned_or('€'),
                         help_attrs={'hidden': True})
        self.load_extensions(paths.COGS_DIR)

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
                    log.warning(f'Failed to load extension {extension}\n{type(e)}: {e}')

    def unload_extensions(self):
        # Unload every cog
        for extension in self.extensions.copy().keys():
            self.unload_extension(extension)

    async def on_command_error(self, ctx, error):
        # Pass if we marked the error as handled
        if getattr(error, 'handled', False):
            return

        if isinstance(error, (commands.UserInputError, commands.NoPrivateMessage, commands.DisabledCommand)):
            message = str(error)
        elif isinstance(error, commands.CommandInvokeError) and not isinstance(error.original, discord.Forbidden):
            tb = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
            log.error(f'Ignoring exception in command {ctx.command} : {tb}')
            message = 'An unexpected error has occurred and has been logged.'
        else:
            return
        
        try:
            await ctx.send(message)
        except discord.Forbidden:
            pass

    async def on_error(self, event_method, *args, **kwargs):
        # Skip if a cog defines this event
        if self.extra_events.get('on_error', None):
            return

        tb = ''.join(traceback.format_exc())
        content = f'Ignoring exception in {event_method} : {tb}'
        log.error(content)

    async def on_connect(self):
        self.app_info = await self.application_info()
        self.owner = self.app_info.owner
        log.info('Connected to Discord as {0.name} (id: {0.id})'.format(self.user))
        if self.conf.status:
            await self.change_presence(game=discord.Game(name=self.conf.status))

    async def on_ready(self):
        log.info("Guild streaming complete. We'ready.")

    async def on_message(self, message):
        # Ignore bot messages (that includes our own)
        if message.author.bot:
            return

        # if message.content.startswith ... :3
        await self.process_commands(message)

    async def get_message(self, channel, message_id):
        # Look into the cache first
        message = self._connection._get_message(message_id)
        if message is not None:
            return message

        # Avoid get_message as its rate limit is terrible
        try:
            message = await channel.history(limit=1, before=discord.Object(id=message_id + 1)).next()

            if message.id != message_id:
                return None

            self._connection._messages.append(message)
            return message
        except Exception:
            return None

    def shutdown(self):
        self.do_restart = False
        # Log out of Discord
        asyncio.ensure_future(self.logout(), loop=self.loop)

    def restart(self):
        self.do_restart = True
        # Log out of Discord
        asyncio.ensure_future(self.logout(), loop=self.loop)

    def run(self):
        try:
            super().run(self.conf.token)
        finally:
            self.unload_extensions()
