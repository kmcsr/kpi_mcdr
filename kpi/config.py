
import abc
import copy
import os
import json
from typing import get_type_hints, Dict, Any, Union

import mcdreforged.api.all as MCDR

from .utils import *

__all__ = [
	'JSONObject', 'JSONStorage', 'Config',
]

def tr(key: str, *args, **kwargs):
	return MCDR.ServerInterface.get_instance().rtr(f'kpi.{key}', *args, **kwargs)

def testInstance(ins, typ):
	if typ is Any:
		return True
	if isinstance(typ, type): # if `typ` is origin type
		return isinstance(ins, typ)
	if hasattr(typ, '__origin__'): # if `typ` is typing type or subscript type
		typ_origin = typ.__origin__
		if typ_origin is Union:
			return any(testInstance(ins, t) for t in typ_origin.__args__)
		if isinstance(typ_origin, type):
			if not isinstance(ins, typ_origin):
				return False
			if hasattr(typ, '__args__'):
				typ_args = typ.__args__
				if isinstance(typ_origin, list):
					etyp = typ_args[0]
					return all(testInstance(e, etyp) for e in ins)
				if isinstance(typ_origin, tuple):
					if len(typ_args) == 1:
						etyp = typ_args[0]
						return all(testInstance(e, etyp) for e in ins)
					return all(testInstance(ins[i], t) for i, t in typ_args)
				if isinstance(typ_origin, dict):
					kt, vt = typ_args
					return all(testInstance(k, kt) and testInstance(v, vt) for k, v in ins.items())
			return True
	return False

class DictWrapper(dict):
	def __init__(self, obj: dict):
		super().__init__()
		if not isinstance(obj, dict):
			raise ValueError('obj is not a dict')
		for k, v in obj.items():
			self[k] = v

	def __setitem__(self, key: str, val):
		if not isinstance(key, str):
			raise KeyError('Key must be a string')
		super().__setitem__(key, val)

class JSONObject: pass

_BASIC_CLASSES = (type(None), bool, int, float, str)
_CONTAINER_TYPES = (list, dict)

def serialize(obj):
	cls = obj.__class__
	if issubclass(cls, JSONObject):
		fields = cls.get_fields()
		res = {}
		for k, v in vars(obj).items():
			if k in fields:
				if isinstance(v, JSONObject):
					v = v.serialize()
				else:
					v = copy.deepcopy(v)
				res[k] = v
		return res
	raise ValueError('Unknown serializable type {}'.format(type(obj)))

class JSONObject(abc.ABC):
	__fields: dict

	def __init__(self, **kwargs: dict):
		cls = self.__class__
		fields = self.get_fields()
		vself = vars(self)
		for k, (t, v) in fields.items():
			if t in _BASIC_CLASSES:
				pass
			elif t in _CONTAINER_TYPES:
				v = copy.deepcopy(v)
			elif isinstance(v, JSONObject):
				v = v.copy()
			vself[k] = v
		if kwargs is not None:
			for k, v in kwargs.items():
				if k not in fields:
					raise KeyError('Unknown init key received in __init__ of class {0}: {1}'.format(self.__class__, k))
				vself[k] = v
		self._update_hooks = set()

	def __init_subclass__(cls):
		fields = {}
		hints = get_type_hints(cls)
		for name, val in vars(cls).items():
			if not name.startswith('_'):
				typ = hints.get(name, None)
				if issubtype(val, JSONObject):
					typ = val
					val = typ()
				if typ is not None:
					fields[name] = (typ, val)
		cls.__fields = fields

	@classmethod
	def get_fields(cls):
		return cls.__fields

	def copy(self) -> JSONObject:
		cls = self.__class__
		o = cls()
		for k, t in cls.get_fields().items():
			v = getattr(self, k)
			if isinstance(v, (dict, list)):
				v = copy.deepcopy(v)
			elif isinstance(v, JSONObject):
				v = v.copy()
			setattr(o, k, v)
		return o

	def serialize(self) -> dict:
		cls = self.__class__
		fields = cls.get_fields()
		obj = {}
		for k, v in vars(self).items():
			if k in fields:
				if isinstance(v, JSONObject):
					v = v.serialize()
				else:
					v = copy.deepcopy(v)
				obj[k] = v
		return obj

	def __on_update(self):
		for u in self._update_hooks:
			u()

	def update(self, data: dict):
		cls = self.__class__
		fields = cls.get_fields()
		vself = vars(self)
		for k, v in data.items():
			f = fields.get(k, None)
			if f is not None:
				typ, _ = f
				if issubtype(typ, JSONObject):
					kv = v
					v = typ()
					v.update(kv)
					v._update_hooks.add(self.__on_update)
				else:
					if not testInstance(v, typ):
						raise TypeError(
							f'Data type not match, need {str(typ)}, got {str(type(v))}')
				vself[k] = v
			else:
				pass # does it need raise KeyError() ?

	def __setattr__(self, name: str, val):
		cls = self.__class__
		field = cls.get_fields().get(name, None)
		if field is not None:
			assert isinstance(val, field[0])
			old = getattr(self, name)
			if val is old or val == old:
				return
		super().__setattr__(name, val)
		if field is not None:
			self.__on_update()

	def __getitem__(self, key: str):
		if not isinstance(key, str):
			raise KeyError('Key must be a string')
		field = cls.get_fields().get(key, None)
		if field is None:
			raise KeyError()
		return getattr(self, key, field[1])

	def __setitem__(self, key: str, val):
		if not isinstance(key, str):
			raise KeyError('Key must be a string')
		typ, _ = cls.get_fields()[key]
		if not isinstance(val, typ):
			raise TypeError(
				f'Unexpected type {str(type(val))} for key "{key}", expect {str(typ)}')
		setattr(self, key, val)

	def __iter__(self):
		m = {}
		for k in cls.get_fields().keys():
			v = getattr(self, k)
			m[k] = v
		return iter(m)

class JSONStorage(JSONObject):
	def __init__(self, plugin: MCDR.PluginServerInterface,
		file_name: str = 'config.json', *, in_data_folder: bool = True,
		sync_update: bool = False, load_after_init: bool = False,
		kwargs: dict = None):
		assert isinstance(plugin, MCDR.PluginServerInterface)
		super().__init__(**(kwargs if kwargs is not None else {}))
		self.__plugin_server = plugin
		self._file_name = file_name
		self._in_data_folder = in_data_folder
		self._sync_update = sync_update
		self._update_hooks = {self.__on_update}
		if load_after_init:
			self.load()

	def copy(self) -> JSONObject:
		raise RuntimeError('You cannot copy a storage')

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

	def save(self, *, path: str = None):
		if path is None:
			path = self.default_path
		with open(path, 'w') as fd:
			json.dump(self.serialize(), fd, indent=4, ensure_ascii=False)
		self.on_saved()

	def __on_update(self):
		if self._sync_update:
			self.save()

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
		if isinstance(self.minimum_permission_level, dict):
			return self.minimum_permission_level.get(literal, self.__class__.def_level)
		raise RuntimeError('Unknown type of "minimum_permission_level": {}'.format(str(type(self.minimum_permission_level))))

	def has_permission(self, src: MCDR.CommandSource, literal: str):
		return src.has_permission(self.get_permission(literal))

	def get_permission_hint(self) -> MCDR.RText:
		return MCDR.RText(tr('permission.denied', cls.msg_id.to_plain_text()), color=MCDR.RColor.red)

	@property
	def permission_hint(self) -> MCDR.RText:
		return self.get_permission_hint()

	def require_permission(self, node: MCDR.AbstractNode, literal: str) -> MCDR.AbstractNode:
		cls = self.__class__
		return node.requires(lambda src: self.has_permission(src, literal), self.get_permission_hint)

	def literal(self, literal: str):
		return self.require_permission(MCDR.Literal(literal), literal)

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
