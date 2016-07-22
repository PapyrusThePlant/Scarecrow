from collections import namedtuple
from .scarecrow import Scarecrow

# Stuff
__title__ = 'scarecrow'
__author__ = 'Papyrus'
__version__ = '0.1.0-alpha'

VersionTuple = namedtuple('VersionTuple', 'major minor micro releaselevel serial')
version_info = VersionTuple(
    0,        # major
    1,        # minor
    0,        # micro
    'alpha',  # release level
    0         # serial
)

__all__ = ['__title__', '__author__', '__version__', 'version_info', 'Scarecrow']
