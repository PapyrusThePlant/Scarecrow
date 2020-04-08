import asyncio
import logging
import multiprocessing
import os
import sys
import time
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler

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


class TRFH(TimedRotatingFileHandler, RotatingFileHandler):
    """TimeRotatingFileHandler with the file naming convention of the RotatingFileHandler"""
    def __init__(self, filename, **kwargs):
        RotatingFileHandler.__init__(self, filename)
        TimedRotatingFileHandler.__init__(self, filename, **kwargs)

    def doRollover(self):
        """Mix of TimedRotatingFileHandler.doRollover and RotatingFileHandler.doRollover"""
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount > 0:
            for i in range(self.backupCount - 1, 0, -1):
                sfn = self.rotation_filename("%s.%d" % (self.baseFilename, i))
                dfn = self.rotation_filename("%s.%d" % (self.baseFilename,
                                                        i + 1))
                if os.path.exists(sfn):
                    if os.path.exists(dfn):
                        os.remove(dfn)
                    os.rename(sfn, dfn)
            dfn = self.rotation_filename(self.baseFilename + ".1")
            if os.path.exists(dfn):
                os.remove(dfn)
            self.rotate(self.baseFilename, dfn)
        if not self.delay:
            self.stream = self._open()

        # Compute the new rollover time
        current_time = int(time.time())
        dst_now = time.localtime(current_time)[-1]
        new_rollover_at = self.computeRollover(current_time)
        while new_rollover_at <= current_time:
            new_rollover_at = new_rollover_at + self.interval

        # If DST changes and midnight or weekly rollover, adjust for this.
        if (self.when == 'MIDNIGHT' or self.when.startswith('W')) and not self.utc:
            dst_at_rollover = time.localtime(new_rollover_at)[-1]
            if dst_now != dst_at_rollover:
                if not dst_now:  # DST kicks in before next rollover, so we need to deduct an hour
                    addend = -3600
                else:           # DST bows out before next rollover, so we need to add an hour
                    addend = 3600
                new_rollover_at += addend
        self.rolloverAt = new_rollover_at


if __name__ == '__main__':
    multiprocessing.set_start_method('spawn')
    debug_instance = 'debug' in sys.argv

    # Setup the root logger
    rlog = logging.getLogger()
    rlog.setLevel(logging.INFO)
    handler = TRFH(paths.BOT_LOG, when='midnight', backupCount=7, encoding='utf-8')
    handler.setFormatter(logging.Formatter('{asctime}:{levelname}:{name}:{message}', style='{'))
    rlog.addHandler(handler)

    # Setup the cogs logger
    if debug_instance:
        logging.getLogger('cogs').setLevel(logging.DEBUG)

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
        exit(bot.exit_code)
