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
    """Information listing commands."""
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

    @commands.command(aliases=['charinfos'])
    async def charinfo(self, *, data: str):
        """Shows information about one or several characters.

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

    @commands.group(name='info', aliases=['infos'], invoke_without_command=True, pass_context=True)
    async def info_group(self, ctx):
        """Shows information about the bot."""
        members_count = sum(len(server.members) for server in self.bot.servers)
        unique_members_count = len(set(self.bot.get_all_members()))
        members_str = '{} ({} unique)'.format(members_count, unique_members_count)

        embed = discord.Embed(title='Bot support server invite', url='https://discord.gg/ZWnENfx', colour=0x738bd7)
        embed.set_author(name=self.bot.owner.name, icon_url=self.bot.owner.avatar_url)
        embed.add_field(name='Command prefixes', value=str(self.bot.command_prefix(self.bot, ctx.message))[1:-1])
        embed.add_field(name='Servers', value=str(len(self.bot.servers)))
        embed.add_field(name='Members', value=members_str)
        embed.add_field(name='Memory', value=self._get_memory_str())
        embed.add_field(name='Uptime', value=self._get_uptime_str())
        embed.add_field(name='Click this to invite me to your server :', value=dutils.oauth_url(self.bot.app_info.id), inline=False)
        embed.set_footer(text='Powered by discord.py', icon_url='http://i.imgur.com/5BFecvA.png')

        await self.bot.say(embed=embed)

    @info_group.command(name='channel', pass_context=True)
    async def info_channel(self, ctx, *, channel: discord.Channel=None):
        """Shows information about the channel."""
        if channel is None:
            channel = ctx.message.channel

        embed = discord.Embed(description=channel.mention, colour=0x738bd7)
        embed.add_field(name='ID', value=channel.id)
        embed.add_field(name='Server', value=channel.server.name)
        embed.add_field(name='Type', value=channel.type)
        embed.add_field(name='Position', value='#' + str(channel.position + 1))

        if str(channel.type) == 'text':
            embed.add_field(name='Private', value='Yes' if channel.is_private else 'No')
            if not channel.is_private:
                embed.add_field(name='Default channel', value='Yes' if channel.is_default else 'No')
        else:
            embed.add_field(name='Bitrate', value=str(channel.bitrate))
            embed.add_field(name='Members', value=str(len(channel.voice_members)))
            embed.add_field(name='User limit', value=str(channel.user_limit))

        await self.bot.say(embed=embed)

    @info_group.command(name='server', no_pm=True, pass_context=True)
    async def info_server(self, ctx):
        """Shows information about the server."""
        server = ctx.message.server

        # Order the roles and avoid mentions when listing them
        ordered_roles = server.roles.copy()
        ordered_roles.sort(key=lambda s: s.position)
        roles = [role.name.replace('@', '@\u200b') for role in ordered_roles]
        del ordered_roles

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
                default_channel = channel
            perms = channel.permissions_for(default_member)
            if channel.type == discord.ChannelType.text:
                text_channels += 1
                if not perms.read_messages:
                    locked_text += 1
            elif not perms.connect or not perms.speak:
                locked_voice += 1

        # Count the channels
        voice_channels = len(server.channels) - text_channels
        channels_fmt = 'Text : {} ({} locked)\n' \
                       'Voice : {} ({} locked)'
        channels = channels_fmt.format(text_channels, locked_text, voice_channels, locked_voice)

        # Count the members
        members_by_status = Counter('{}{}'.format(str(m.status), '_bot' if m.bot else '') for m in server.members)
        members_fmt = 'Total : {0}\n' \
                      'Online : {1[online]} ({1[online_bot]} bots)\n' \
                      'Idle : {1[idle]} ({1[idle_bot]} bots)\n' \
                      'Offline : {1[offline]} ({1[offline_bot]} bots)'
        members = members_fmt.format(len(server.members), members_by_status)

        # Gather the valid and permanent invites if we have permission to do so
        invite = None
        if ctx.message.channel.permissions_for(ctx.message.server.me).manage_server:
            # Get only permanent and valid invites
            invites = await self.bot.invites_from(server)
            main_invites = [i for i in invites if not i.revoked and i.max_age == 0]
            if main_invites:
                # Sort the invites by number of uses
                main_invites.sort(key=lambda i: i.uses, reverse=True)
                # Try to get an invite to the default channel
                invite = discord.utils.get(main_invites, channel=server.default_channel)
                if invite is None:
                    # Try to get an invite created by the server owner
                    invite = discord.utils.get(main_invites, inviter=server.owner)
                    if invite is None:
                        # Get the invite with the most uses
                        invite = main_invites[0]

        # Create and fill the embed
        if invite is not None:
            embed = discord.Embed(title='Server invite'.format(server.name), url=invite.url, colour=0x738bd7)
        else:
            embed = discord.Embed(colour=0x738bd7)
        embed.set_author(name=server.name, url=server.icon_url, icon_url=server.icon_url)
        embed.add_field(name='ID', value=server.id)
        embed.add_field(name='Owner', value=str(server.owner))
        embed.add_field(name='Region', value=server.region.value.title())
        embed.add_field(name='Members', value=members)
        embed.add_field(name='Channels', value=channels)
        embed.add_field(name='Default channel', value=default_channel.mention)
        embed.add_field(name='Roles', value=', '.join(roles))
        embed.set_footer(text='Server created the ')
        embed.timestamp = server.created_at

        await self.bot.say(embed=embed)

    @info_group.command(name='user')
    async def info_user(self, member: discord.Member=None):
        """Shows information about a user."""
        if member is None:
            return

        roles = [role.name.replace('@', '@\u200b') for role in member.roles]
        shared = sum(1 for m in self.bot.get_all_members() if m.id == member.id)

        voice = member.voice.voice_channel
        if voice is not None:
            other_people = len(voice.voice_members) - 1
            voice_fmt = '{} with {} others' if other_people else '{} by themselves'
            voice = voice_fmt.format(voice.name, other_people)
        else:
            voice = 'Not connected.'

        embed = discord.Embed(title=member.nick or member.name, url=member.avatar_url, colour=0x738bd7)
        embed.set_author(name=str(member))
        embed.set_thumbnail(url=member.avatar_url)
        embed.add_field(name='ID', value=member.id)
        embed.add_field(name='Servers', value='{} shared'.format(shared))
        embed.add_field(name='Joined', value=member.joined_at)
        embed.add_field(name='Roles', value=', '.join(roles))
        embed.add_field(name='Voice', value=voice)
        embed.set_footer(text='User created the ')
        embed.timestamp = member.created_at

        await self.bot.say(embed=embed)
