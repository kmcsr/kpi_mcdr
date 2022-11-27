
import abc
import copy
import os
import json
from typing import get_type_hints, Dict

import mcdreforged.api.all as MCDR

from .utils import *

__all__ = [
	'Config', 'JSONStorage',
]

def tr(key: str, *args, **kwargs):
	return MCDR.ServerInterface.get_instance().rtr(f'kpi.{key}', *args, **kwargs)

class JSONStorage(abc.ABC):
	__fields: dict

	def __init__(self, plugin: MCDR.PluginServerInterface,
		file_name: str = 'config.json', *, in_data_folder: bool = True,
		sync_update: bool = False, load_after_init: bool = False,
		kwargs: dict = None):
		assert isinstance(plugin, MCDR.PluginServerInterface)
		self.__plugin_server = plugin
		self._file_name = file_name
		self._in_data_folder = in_data_folder
		self._sync_update = sync_update
		vars(self).update((k, getattr(self.__class__, k)) for k in self.get_fields().keys())
		if kwargs is not None:
			for k in kwargs.keys():
				if k not in self.get_fields():
					raise KeyError('Unknown init key received in __init__ of class {0}: {1}'.format(self.__class__, k))
			vars(self).update(kwargs)
		if load_after_init:
			self.load()

	def __init_subclass__(cls):
		fields = {}
		for name, typ in get_type_hints(cls).items():
			if not name.startswith('_'):
				fields[name] = typ
		cls.__fields = fields

	@classmethod
	def get_fields(cls):
		return cls.__fields

	@property
	def plugin(self):
		return self.__plugin_server

	@property
	def file_name(self):
		return self._file_name

	@file_name.setter
	def file_name(self, file_name):
		self._file_name = file_name

	@property
	def default_path(self):
		return os.path.join(self.plugin.get_data_folder(), self.file_name) if self._in_data_folder else self.file_name

	@property
	def sync_update(self):
		return self._sync_update

	@sync_update.setter
	def sync_update(self, val: bool):
		self._sync_update = val

	def serialize(self) -> dict:
		return copy.deepcopy(dict(filter(lambda o: not o[0].startswith('_'), vars(self).items())))

	def update(self, data: dict):
		vself = vars(self)
		for k, v in data.items():
			if k in vself:
				vself[k] = v

	def save(self, *, path: str = None):
		if path is None:
			path = self.default_path
		with open(path, 'w') as fd:
			json.dump(self.serialize(), fd, indent=4, ensure_ascii=False)
		self.on_saved()

	def load(self, *, path: str = None, error_on_missing: bool = False):
		if path is None:
			path = self.default_path
		if not os.path.exists(path):
			if error_on_missing:
				raise FileNotFoundError(f'Cannot find storage file: "{path}"')
			log_warn('Cannot find storage file: "{}"'.format(path))
			self.save(path=path)
			return
		data: dict
		try:
			with open(path, 'r') as fd:
				data = json.load(fd)
		except json.decoder.JSONDecodeError as e:
			log_warn('Decode "{0}" error: {1}'.format(path, e))
			self.save(path=path)
		else:
			log_info('Successful load file "{}"'.format(path))
			self.update(data)

	def on_saved(self):
		pass

	def on_loaded(self):
		pass

	def __setattr__(self, name: str, val):
		typ = self.__class__.__fields.get(name, None)
		if typ is not None:
			assert isinstance(val, typ)
		super().__setattr__(name, val)
		if typ is not None and self._sync_update:
			self.save()

class Config(JSONStorage):
	def __init_subclass__(cls, msg_id, def_level: int = 4, **kwargs):
		super().__init_subclass__(**kwargs)
		cls.msg_id = msg_id
		cls.def_level = def_level
		cls.instance = None

	@classmethod
	def init_instance(cls, plugin: MCDR.PluginServerInterface, *args, sync_update: bool = True, **kwargs):
		assert cls.instance is None
		cls.instance = cls(plugin, *args, sync_update=sync_update, **kwargs)
		return cls.instance

	# 0:guest 1:user 2:helper 3:admin 4:owner
	minimum_permission_level: Dict[str, int] = {}

	@property
	def server(self) -> MCDR.PluginServerInterface:
		return self.plugin

	def get_permission(self, literal: str):
		return self.minimum_permission_level.get(literal, self.__class__.def_level)

	def has_permission(self, src: MCDR.CommandSource, literal: str):
		return src.has_permission(self.get_permission(literal))

	def get_permission_hint(self) -> MCDR.RText:
		return MCDR.RText(tr('permission.denied', cls.msg_id.to_plain_text()), color=MCDR.RColor.red)

	@property
	def permission_hint(self) -> MCDR.RText:
		return self.get_permission_hint()

	def literal(self, literal: str):
		cls = self.__class__
		return MCDR.Literal(literal).requires(lambda src: self.has_permission(src, literal), self.get_permission_hint)

class Properties:
	def __init__(self, file: str):
		self._file = file
		self._data = {}
		if os.path.exists(file):
			self.parse()

	def parse(self):
		self._data.clear()
		with open(self._file, 'r') as fd:
			while True:
				line = fd.readline()
				if not line:
					break
				line = line.lstrip()
				if not line or line[0] in '#!':
					continue
				a, b = line.find('='), line.find(':')
				i = (max if a == -1 or b == -1 else min)(a, b)
				if i == -1:
					raise ValueError()
				k, v = line[:i].rstrip(), line[i + 1:].lstrip()
				if len(v) > 0:
					while v[-1] == '\\':
						v = v[:-1] + fd.readline().lstrip()
					unescape_string(v)
				self._data[k] = v

	def save(self, comment: str = None):
		with open(self._file, 'w', encoding='utf8') as fd:
			if comment is not None:
				fd.write(f'# {comment}\n')
			fd.writelines([
				f'{k}={v}\n' for k, v in self._data.items()
			])

	def __str__(self):
		return str(self._data)

	def __iter__(self):
		return iter(self._data.copy().items())

	def __getitem__(self, key: str):
		if key not in self._data:
			raise KeyError(key)
		return self._data[key]

	def __setitem__(self, key: str, value):
		self._data[key] = str(value)

	def items(self):
		return self._data.items()

	def keys(self):
		return self._data.keys()

	def values(self):
		return self._data.values()

	def get(self, key: str, default=None) -> str:
		if key not in self._data:
			return default
		v = self._data[key]
		if len(v) == 0:
			return default
		return v

	def set(self, key: str, value):
		if isinstance(value, bool):
			self._data[key] = 'true' if value else 'false'
		elif isinstance(value, str):
			self._data[key] = escape_string(value)
		else:
			self._data[key] = str(value)

	def has(self, key: str) -> bool:
		return key in self._data

	def get_int(self, key: str, default: int = 0) -> int:
		return int(self.get(key, default))

	def get_float(self, key: str, default: float = 0) -> float:
		return float(self.get(key, default))

	def get_str(self, key: str, default: str = '') -> str:
		return str(self.get(key, default))

	def get_bool(self, key: str, default: bool = False) -> bool:
		if key not in self._data:
			return default
		v = self._data[key]
		if v in ('true', 'TRUE', 'True'):
			return True
		if v in ('false', 'FALSE', 'False'):
			return False
		raise ValueError(f'Value "{v}" is not a bool')

def unescape_string(src: str) -> str:
	if '\\' not in src:
		return src
	val = ''
	i = 0
	while True:
		j = src.find('\\', i)
		if j == -1:
			break
		val += src[i:j]
		c, i = _unescape_chr(src, j + 1)
		val += c
	val += src[i:]
	return val

_UNESCAPE_MAP = {
	'a': '\a',
	'b': '\b',
	'f': '\f',
	'n': '\n',
	'r': '\r',
	't': '\t',
	'v': '\v',
	'\\': '\\',
}

def _unescape_chr(src: str, i: int) -> tuple[str, int]:
	t = src[i].lower()
	c = _UNESCAPE_MAP.get(t, None)
	if c is not None:
		return c, i + 1
	if '0' <= t and t <= '7':
		j = i + 1
		while j < i + 3 and j < len(src) and ('0' <= src[j] and src[j] <= '7'):
			j += 1
		c = chr(int(src[i:j], base=8))
		return c, j
	if t == 'x':
		return _decode_hex(src, i + 1, 2)
	if t == 'u':
		return _decode_hex(src, i + 1, 4)
	return src[i], i + 1

def _decode_hex(src: str, i: int, xlen: int) -> tuple[str, int]:
	j = i + xlen
	if j > len(src):
		raise IndexError('string index out of range when encoding string')
	c = chr(int(src[i:j], base=16))
	return c, j

def escape_string(src: str) -> str:
	if src.isascii() and src.isprintable():
		return src
	val = ''
	for c in src:
		if not (c.isascii() and c.isprintable()):
			c = '\\' + _escape_chr(c)
		val += c
	return val

_ESCAPE_MAP = {
	'\a': 'a',
	'\b': 'b',
	'\f': 'f',
	'\n': 'n',
	'\r': 'r',
	'\t': 't',
	'\v': 'v',
	'\\': '\\',
}

def _escape_chr(c: str) -> str:
	s = _ESCAPE_MAP.get(c, None)
	if s is not None:
		return s
	n = ord(c)
	if n <= 0xff:
		return 'x' + _encode_hex(n, 2)
	return 'u' + _encode_hex(n, 4)

def _encode_hex(n: int, xlen: int) -> str:
	s = hex(n)[2:]
	assert len(s) <= xlen
	s = s.rjust(xlen, '0')
	return s
