"""
This gather stuff that for the most part should be written elsewhere but is not because ¯\_(ツ)_/¯
"""
import aiohttp
import asyncio
import random

import discord.utils as dutils
from discord.ext.commands import BadArgument, Converter


class ServerConverter(Converter):
    def convert(self):
        bot = self.ctx.bot

        result = dutils.get(bot.servers, name=self.argument)
        if result is None:
            result = bot.get_server(self.argument)

        if result is None:
            raise BadArgument('Member "{}" not found'.format(self.argument))

        return result


class HTTPError(Exception):
    def __init__(self, resp, message):
        self.response = resp
        if type(message) is dict:
            self.resp_message = message.get('message', message.get('msg', ''))
            self.code = message.get('code', 0)
        else:
            self.resp_message = message

        fmt = '{0.reason} (status code: {0.status})'
        if len(self.resp_message):
            fmt += ': {1}'

        super().__init__(fmt.format(self.response, self.resp_message))

async def fetch_page(url, **kwargs):
    """Fetches a web page and return its text or json content."""
    session = kwargs.pop('session', None)
    timeout = kwargs.pop('timeout', None)

    # Create a session if none has been given
    _session = session or aiohttp.ClientSession()

    resp = None
    try:
        resp = await asyncio.wait_for(_session.get(url, **kwargs), timeout)
    except asyncio.TimeoutError:
        data = None
    else:
        if resp.headers['content-type'] == 'application/json':
            data = await resp.json()
        elif 'image/' in resp.headers['content-type']:
            return resp.url
        else:
            data = await resp.text()

        if resp.status != 200:
            raise HTTPError(resp, data)
    finally:
        if resp:
            await resp.release()
        if not session:
            _session.close()

    return data


def indented_entry_to_str(entries, indent=0, sep=' '):
    """Pretty formatting."""
    # Get the longest keys' width
    # width = [max([len(t[i]) for t in entries]) for i in range(0, len(entries) - 1)]
    width = max([len(t[0]) for t in entries])

    output = []

    # Set the format for each line
    if indent > 0:
        fmt = '{0:{indent}}{1:{width}}{sep}{2}'
    else:
        fmt = '{1:{width}}{sep}{2}'

    for name, entry in entries:
        output.append(fmt.format('', name, entry, width=width, indent=indent, sep=sep))

    return '\n'.join(output)


def random_line(file_name, predicate=None):
    """Reservoir algorithm to randomly draw one line from a file."""
    with open(file_name, 'r', encoding='utf-8') as file:
        file = filter(predicate, file)
        line = next(file)
        for num, aline in enumerate(file):
            if random.randrange(num + 2):
                continue
            line = aline
    return line
