from os import curdir
import json

WORKDIR          = curdir
COGS             = WORKDIR + '/scarecrow/cogs'
CONFIG           = WORKDIR + '/config'
SCARECROW_CONFIG = CONFIG + '/scarecrow.json'
TWITTER_CONFIG   = CONFIG + '/twitter.json'

# TODO : rework the config

class ConfigElement(object):
    """Internal data class for Config, basically replaces a dict, because why not."""
    def __init__(self, data=None):
        if data is None:
            data = {}

        for key, val in data.items():
            # Transformations
            if isinstance(val, (list, tuple)):
                val = [ConfigElement(v) if isinstance(v, dict) else v for v in val]
            elif isinstance(val, dict):
                val = ConfigElement(val)

            # Registering element
            if getattr(self, key, None) is not None:
                # Because fuck your config, it will not shadow my beautiful attributes
                raise KeyError('Could not register attribute {}. An attribute with that name already exists.'.format(key))
            setattr(self, key, val)

    def delete(self, key):
        delattr(self, key)

    def get(self, key, default=None):
        return getattr(self, key, default)

    def set(self, key, val):
        setattr(self, key, val)

    def to_dict(self):
        return self.__dict__

    def __contains__(self, item):
        return self.__dict__.__contains__(str(item))

    def __iter__(self):
        return ConfigIterator(self)

    def __len__(self):
        return len(self.__dict__)

    def __setattr__(self, key, val):
        super().__setattr__(key, ConfigElement(val) if isinstance(val, dict) else val)


class Config(ConfigElement):
    """The config object we should mostly care about, created from a json file"""
    _excludes = ['file', 'encoding', 'object_hook', 'encoder']

    def __init__(self, file, **options):
        self.file = file
        self.encoding = options.pop('encoding', None)
        self.object_hook = options.pop('object_hook', None)
        self.encoder = options.pop('encoder', DefaultConfigEncoder)

        try:
            with open(self.file, 'r', encoding=self.encoding) as f:
                data = json.load(f, object_hook=self.object_hook)
        except FileNotFoundError:
            data = {}

        super().__init__(data)

    def to_dict(self):
        """Return a dict of the config data related attributes"""
        return {k: v for k, v in self.__dict__.items() if k not in self.__class__._excludes}

    def save(self):
        """Saves the config on disk"""
        with open(self.file, 'w', encoding=self.encoding) as fp:
            json.dump(self, fp, ensure_ascii=True, cls=self.encoder)


class DefaultConfigEncoder(json.JSONEncoder):
    def default(self, obj):
        return obj.to_dict()


class ConfigIterator:
    def __init__(self, conf):
        self.elements = [{'key': key, 'val': val} for key, val in conf.to_dict().items()]
        self.index = 0
        self.len = len(conf)

    def __iter__(self):
        return self

    def __next__(self):
        if self.index >= self.len:
            raise StopIteration

        elem = self.elements[self.index]
        self.index += 1
        return elem['key'], elem['val']

__all__ = ['Config', 'ConfigElement']