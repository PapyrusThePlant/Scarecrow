import importlib
import logging
import multiprocessing
import sys
import types

import paths
import scarecrow


log = logging.getLogger(__name__)


class Settings:
    """Startup script's settings"""
    requirements = [
        'https://github.com/PapyrusThePlant/discord.py',
        'https://github.com/PapyrusThePlant/Scarecrow'
    ]

    log_level = logging.INFO
    log_handler = logging.NullHandler()

    @classmethod
    def parse_arguments(cls, args):
        iter = args[1:].__iter__()
        for arg in iter:
            if '--update' == arg or '-u' == arg:
                # TODO : update the requirements
                exit()

            if '--help' == arg or '-h' == arg:
                # TODO : print help
                pass

            if '--loglevel' == arg:
                cls.log_level = logging.getLevelName(iter.__next__().upper())

            if '--logs' == arg or '-l' == arg:
                log_mode = iter.__next__()
                if log_mode == 'cons':
                    cls.log_handler = logging.StreamHandler()
                elif log_mode == 'file':
                    cls.log_handler = logging.FileHandler(filename=paths.SCARECROW_LOG, encoding='utf-8', mode='w')


class Reloader:
    """
    - Aww no it's bad pls don't do this :x
    - But it works senpai !
    - NO IT DOES NOT, FUCK YOUR IDEA, IT'S BAD
    - D:
    """
    @classmethod
    def _reload(cls, module, _reloading, _reloaded):
        if module.__name__ in _reloading or module.__name__ in _reloaded:
            return

        _reloading.append(module.__name__)
        post_reload = []

        # Check if we need to reload any other related module
        for element in module.__dict__.values():
            if isinstance(element, type(module)):
                if module.__name__.startswith(element.__name__):
                    # Post reload only parent modules
                    post_reload.append(element)
                elif element.__name__.startswith(module.__name__):
                    # Reload only child modules
                    cls._reload(element, _reloading, _reloaded)

        importlib.reload(module)
        _reloaded.append(module.__name__)
        _reloading.remove(module.__name__)

        for module in post_reload:
            cls._reload(module, _reloading, _reloaded)

    @classmethod
    def reload(cls, module):
        _reloading = []
        _reloaded = []

        if isinstance(module, str):
            module = sys.modules[module]

        if not isinstance(module, types.ModuleType):
            raise ValueError("Expected '{}' or '{}' but got '{}'".format(str, types.ModuleType, type(module)))

        cls._reload(module, _reloading, _reloaded)
        # TODO : loop over sys.modules and reload modules which imported the module we just reloaded ?


def main():
    Settings.parse_arguments(sys.argv)

    # Setup the logging
    rlog = logging.getLogger()
    rlog.setLevel(Settings.log_level)
    Settings.log_handler.setFormatter(logging.Formatter('{asctime} {levelname} {name} {message}', style='{'))
    rlog.addHandler(Settings.log_handler)

    log.info('Started with Python {0.major}.{0.minor}.{0.micro}'.format(sys.version_info))

    # ERMAHGERD ! MAH FRAVRIT LERP !
    while True:
        # Create the bot, let it crash on exceptions
        log.info('Creating bot...')
        bot = scarecrow.Bot()

        # Start it
        try:
            log.info('Running bot...')
            bot.run()
        except Exception as e:
            log.exception('Recovering from exception : {}'.format(e))

        if not bot.do_restart:
            break

        if bot.do_reload:
            log.info('Reloading the bot.')
            Reloader.reload(bot.__module__)

        # Clear state
        log.info('Deleting the bot.')
        del bot

    exit()

if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    main()
