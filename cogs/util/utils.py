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


class GuildChannelConverter(commands.Converter):
    def __init__(self):
        self._id_regex = re.compile(r'([0-9]{15,21})$')

    def _get_id_match(self):
        return self._id_regex.match(self.argument)

    def convert(self):
        match = self._get_id_match()

        if match is None:
            # not a mention
            result = discord.utils.get(self.ctx.bot.get_all_channels(), name=self.argument)
        else:
            guild_id = int(match.group(1))
            result = self.ctx.bot.get_channel(guild_id)

        if not isinstance(result, (discord.TextChannel, discord.VoiceChannel)):
            raise commands.BadArgument('Guild "{}" not found.'.format(self.argument))

        return result


class GuildConverter(commands.Converter):
    def __init__(self):
        self._id_regex = re.compile(r'([0-9]{15,21})$')

    def _get_id_match(self):
        return self._id_regex.match(self.argument)

    def convert(self):
        match = self._get_id_match()

        if match is None:
            # not a mention
            result = discord.utils.get(self.ctx.bot.guilds, name=self.argument)
        else:
            guild_id = int(match.group(1))
            result = self.ctx.bot.get_guild(guild_id)

        if not isinstance(result, discord.Guild):
            raise commands.BadArgument('Guild "{}" not found.'.format(self.argument))

        return result


class HTTPError(Exception):
    def __init__(self, resp, message):
        self.response = resp
        if isinstance(message, dict):
            self.resp_msg = message.get('message', message.get('msg', ''))
            self.code = message.get('code', 0)
        else:
            self.resp_msg = message

        fmt = '{0.reason} (status code: {0.status})'
        if len(self.resp_msg):
            fmt += ': {1}'

        super().__init__(fmt.format(self.response, self.resp_msg))


def dict_keys_to_int(d):
    """#HowToBeLazy"""
    return {int(k): v for k, v in d.items()}


class OrderedCounter(collections.Counter, collections.OrderedDict):
    """A counter that remembers the order elements are first encountered."""

    def __repr__(self):
        return '{}({})'.format(self.__class__.__name__, repr(collections.OrderedDict(self)))

    def __reduce__(self):
        return self.__class__, (collections.OrderedDict(self),)

    def item_at(self, index):
        return self[list(self.keys())[index]]


def duration_to_str(duration):
    # Extract minutes, hours and days
    minutes, seconds = divmod(duration, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)

    # Create the string format
    if days > 0:
        fmt = '{d} days, {h} hours, {m} minutes, {s} seconds'
    elif hours > 0:
        fmt = '{h} hours, {m} minutes, {s} seconds'
    elif minutes > 0:
        fmt = '{m} minutes, {s} seconds'
    else:
        fmt = '{s} seconds'

    # Create the string and return it
    return fmt.format(d=days, h=hours, m=minutes, s=seconds)


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
    return '```{}\n{}\n```'.format(language, content)


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
