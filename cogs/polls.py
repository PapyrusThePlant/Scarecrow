import asyncio
import datetime
import re

import discord
import discord.ext.commands as commands

import paths
from .util import config, utils


def setup(bot):
    bot.add_cog(Polls(bot))


def _format_index(i, w):
    return '`[{0:>{1}}]`'.format(i, w)


class DeltaParser(datetime.timedelta):
    """Turns a string with a specific format (see regex) into a datetime.timedelta."""
    # regex matching a duration in the form of a combination of: XXd, XXh, XXm, XXs
    _reg = re.compile(r"""^
                          ((?P<days>\d+)[dD])?
                          ((?P<hours>([0-1]?[0-9]|2[0-3]))[hH])?
                          ((?P<minutes>[0-5]?[0-9])[mM])?
                          ((?P<seconds>[0-5]?[0-9])[sS])?
                          $
                       """, re.X)

    def __new__(cls, value):
        """Raises BadArgument if the given string has an invalid format."""
        if value.isdigit():
            value += 's'

        match = cls._reg.match(value)
        if not match:
            raise commands.BadArgument('Invalid expiration format.')

        return super().__new__(cls, **{k: int(v) for k, v in match.groupdict().items() if v and int(v) > 0})


class PollConf(config.ConfigElement):
    def __init__(self, creator, title, **kwargs):
        self.creator = creator
        self.title = title
        self.open = kwargs.pop('open', True)
        self.strawpoll = kwargs.pop('strawpoll', None)
        self.expiration = kwargs.pop('expiration', 0)
        self.channel = kwargs.pop('channel', None)
        self.voters = kwargs.pop('voters', [])
        self.results = utils.OrderedCounter(kwargs.pop('results'))
        self._expiration_task = None

        options = kwargs.pop('options', None)
        self.results.update(options)
        if options is not None:
            for option in options:
                # Do not loose the order
                self.results[option] = 0

    def has_voted(self, user):
        if isinstance(user, discord.User):
            return user.id in self.voters
        elif isinstance(user, str):
            return user in self.voters
        else:
            raise TypeError("Expected type 'str' or 'User' but got {}.".format(type(user)))

    @property
    def votes_count(self):
        return sum(self.results.values())

    def format(self, guild, show_results=False):
        results_index_width = len(str(len(self.results)))
        creator = discord.utils.get(guild.members, id=self.creator)
        if show_results:
            fmt = '**{votes}** {name}'
        else:
            fmt = '{index} {name}'

        entries = []
        if not show_results:
            entries.append('**Creator:** {}'.format(creator))
        entries.append('**Title:** {}'.format(self.title))
        entries.append('**Open:** {}'.format('Yes' if self.open else 'No'))
        entries.append('**Total votes:** {}'.format(self.votes_count))

        if not show_results:
            if self.expiration > 0:
                expiration = utils.duration_to_str(self.expiration - asyncio.get_event_loop().time())
                entries.append('**Expires in:** {}'.format(expiration))
            res_label = '**Options:**'
            results = self.results.items()
        else:
            res_label = '**Results:**'
            results = self.results.most_common()

        entries.append(res_label)
        for result_id, result in enumerate(results):
            entries.append(fmt.format(index=_format_index(result_id, results_index_width),
                                      name=result[0],
                                      votes=result[1]))

        return '\n'.join(entries)


class Polls:
    """Polls commands"""
    def __init__(self, bot):
        self.bot = bot
        self.polls = config.Config(paths.POLLS, encoding='utf-8')
        self.initialised = False

    async def on_ready(self):
        if self.initialised:
            return

        # Schedule the expiration callbacks
        for sid, poll_list in self.polls.items():
            for poll in poll_list:
                if poll.expiration > 0:
                    self._schedule_expiration(sid, poll)

        self.initialised = True

    def get_polls(self, guild_id, *, check=None):
        polls = self.polls.get(guild_id, None)
        if not polls:
            return 'No poll found.'

        polls_index_width = len(str(len(polls)))

        entries = []
        for poll_id, poll in enumerate(polls):
            if not check or check(poll):
                entries.append('{} {}'.format(_format_index(poll_id, polls_index_width), poll.title))

        if not entries:
            return 'No poll found.'
        else:
            return '\n'.join(entries)

    def _schedule_expiration(self, sid, poll):
        def expire():
            channel = self.bot.get_channel(poll.target)
            if channel is None:
                # Channel unreachable
                return
            content = 'The following poll has expired, here are the results:\n' + poll.format(channel.guild, show_results=True)
            self.bot.loop.create_task(channel.send(content))
            poll.open = False
            self.polls.save()

        if poll.expiration > 0 and poll.expiration > self.bot.loop.time():
            poll._expiration_task = self.bot.loop.call_at(poll.expiration, expire)
        else:
            expire()

    def __unload(self):
        # Cancel the scheduled expiration tasks
        for poll in self.polls.values():
            if poll.expiration > 0:
                poll._expiration_task.cancel()
    
    async def on_guild_remove(self, guild):
        # Cancel the sheduled expiration tasks
        for poll in self.polls.get(guild.id):
            if poll.expiration > 0:
                poll._expiration_task.cancel()
        
        # Remove the polls
        try:
            del self.polls[guild.id]
        except:
            pass
        else:
            self.polls.save()

    @commands.group(name='poll', invoke_without_command=True)
    async def poll_group(self, ctx, poll_id: int):
        """Shows the poll's information."""
        polls = self.polls.get(ctx.guild.id, None)
        poll = polls[poll_id] if polls and poll_id < len(polls) else None
        if not poll:
            raise commands.BadArgument('Poll not found.')

        await ctx.send(poll.format(ctx.guild))

    @poll_group.command(name='clean')
    @commands.has_permissions(manage_guild=True)
    async def poll_clean(self, ctx):
        polls = self.polls.get(ctx.guild.id, None)
        for poll in polls.copy():
            if not poll.open:
                polls.remove(poll)
        self.polls.save()

    @poll_group.command(name='create')
    async def poll_create(self, ctx, duration: DeltaParser, title, *options):
        """Creates a poll.

        If the duration is greater than 0, the poll will report its results in the
        channel the command was used in and close itself.
        The duration is assumed to be in seconds but can be modified with units such
        as 'd' for days, 'h' for hours, 'm' for minutes and 's' for seconds. The unit
        modifiers can be combined for more precision, e.g 1d10h40m or 5h40s.
        """
        polls = self.polls.get(ctx.guild.id, None)
        if not polls:
            # Check if polls already exist for that guild
            polls = []
            self.polls[ctx.guild.id] = polls
        elif discord.utils.get(polls, title=title):
            # Check the poll's title is unique
            raise commands.BadArgument('A poll with that name already exists.')

        if duration.total_seconds() > 604800:  # 7 days
            raise commands.BadArgument("The maximum duration for a poll is 7 days.")

        if duration.total_seconds() > 0:
            expiration = self.bot.loop.time() + duration.total_seconds()
        else:
            expiration = 0

        # Create the new poll and add it to the guild's polls list
        poll = PollConf(ctx.author.id,
                        title,
                        expiration=expiration,
                        target=ctx.message.channel.id,
                        options=options)
        polls.append(poll)

        # Schedule the poll's expiration
        if expiration > 0:
            self._schedule_expiration(ctx.guild.id, poll)

        index = len(polls)
        self.polls.save()
        await ctx.send('Poll created at index {0}. Type `{1}poll {0}` to review it.'.format(index, ctx.prefix))

    @poll_group.command(name='delete', pass_context=True)
    async def poll_delete(self, ctx, poll_id: int):
        """Deletes a poll.

        Only the creator of a poll or a member with the `Manage Server` permission
        can delete a poll.
        """
        guild_id = ctx.guild.id
        polls = self.polls.get(guild_id, None)
        poll = polls[poll_id] if polls and poll_id < len(polls) else None
        if not poll:
            raise commands.BadArgument('Poll not found.')

        # Check if the member invoking the deletion has the right to do so
        if not poll.creator == ctx.author.id and not ctx.channel.permissions_for(ctx.author).manage_guild:
            raise commands.CheckFailure("Only the poll's creator or someone with the `Manage Server` permission can delete a poll.")

        # Delete the poll
        polls.remove(poll)
        if len(polls) == 0:
            self.polls.pop(guild_id)
        self.polls.save()
        await ctx.send(':ok_hand:')

    @poll_group.command(name='list')
    async def poll_list(self, ctx):
        """Lists the polls."""
        await ctx.send(self.get_polls(ctx.guild.id))

    @poll_group.command(name='make')
    async def poll_make(self, ctx):
        """Interactively create a poll.

        This is a more user friendly version of the poll create command.
        """
        message = ctx.message

        def check(msg):
            return msg.channel == message.channel and msg.author == message.author

        # Start with the poll's title
        await ctx.send("Yay let's make a poll !\n"
                       "What will its title be?")
        title = await ctx.bot.wait_for('message', check=check, timeout=60)
        if not title:
            raise commands.UserInputError('{} You took too long, aborting poll creation.'.format(message.author.mention))

        # Loop and register the poll's options until the user says we're done
        await ctx.send("Ok ! Now tell me the poll's options in order.")
        options = []
        while True:
            await ctx.send("What will be entry #{}? (type `No more options` when you're done)".format(len(options)))
            entry = await ctx.bot.wait_for('message', check=check, timeout=60)
            if not entry:
                raise commands.UserInputError('{} You took too long, aborting poll creation.'.format(message.author.mention))

            if entry.content.lower() == 'no more options':
                break

            options.append(entry.content)

        # Ask for the poll duration
        await ctx.send("Sweet ! Do you want the poll to expire after a set duration ? (y/n)")
        resp = await ctx.bot.wait_for('message', check=check, timeout=60)
        if not resp:
            raise commands.UserInputError('{} You took too long, aborting poll creation.'.format(message.author.mention))

        if resp.content[0] == 'y':
            await ctx.send("What will the duration be ?\n"
                           "The duration is assumed to be in seconds but can be modified with units such as 'd' for days, 'h' for hours, 'm' for minutes and 's' for seconds. The unit modifiers can be combined for more precision, e.g 1d10h40m or 5h40s.")
            duration = await ctx.bot.wait_for_message('message', check=check, timeout=60)
            if not duration:
                raise commands.UserInputError('{} You took too long, aborting poll creation.'.format(message.author.mention))

            expiration = DeltaParser(duration.content)
        else:
            expiration = DeltaParser('0')

        # Create the poll
        await ctx.invoke(self.poll_create, expiration, title.content, *options)

    @poll_group.command(name='results')
    async def poll_results(self, ctx, poll_id: int):
        """Prints the current results of a poll."""
        polls = self.polls.get(ctx.guild.id, None)
        poll = polls[poll_id] if polls and poll_id < len(polls) else None
        if not poll:
            raise commands.BadArgument('Poll not found.')

        await ctx.send(poll.format(ctx.guild, show_results=True))

    @commands.group(name='strawpoll', hidden=True, invoke_without_command=True)
    async def strawpoll_group(self, ctx, poll_id):
        """Retrieves the strawpoll.me data for a given poll."""
        # https://strawpoll.zendesk.com/hc/en-us/articles/218979828-Straw-Poll-API-Information
        pass

    @strawpoll_group.command(name='list')
    async def strawpoll_list(self, ctx):
        """Lists the strawpoll polls."""
        await ctx.send(self.get_polls(ctx.guild.id, check=lambda p: p.strawpoll))

    @strawpoll_group.command(name='create')
    async def strawpoll_create(self, ctx, poll_id):
        """Creates a poll on strawpoll.me from an existing poll."""
        # Note : Needs to invalidate the voting on discord. Add a warning and a confirmation.
        # https://strawpoll.zendesk.com/hc/en-us/articles/218979828-Straw-Poll-API-Information
        pass

    @commands.command()
    async def vote(self, ctx, poll_id: int, entry_id: int):
        """Votes in a poll.

        Get the poll id from the `poll list` command and get
        the entry id from the `poll <poll_id>` command.
        """
        polls = self.polls.get(ctx.guild.id, None)
        poll = polls[poll_id] if polls and poll_id < len(polls) else None

        if not poll:
            raise commands.BadArgument('Poll not found.')

        if poll.has_voted(ctx.author):
            raise commands.BadArgument('You already have voted on this poll.')

        if entry_id >= len(poll.results):
            raise commands.BadArgument('Option not found.')

        option = poll.results.item_at(entry_id)
        option += 1
        self.polls.save()
        await ctx.send('Vote cast !')
