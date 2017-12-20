"""
This gather stuff that for the most part should be written elsewhere but is not because ¯\_(ツ)_/¯
"""
import aiohttp
import asyncio
import collections
import random
import re

import discord
import discord.ext.commands as commands


class GuildChannelConverter(commands.IDConverter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        match = self._get_id_match(argument)

        if match is None:
            # not a mention
            result = discord.utils.get(ctx.bot.get_all_channels(), name=argument)
        else:
            guild_id = int(match.group(1))
            result = ctx.bot.get_channel(guild_id)

        if not isinstance(result, (discord.TextChannel, discord.VoiceChannel)):
            raise commands.BadArgument(f'Channel "{argument}" not found.')

        return result


class GuildConverter(commands.IDConverter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        match = self._get_id_match(argument)

        if match is None:
            # not a mention
            result = discord.utils.get(ctx.bot.guilds, name=argument)
        else:
            guild_id = int(match.group(1))
            result = ctx.bot.get_guild(guild_id)

        if not isinstance(result, discord.Guild):
            raise commands.BadArgument(f'Guild "{argument}" not found.')

        return result


class HTTPError(Exception):
    def __init__(self, resp, message):
        self.response = resp
        if isinstance(message, dict):
            self.resp_msg = message.get('message', message.get('msg', ''))
            self.code = message.get('code', message.get('status', 0))
        else:
            self.resp_msg = message

        super().__init__(f'{resp.reason} (status code: {resp.status}){f": {self.resp_msg}" if self.resp_msg else ""}')


def dict_keys_to_int(d):
    """#HowToBeLazy"""
    return {int(k): v for k, v in d.items()}


class OrderedCounter(collections.Counter, collections.OrderedDict):
    """A counter that remembers the order elements are first encountered."""

    def __repr__(self):
        return f'{self.__class__.__name__}({repr(collections.OrderedDict(self))})'

    def __reduce__(self):
        return self.__class__, (collections.OrderedDict(self),)

    def item_at(self, index):
        return self[list(self.keys())[index]]


def duration_to_str(duration):
    # Extract minutes, hours and days
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    # Create a fancy string
    return f"{f'{days} days, ' if days > 0 else ''}{f'{hours} hours, ' if hours > 0 else ''}{f'{minutes} minutes, ' if minutes > 0 else ''}{seconds} seconds"


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
        content_type = [ct.strip() for ct in resp.headers['content-type'].split(';')]
        if 'application/json' in content_type:
            data = await resp.json()
        elif 'image/' in content_type:
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


def format_block(content, language=''):
    """Formats text into a code block."""
    return f'```{language}\n{content}\n```'


def indented_entry_to_str(entries, indent=0, sep=' '):
    """Pretty formatting."""
    # Get the longest keys' width
    width = max([len(t[0]) for t in entries])

    output = []
    for name, entry in entries:
        if indent > 0:
            output.append(f'{"":{indent}}{name:{width}}{sep}{entry}')
        else:
            output.append(f'{name:{width}}{sep}{entry}')

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
