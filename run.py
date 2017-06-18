import asyncio
import logging
import multiprocessing
import sys

import paths
from bot import Bot


class StreamToLogger:
    """Fake file-like stream object that redirects writes to a logger instance."""
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.buffer = []

    def write(self, buf):
        try:
            if buf[-1] == '\n':
                self.buffer.append(buf.rstrip())
                self.emit()
            else:
                self.buffer.append(buf)
        except IndexError: # When buf == ''
            pass

    def emit(self):
        self.logger.log(self.log_level, ''.join(part for part in self.buffer))
        self.buffer.clear()

    def flush(self):
        # Quality flush
        pass


if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    debug_instance = 'debug' in sys.argv

    # Setup the root logger
    rlog = logging.getLogger()
    rlog.setLevel(logging.DEBUG if debug_instance else logging.INFO)
    handler = logging.FileHandler(paths.BOT_LOG, encoding='utf-8')
    handler.setFormatter(logging.Formatter('{asctime}:{levelname}:{name}:{message}', style='{'))
    rlog.addHandler(handler)

    # Redirect stdout and stderr to the log file
    sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO)
    sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR)

    log = logging.getLogger(__name__)
    log.info('Started with Python {0.major}.{0.minor}.{0.micro}'.format(sys.version_info))

    # Try to use uvloop, and fallback to a ProactorEventLoop on windows to be able to use subprocesses
    # See https://docs.python.org/3/library/asyncio-subprocess.html#windows-event-loop
    try:
        import uvloop
    except ImportError:
        if sys.platform == 'win32':
            asyncio.set_event_loop(asyncio.ProactorEventLoop())
    else:
        asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())

    # Create the bot
    log.info('Creating bot...')
    bot = Bot(debug_instance=debug_instance)

    # Start it
    try:
        log.info('Running bot...')
        bot.run()
    except Exception as e:
        log.exception(f'Exiting on exception : {e}')
    else:
        log.info('Exiting normally')
    finally:
        logging.shutdown()
        exit(bot.do_restart)
