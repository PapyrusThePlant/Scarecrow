import collections
import inspect
import json
import os


class Config:
    """The config object, created from a json file"""
    def __init__(self, file, **options):
        super().__setattr__('_data', {})
        self.file = file
        self.encoding = options.pop('encoding', None)
        self.object_hook = options.pop('object_hook', _ConfigDecoder().decode)
        self.encoder = options.pop('encoder', _ConfigEncoder)

        try:
            with open(self.file, 'r', encoding=self.encoding) as fp:
                self._data = json.load(fp, object_pairs_hook=self.object_hook)
        except FileNotFoundError:
            pass

    def save(self):
        """Saves the config on disk"""
        tmp_file = self.file + '~'
        with open(tmp_file, 'w', encoding=self.encoding) as fp:
            json.dump(self._data, fp, ensure_ascii=True, cls=self.encoder)
        os.replace(tmp_file, self.file)

    # utility

    def __contains__(self, item):
        return item in self._data

    def __len__(self):
        return len(self._data)

    def __getattr__(self, item, default=None):
        return getattr(self._data, item, default)

    def __setattr__(self, key, value):
        if key in self._data:
            setattr(self._data, key, value)
        else:
            super().__setattr__(key, value)


class ConfigElement:
    def __iter__(self):
        return iter(self.__dict__)


class _ConfigEncoder(json.JSONEncoder):
    """Default JSON encoder."""
    def default(self, o):
        if isinstance(o, ConfigElement):
            d = o.__dict__.copy()

            # Ignore 'private' attributes
            for k in o.__dict__.keys():
                if k[0] == '_':
                    del d[k]

            d['__class__'] = o.__class__.__qualname__
            return d

        return json.JSONEncoder.default(self, o)


class _ConfigDecoder:
    """Default JSON decoder, do not instantiate as the inspect magic involved is not tailored for it."""
    def __init__(self):
        # Back once to reach Config.__init__
        # Back twice to reach the caller
        self._globals = inspect.currentframe().f_back.f_back.f_globals

    def decode(self, o):
        o = collections.OrderedDict(o)
        if '__class__' in o:
            name = o['__class__']

            # Get the top level module/class in the given name
            parts = name.split('.')
            obj = self._globals[parts[0]]

            # Walk the rest of the dotted path if any
            for part in parts[1:]:
                if inspect.ismodule(obj):
                    obj = getattr(obj, part, None)
                    if obj is None:
                        raise KeyError(f'Could not find {part} in {obj.__name__}')
                elif inspect.isclass(obj):
                    obj = obj.__dict__[part]
                else:
                    raise TypeError('Expected Class or Module.')

            del o['__class__']
            return obj(**o)
        else:
            return o
