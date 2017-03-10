from os import curdir

WORKDIR = curdir

COGS = WORKDIR + '/cogs/'

CONFIG = WORKDIR + '/conf/'
BOT_CONFIG = CONFIG + 'bot.json'
IGNORED_CONFIG = CONFIG + 'ignored.json'
PREFIXES_CONFIG = CONFIG + 'prefixes.json'
TWITCH_CONFIG = CONFIG + 'twitch.json'
TWITTER_CONFIG = CONFIG + 'twitter.json'

DATA = WORKDIR + '/data/'
INSULTS = DATA + 'insults.txt'
WEEBNAMES = DATA + 'weeb_names.txt'
OEMBED_PROVIDERS = DATA + 'oEmbed_providers.json'

LOGS = WORKDIR + '/logs/'
BOT_LOG = LOGS + 'bot.log'
TWITTER_SUBPROCESS_LOG = LOGS + 'twitter-sub-process-{pid}.log'
