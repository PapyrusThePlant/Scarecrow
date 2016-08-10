import copy
import time
import unicodedata
from collections import Counter

import psutil

import discord
import discord.ext.commands as commands
import discord.utils as dutils

from .util import utils


def setup(bot):
    bot.add_cog(Info(bot))


class Info:
    """Information listing commands"""
    def __init__(self, bot):
        self.bot = bot

    def _get_memory_str(self):
        process = psutil.Process()
        mem_info = process.memory_info()

        # Expressed in bytes, turn to Mb and round to 2 decimals
        return '{0:.2f} Mb'.format(mem_info.rss / 1048576)

    def _get_uptime_str(self):
        # Get the uptime
        uptime = round(time.time() - self.bot.start_time)

        # Extract minutes, hours and days
        minutes, seconds = divmod(uptime, 60)
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

    @commands.command()
    async def avatar(self, member: discord.Member=None):
        """Retreives a member's avatar link.

        If no member is given, the bot's avatar link is given.
        """
        if member is None:
            await self.bot.say(self.bot.user.avatar_url)
        else:
            await self.bot.say(member.avatar_url)

    @commands.command(aliases=['charinfos'])
    async def charinfo(self, *, data: str):
        """Shows informations about a character.

        'data' can either be a character, a unicode escape sequence, a unicode character name or a string.
        If 'data' is a string only a summary of each character's info will be displayed.
        """
        data = data.lower()

        if data.startswith('\\u'):
            # Let's interpret the unicode escape sequence
            hex_values = data.split('\\u')[1:]
            try:
                code_points = [int(val, 16) for val in hex_values]
            except ValueError:
                await self.bot.say('Invalid unicode escape sequence.')
                return
            else:
                data = ''.join([chr(cp) for cp in code_points])
        elif len(data) > 1:
            # Maybe we've been given the character's name ?
            try:
                data = unicodedata.lookup(data)
            except KeyError:
                pass

        # Normalise the input
        data = unicodedata.normalize('NFC', data)
        url_fmt = '<http://unicode-table.com/en/{:X}>'

        if len(data) == 1:
            # Detailed info on the character
            entries = [
                ('Character', data),
                ('Name', unicodedata.name(data, 'None')),
                ('Code point', '{:04x}'.format(ord(data)))
            ]
            decomposition = unicodedata.decomposition(data)
            if decomposition != '':
                entries.append(('Decomposition', decomposition))

            combining = unicodedata.combining(data)
            if combining:
                entries.append(('Combining class', combining))

            entries.append(('Category', unicodedata.category(data)))
            bidirectional = unicodedata.bidirectional(data)
            entries.append(('Bidirectional', bidirectional if bidirectional != '' else 'None'))
            entries.append(('Mirrored', 'True' if unicodedata.mirrored(data) == 1 else 'False'))
            entries.append(('East asian width', unicodedata.east_asian_width(data)))
            entries.append(('Url', url_fmt.format(ord(data))))

            # Create the message's content and send it
            content = utils.indented_entry_to_str(entries)
            await self.bot.say_block(content)
        else:
            # Minimal info for each character
            entries = []
            for char in data:
                entries.append('{} | `\\u{:04x}` | {} | {}'.format(char,
                                                                    ord(char),
                                                                    unicodedata.name(char, 'None'),
                                                                    url_fmt.format(ord(char))))
            content = '\n'.join(entries)
            await self.bot.say(content)

    @commands.group(name='info', aliases=['infos'], invoke_without_command=True)
    async def info_group(self):
        """Shows informations about the bot."""
        entries = [
            ('Author', '{0.name} (Discord ID: {0.id})'.format(self.bot.owner)),
            ('Library', 'discord.py (Python)'),
            ('Uptime', self._get_uptime_str()),
            ('Memory', self._get_memory_str()),
            ('Support', 'https://discord.me/mad-plants'),
            ('Invite', dutils.oauth_url(self.bot.app_info.id))
        ]
        content = utils.indented_entry_to_str(entries)

        await self.bot.say_block(content)

    @info_group.command(name='cog')
    async def info_cog(self, cog_name):
        """Shows information about a cog."""
        if cog_name not in self.bot.cogs:
            await self.bot.say('Cog not loaded.')
            return

        cog = self.bot.cogs[cog_name]
        about = getattr(cog, '_{}__about'.format(cog_name), None)

        # Try to retreive the cog's about page
        if about and callable(about):
            content = about()
        else:
            content = 'Cog {} does not have any about page.'.format(cog_name)

        await self.bot.say_block(content)

    @info_group.command(name='channel', pass_context=True)
    async def info_channel(self, ctx):
        """Shows informations about the channel."""
        channel = ctx.message.channel

        entries = [
            ('Name', channel.name),
            ('ID', channel.id),
            ('Server', channel.server.name),
            ('Type', channel.type),
            ('Position', '#' + str(channel.position + 1))
        ]

        if str(channel.type) == 'text':
            entries.append(('Private', 'Yes' if channel.is_private else 'No'))

            if not channel.is_private:
                default_channel = None
                for channel in channel.server.channels:
                    if channel.is_default:
                        default_channel = channel
                entries.append(('Default channel', 'Yes' if channel == default_channel else 'No'))
        else:
            entries.append(('Bitrate', str(channel.bitrate)))
            entries.append(('Members', len(channel.voice_members)))
            entries.append(('User limit', str(channel.user_limit)))

        content = utils.indented_entry_to_str(entries)
        await self.bot.say_block(content)

    @info_group.command(name='server', no_pm=True, pass_context=True)
    async def info_server(self, ctx):
        """Shows informations about the server."""
        server = ctx.message.server

        # Avoid mentions when listing the roles
        roles = [role.name.replace('@', '@\u200b') for role in server.roles]

        # Create a default member to test locked channels
        default_member = copy.copy(server.me)
        default_member.id = '0'
        default_member.roles = [server.default_role]

        # Figure out what channels are locked
        locked_text = 0
        locked_voice = 0
        text_channels = 0
        default_channel = 'None'
        for channel in server.channels:
            if channel.is_default:
                default_channel = channel.name
            perms = channel.permissions_for(default_member)
            if channel.type == discord.ChannelType.text:
                text_channels += 1
                if not perms.read_messages:
                    locked_text += 1
            elif not perms.connect or not perms.speak:
                locked_voice += 1

        # Count the channels
        voice_channels = len(server.channels) - text_channels
        channels_fmt = '{} Text ({} locked) / {} Voice ({} locked)'
        channels = channels_fmt.format(text_channels, locked_text, voice_channels, locked_voice)

        # Count the members
        members_by_status = Counter('{}{}'.format(str(m.status), '_bot' if m.bot else '') for m in server.members)
        members_fmt = '{0} ({1[online]} online ({1[online_bot]} bots), ' \
                      '{1[idle]} idle ({1[idle_bot]} bots), ' \
                      '{1[offline]} offline ({1[offline_bot]} bots))'
        members = members_fmt.format(len(server.members), members_by_status)

        entries = [
            ('Name', server.name),
            ('ID', server.id),
            ('Icon', server.icon_url),
            ('Owner', server.owner),
            ('Created', server.created_at),
            ('Region', server.region),
            ('Members', members),
            ('Roles', ', '.join(roles)),
            ('Channels', channels),
            ('Default channel', default_channel)
        ]

        content = utils.indented_entry_to_str(entries)
        await self.bot.say_block(content)

    @info_group.command(name='user')
    async def info_user(self, member: discord.Member=None):
        """Shows informations about a user."""
        if member is None:
            return

        roles = [role.name.replace('@', '@\u200b') for role in member.roles]
        shared = sum(1 for m in self.bot.get_all_members() if m.id == member.id)

        voice = member.voice_channel
        if voice is not None:
            other_people = len(voice.voice_members) - 1
            voice_fmt = '{} with {} others' if other_people else '{} by themselves'
            voice = voice_fmt.format(voice.name, other_people)
        else:
            voice = 'Not connected.'

        entries = [
            ('Nickname', member.nick),
            ('Username', member.name),
            ('Tag', member.discriminator),
            ('ID', member.id),
            ('Created', member.created_at),
            ('Joined', member.joined_at),
            ('Roles', ', '.join(roles)),
            ('Servers', '{} shared'.format(shared)),
            ('Voice', voice),
            ('Avatar', member.avatar_url)
        ]

        content = '{}'.format(utils.indented_entry_to_str(entries))
        await self.bot.say_block(content)
