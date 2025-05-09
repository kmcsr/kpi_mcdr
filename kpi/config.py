
import abc
import copy
import functools
import json
import os
from enum import Enum
from typing import get_type_hints, overload, Any, Union, Optional, ClassVar, Type, Self

import mcdreforged.api.all as MCDR

from .utils import *
from .utils import tr

__all__ = [
	'memo_wrapper', 'serialize',
	'JSONSerializable', 'DictWrapper', 'JSONObject', 'JSONStorage', 'Config',
]

_UNION_TYPE = type(Union[int, str])

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

def memo_wrapper(fn):
	@functools.wraps(fn)
	def wrapped(obj, /, memo: dict | None = None):
		if memo is None:
			memo = {}
		cache = memo.get(id(obj), None)
		if cache is not None:
			return cache
		res = fn(obj, memo)
		memo[id(obj)] = res
		return res
	return wrapped

_BASIC_CLASSES = (type(None), bool, int, float, str)

@memo_wrapper
def serialize(obj, /, memo):
	cls = obj.__class__
	if cls in _BASIC_CLASSES:
		return obj
	if issubclass(cls, JSONSerializable):
		return obj.serialize(memo)
	if issubclass(cls, (list, tuple)):
		return [serialize(v, memo) for v in obj]
	if issubclass(cls, dict):
		return dict((k, serialize(v, memo)) for k, v in obj.items())
	raise ValueError('Unknown serializable type {}'.format(type(obj)))

def deserialize(hint, obj):
	if hint is None or hint is Any:
		return copy.deepcopy(obj)
	origin = getattr(hint, '__origin__', hint)
	args = getattr(hint, '__args__', ())
	if origin in _BASIC_CLASSES:
		assert_instanceof(obj, origin)
		return copy.deepcopy(obj)
	if isinstance(hint, _UNION_TYPE):
		for t in args:
			try:
				return deserialize(t, obj)
			except (TypeError, ValueError):
				pass
		raise TypeError('Unexpected data {}:{}, expect {}'.format(
			type(obj), obj, ' | '.join(str(t) for t in args)))
	if issubtype(origin, list):
		assert_instanceof(obj, list)
		elem = None if len(args) == 0 else args[0]
		return [deserialize(elem, o) for o in obj]
	if issubtype(origin, dict):
		assert_instanceof(obj, dict)
		kt, vt = (None, None) if len(args) == 0 else args
		return dict((deserialize(kt, k), deserialize(vt, v)) for k, v in obj.items())
	if issubtype(origin, Enum):
		assert_instanceof(obj, str)
		return origin[obj]
	if issubtype(origin, JSONSerializable):
		v = origin()
		v.update(obj)
		return v
	raise TypeError('Unexpected hint {}'.format(hint))

class JSONSerializable(abc.ABC):
	def __init__(self):
		self._update_hooks = set()

	@abc.abstractmethod
	def serialize(self, memo: dict):
		raise NotImplementedError()

	@abc.abstractmethod
	def update(self, data):
		raise NotImplementedError()

	@abc.abstractmethod
	def __deepcopy__(self, memo: dict):
		raise NotImplementedError()

	def on_update(self):
		for u in self._update_hooks:
			u()

	def register(self, parent: 'JSONSerializable'):
		assert_instanceof(parent, JSONSerializable)
		self._update_hooks.add(parent.on_update)

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

DNE = object()

class JSONObject(JSONSerializable):
	__fields: dict

	def __init__(self, **kwargs):
		super().__init__()
		cls = self.__class__
		fields = cls.get_fields()
		vself = vars(self)
		for k, (t, v) in fields.items():
			vself[k] = DNE if v is DNE else copy.deepcopy(v)
		if kwargs is not None:
			for k, v in kwargs.items():
				if k not in fields:
					raise KeyError('Unknown init key received in __init__ of class {0}: {1}'.
						format(cls, k))
				vself[k] = v
		for k in fields:
			if vself[k] is DNE:
				raise ValueError('Field {0}.{1} is not initialized'.format(cls, k))

	def __init_subclass__(cls):
		fields = {}
		# TODO: check typing.Annotated
		hints = get_type_hints(cls, include_extras=True)
		clsv = dict((k, getattr(cls, k)) for k in dir(cls) if not k.startswith('_'))
		for name, typ in hints.items():
			if name.startswith('_'):
				continue
			if getattr(typ, '__origin__', None) is ClassVar:
				continue
			val = clsv.get(name, DNE)
			if issubtype(val, JSONSerializable):
				typ = val
				val = typ()
			elif isinstance(val, (list, tuple)):
				val = copy.deepcopy(val)
			fields[name] = (typ, val)
		for name, val in clsv.items():
			if name in fields:
				continue
			typ = hints.get(name, None)
			if getattr(typ, '__origin__', None) is ClassVar:
				continue
			if issubtype(val, JSONSerializable):
				typ = val
				val = typ()
			elif isinstance(val, (list, tuple)):
				val = copy.deepcopy(val)
			if typ is None:
				continue
			fields[name] = (typ, val)
		cls.__fields = fields

	@classmethod
	def get_fields(cls):
		return cls.__fields

	@memo_wrapper
	def __deepcopy__(self, memo: dict) -> 'JSONObject':
		cls = self.__class__
		o = cls.__new__(cls)
		for k, t in cls.get_fields().items():
			v = getattr(self, k)
			if isinstance(v, (dict, list, JSONSerializable)):
				v = copy.deepcopy(v, memo)
			setattr(o, k, v)
		return o

	@memo_wrapper
	def serialize(self, memo: dict) -> dict:
		cls = self.__class__
		fields = cls.get_fields()
		obj = {}
		for k, v in vars(self).items():
			if k in fields:
				try:
					obj[k] = serialize(v, memo)
				except ValueError as e:
					raise ValueError('Cannot serialize field {}: {}'.format(k, e))
		return obj

	def update(self, data: dict):
		assert_instanceof(data, dict)
		cls = self.__class__
		fields = cls.get_fields()
		vself = vars(self)
		for k, v in data.items():
			f = fields.get(k, None)
			if f is None:
				continue
			typ, _ = f
			vself[k] = deserialize(typ, v)

	def __setattr__(self, name: str, val):
		cls = self.__class__
		field = cls.get_fields().get(name, None)
		if field is not None:
			assert_instanceof(val, field[0])
			old = getattr(self, name)
			if val is old or val == old:
				return
		super().__setattr__(name, val)
		if field is not None:
			self.on_update()

	def __getitem__(self, key: str):
		if not isinstance(key, str):
			raise KeyError('Key must be a string')
		field = self.__class__.get_fields().get(key, None)
		if field is None:
			raise KeyError()
		return getattr(self, key, field[1])

	def __setitem__(self, key: str, val):
		if not isinstance(key, str):
			raise KeyError('Key must be a string')
		typ, _ = self.__class__.get_fields()[key]
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
		kwargs: dict | None = None) -> None:
		assert_instanceof(plugin, MCDR.PluginServerInterface)
		super().__init__(**(kwargs if kwargs is not None else {}))
		self.__plugin_server = plugin
		self._file_name = file_name
		self._in_data_folder = in_data_folder
		self._sync_update = sync_update
		if load_after_init:
			self.load()
		self._update_hooks.add(self.__on_update)

	def copy(self) -> Self:
		raise RuntimeError('You cannot copy a storage')

	@property
	def plugin(self) -> MCDR.PluginServerInterface:
		return self.__plugin_server

	@property
	def file_name(self) -> str:
		return self._file_name

	@file_name.setter
	def file_name(self, file_name: str):
		self._file_name = file_name

	@property
	def default_path(self) -> str:
		return os.path.join(self.plugin.get_data_folder(), self.file_name) \
			if self._in_data_folder else self.file_name

	@property
	def sync_update(self) -> bool:
		return self._sync_update

	@sync_update.setter
	def sync_update(self, val: bool) -> None:
		self._sync_update = val

	def __deepcopy__(self, memo: dict):
		raise RuntimeError('Cannot copy JSONStorage')

	def save(self, *, path: str | None = None) -> None:
		if path is None:
			path = self.default_path
		with open(path, 'w') as fd:
			json.dump(self.serialize(), fd, indent=4, ensure_ascii=False)
		self.on_saved()

	def __on_update(self) -> None:
		if self._sync_update:
			self.save()

	def load(self, *, path: str | None = None, error_on_missing: bool = False) -> None:
		if path is None:
			path = self.default_path
		if os.path.exists(path):
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
		else:
			if error_on_missing:
				raise FileNotFoundError(f'Cannot find storage file: "{path}"')
			log_warn('Cannot find storage file: "{}"'.format(path))
			self.save(path=path)
		self.on_loaded()

	def on_saved(self) -> None:
		pass

	def on_loaded(self) -> None:
		pass

class Config(JSONStorage):
	msg_id: ClassVar[MCDR.RTextBase]
	def_level: ClassVar[int]

	# 0:guest 1:user 2:helper 3:admin 4:owner
	minimum_permission_level: dict[str, int] = {}

	def __init_subclass__(cls, msg_id, def_level: int = 4, **kwargs):
		super().__init_subclass__(**kwargs)
		cls.msg_id = msg_id
		cls.def_level = def_level
		cls._instance = None # type: ignore

	@classmethod
	def instance(cls) -> Self:
		return cls._instance # type: ignore

	@classmethod
	def init_instance(cls, plugin: MCDR.PluginServerInterface, *args,
		sync_update: bool = True, **kwargs) -> Self:
		if cls._instance is not None: # type: ignore
			raise RuntimeError('Cannot init instance twice')
		cls._instance = cls(plugin, *args, sync_update=sync_update, **kwargs)  # type: ignore
		return cls._instance # type: ignore

	@property
	def server(self) -> MCDR.PluginServerInterface:
		return self.plugin

	def get_permission(self, literal: str) -> int:
		if isinstance(self.minimum_permission_level, (dict, JSONObject)):
			try:
				return self.minimum_permission_level[literal]
			except KeyError:
				return self.__class__.def_level
		raise TypeError('Unknown type of "minimum_permission_level": {}'.
			format(str(type(self.minimum_permission_level))))

	def has_permission(self, src: MCDR.CommandSource, literal: str) -> bool:
		return src.has_permission(self.get_permission(literal))

	def get_permission_hint(self) -> MCDR.RText:
		cls = self.__class__
		return MCDR.RText(tr('permission.denied', cls.msg_id.to_plain_text()), color=MCDR.RColor.red)

	@property
	def permission_hint(self) -> MCDR.RText:
		return self.get_permission_hint()

	def require_permission[T: MCDR.AbstractNode](self, node: T, literal: str) -> T:
		return node.requires(lambda src: self.has_permission(src, literal), self.get_permission_hint)

	def literal(self, literal: str) -> MCDR.Literal:
		return self.require_permission(MCDR.Literal(literal), literal)

class Properties:
	def __init__(self, file: str, comment: str = '') -> None:
		self._file = file
		self._data: dict[str, Any] = {}
		self._comment = comment

		if os.path.exists(file):
			self.parse()

	def parse(self) -> None:
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

	def save(self, comment: str | None = None) -> None:
		if comment is None:
			comment = self._comment
		with open(self._file, 'w', encoding='utf8') as fd:
			if len(comment) > 0:
				for l in comment.split('\n'):
					fd.write(f'# {l}\n')
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

	@overload
	def get(self, key: str, default: None = None) -> str | None:
		...

	@overload
	def get[T](self, key: str, default: T) -> str | T:
		...

	def get(self, key: str, default=None):
		if key not in self._data:
			return default
		v = self._data[key]
		if len(v) == 0:
			return default
		return v

	def set(self, key: str, value: Any) -> None:
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
	if len(s) > xlen:
		raise ValueError('xlen to small')
	s = s.rjust(xlen, '0')
	return s
