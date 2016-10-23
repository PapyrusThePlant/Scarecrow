import logging
import multiprocessing
import sys

import paths
from bot import Bot


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
            if '--loglevel' == arg:
                cls.log_level = logging.getLevelName(iter.__next__().upper())
            elif '--logs' == arg or '-l' == arg:
                log_mode = iter.__next__()
                if log_mode == 'cons':
                    cls.log_handler = logging.StreamHandler()
                elif log_mode == 'file':
                    cls.log_handler = logging.FileHandler(filename=paths.SCARECROW_LOG, encoding='utf-8', mode='w')


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
        bot = Bot()

        # Start it
        try:
            log.info('Running bot...')
            bot.run()
        except Exception as e:
            log.exception('Recovering from exception : {}'.format(e))

        if bot.do_shutdown:
            if bot.do_restart:
                exit(10)
            else:
                exit(0)

        # Clear state
        log.info('Deleting the bot.')
        del bot


if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    main()
