from os import curdir

WORKDIR = curdir

COGS = f'{WORKDIR}/cogs/'

CONFIG = f'{WORKDIR}/conf/'
BOT_CONFIG = f'{CONFIG}bot.json'
IGNORED_CONFIG = f'{CONFIG}ignored.json'
PREFIXES_CONFIG = f'{CONFIG}prefixes.json'
TWITCH_CONFIG = f'{CONFIG}twitch.json'
TWITTER_CONFIG = f'{CONFIG}twitter.json'

DATA = f'{WORKDIR}/data/'
INSULTS = f'{DATA}insults.txt'
POLLS = f'{DATA}polls.json'
WEEBNAMES = f'{DATA}weeb_names.txt'
OEMBED_PROVIDERS = f'{DATA}oEmbed_providers.json'

LOGS = f'{WORKDIR}/logs/'
BOT_LOG = f'{LOGS}bot.log'
TWITTER_SUBPROCESS_LOG = f'{LOGS}twitter-sub-process.log'
