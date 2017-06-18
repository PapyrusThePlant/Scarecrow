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
    """When your curiosity takes over."""
    def __init__(self, bot):
        self.start_time = bot.start_time

    def _get_memory_str(self):
        # Expressed in bytes, turn to Mb and round to 2 decimals
        mem_info = psutil.Process().memory_full_info()
        return f'{mem_info.uss / 1048576:.2f} Mb'

    def _get_uptime_str(self):
        # Get the uptime
        uptime = round(time.time() - self.start_time)
        return utils.duration_to_str(uptime)

    @commands.command(aliases=['charinfos'])
    async def charinfo(self, ctx, *, data: str):
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
                raise commands.BadArgument('Invalid unicode escape sequence.')
            else:
                data = ''.join(chr(cp) for cp in code_points)
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
                ('Code point', f'{ord(data):04x}')
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
            await ctx.send(utils.format_block(content))
        else:
            # Minimal info for each character
            entries = [f'`{c}` | `\\u{ord(c):04x}` | `{unicodedata.name(c, "None")}` | {url_fmt.format(ord(c))}' for c in data]
            content = '\n'.join(entries)
            await ctx.send(content)

    @commands.group(name='info', aliases=['infos'], invoke_without_command=True)
    async def info_group(self, ctx):
        """Shows information about the bot."""
        unique_members = set()
        members_count = 0
        for member in ctx.bot.get_all_members():
            members_count += 1
            unique_members.add(member.id)
        unique_members_count = len(unique_members)

        members_str = f'{members_count} ({unique_members_count} unique)'
        owner = ctx.guild.get_member(ctx.bot.owner.id) or ctx.bot.owner
        perms = discord.Permissions(84992) # Read messages, read message history, send messages, embed links
        invite = dutils.oauth_url(ctx.bot.app_info.id, perms)
        prefixes = ctx.bot.command_prefix(ctx.bot, ctx.message)

        embed = discord.Embed(title='Click here to invite me to your server !', url=invite, colour=0x738bd7)
        embed.set_author(name=f'{owner.display_name} ({owner})', icon_url=owner.avatar_url)
        embed.add_field(name='Command prefixes', value="'" + "', '".join(prefixes) + "'")
        embed.add_field(name='Servers', value=len(ctx.bot.guilds))
        embed.add_field(name='Members', value=members_str)
        embed.add_field(name='Memory', value=self._get_memory_str())
        embed.add_field(name='Uptime', value=self._get_uptime_str())
        embed.set_footer(text='Powered by discord.py', icon_url='http://i.imgur.com/5BFecvA.png')

        await ctx.send(embed=embed)

    @info_group.command(name='channel', no_pm=True)
    async def info_channel(self, ctx, *, channel: utils.GuildChannelConverter=None):
        """Shows information about the channel.

        The channel can either be the name, the mention or the ID of a text or voice channel.
        If no channel is given, the text channel this command was used in is selected.
        """
        if channel is None:
            channel = ctx.channel

        embed = discord.Embed(description=channel.mention, colour=0x738bd7)
        embed.add_field(name='ID', value=channel.id)
        embed.add_field(name='Server', value=channel.guild.name)
        embed.add_field(name='Type', value='Text channel' if isinstance(channel, discord.TextChannel) else 'Voice channel')
        embed.add_field(name='Position', value=f'#{channel.position + 1}')

        if isinstance(channel, discord.VoiceChannel):
            embed.add_field(name='Bitrate', value=str(channel.bitrate))
            embed.add_field(name='Members', value=str(len(channel.members)))
            embed.add_field(name='User limit', value=str(channel.user_limit) if channel.user_limit > 0 else 'None')
        elif isinstance(channel, discord.TextChannel):
            embed.add_field(name='Default channel', value='Yes' if channel.is_default else 'No')

        await ctx.send(embed=embed)

    @info_group.command(name='guild', aliases=['server'], no_pm=True)
    async def info_guild(self, ctx):
        """Shows information about the server."""
        guild = ctx.guild

        # Order the roles and avoid mentions when listing them
        ordered_roles = guild.roles.copy()
        ordered_roles.sort(key=lambda s: s.position)
        roles = [role.name.replace('@', '@\u200b') for role in ordered_roles]
        del ordered_roles

        # Create a default member to test locked channels
        default_member = copy.copy(guild.me)
        default_member.roles = [guild.default_role]

        # Figure out how many channels are locked
        locked_text = 0
        locked_voice = 0
        for channel in guild.channels:
            perms = channel.permissions_for(default_member)
            if isinstance(channel, discord.TextChannel):
                if not perms.read_messages:
                    locked_text += 1
            elif not perms.connect or not perms.speak:
                locked_voice += 1

        # Count the channels
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        channels = f'Text : {text_channels} ({locked_text} locked)\n' \
                   f'Voice : {voice_channels} ({locked_voice} locked)'

        # Count the members
        members_by_status = Counter(f'{m.status}{"_bot" if m.bot else ""}' for m in guild.members)
        members_by_status['online'] += members_by_status['online_bot']
        members_by_status['idle'] += members_by_status['idle_bot']
        members_by_status['offline'] += members_by_status['offline_bot']
        members_fmt = 'Total : {0}\n' \
                      'Online : {1[online]} ({1[online_bot]} bots)\n' \
                      'Idle : {1[idle]} ({1[idle_bot]} bots)\n' \
                      'Offline : {1[offline]} ({1[offline_bot]} bots)'
        members = members_fmt.format(len(guild.members), members_by_status)

        # Gather the valid and permanent invites if we have permission to do so
        invite = None
        perms = ctx.channel.permissions_for(ctx.guild.me)
        if perms.manage_guild:
            # Get only permanent and valid invites
            invites = await guild.invites()
            invites = [inv for inv in invites if not inv.revoked and inv.max_age == 0]
            if invites:
                # Get the invite with the most uses
                invites.sort(key=lambda inv: inv.uses, reverse=True)
                invite = invites[0]

        # Create and fill the embed
        if invite is not None:
            embed = discord.Embed(title='Server invite', url=invite.url, colour=0x738bd7)
        else:
            embed = discord.Embed(colour=0x738bd7)
        embed.set_author(name=guild.name, url=guild.icon_url, icon_url=guild.icon_url)
        embed.add_field(name='ID', value=guild.id)
        embed.add_field(name='Owner', value=str(guild.owner))
        embed.add_field(name='Region', value=guild.region.value.title())
        embed.add_field(name='Members', value=members)
        embed.add_field(name='Channels', value=channels)
        embed.add_field(name='Default channel', value=guild.default_channel.mention)
        embed.add_field(name='Roles', value=', '.join(roles))
        embed.set_footer(text='Server created the ')
        embed.timestamp = guild.created_at

        await ctx.send(embed=embed)

    @info_group.command(name='user', no_pm=True)
    async def info_user(self, ctx, *, member: discord.Member):
        """Shows information about a user.

        The given member can either be found by ID, nickname or username.
        If no member is given, your info will be displayed.
        """
        if member is None:
            member = ctx.author
        roles = [role.name.replace('@', '@\u200b') for role in member.roles]
        shared = sum(1 for m in ctx.bot.get_all_members() if m.id == member.id)

        if member.voice:
            vc = member.voice.channel
            other_people = len(vc.members) - 1
            voice = f'{vc.name}, {"with {other_people} others" if other_people else "by themselves"}'
        else:
            voice = 'Not connected.'

        embed = discord.Embed(title=member.display_name, url=member.avatar_url, colour=0x738bd7)
        embed.set_author(name=str(member))
        embed.set_thumbnail(url=member.avatar_url)
        embed.add_field(name='ID', value=member.id)
        embed.add_field(name='Servers', value=f'{shared} shared')
        embed.add_field(name='Joined', value=member.joined_at)
        embed.add_field(name='Roles', value=', '.join(roles))
        embed.add_field(name='Voice', value=voice)
        embed.set_footer(text='User created the ')
        embed.timestamp = member.created_at

        await ctx.send(embed=embed)
