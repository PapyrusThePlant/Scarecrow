from os import curdir

WORK_DIR = f'{curdir}/'

COGS_DIR_NAME = 'cogs'
COGS_DIR = f'{WORK_DIR}{COGS_DIR_NAME}/'

CONFIG_DIR_NAME = 'conf'
CONFIG_DIR = f'{WORK_DIR}{CONFIG_DIR_NAME}/'
BOT_CONFIG = f'{CONFIG_DIR}bot.json'
IGNORED_CONFIG = f'{CONFIG_DIR}ignored.json'
PREFIXES_CONFIG = f'{CONFIG_DIR}prefixes.json'
TWITCH_CONFIG = f'{CONFIG_DIR}twitch.json'
TWITTER_CONFIG = f'{CONFIG_DIR}twitter.json'

DATA_DIR_NAME = 'data'
DATA_DIR = f'{WORK_DIR}{DATA_DIR_NAME}/'
INSULTS = f'{DATA_DIR}insults.txt'
WEEBNAMES = f'{DATA_DIR}weeb_names.txt'
OEMBED_PROVIDERS = f'{DATA_DIR}oEmbed_providers.json'

LOGS_DIR_NAME = 'logs'
LOGS_DIR = f'{WORK_DIR}{LOGS_DIR_NAME}/'
BOT_LOG = f'{LOGS_DIR}bot.log'
TWITTER_SUBPROCESS_LOG = f'{LOGS_DIR}twitter-sub-process.log'
