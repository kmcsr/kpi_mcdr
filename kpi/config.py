
import os
from typing import Dict

import mcdreforged.api.all as MCDR

__all__ = [
	'Config'
]

def tr(key: str, *args, **kwargs):
	return MCDR.ServerInterface.get_instance().rtr(f'kpi.{key}', *args, **kwargs)

class Config(MCDR.Serializable):
	def __init_subclass__(cls, msg_id, def_level: int = 4, **kwargs):
		super().__init_subclass__(**kwargs)
		cls.msg_id = msg_id
		cls.def_level = def_level
		cls._instance = None

	# 0:guest 1:user 2:helper 3:admin 4:owner
	minimum_permission_level: Dict[str, int] = {}

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self._server = None

	@property
	def server(self):
		return self._server

	def literal(self, literal: str):
		cls = self.__class__
		lvl = self.minimum_permission_level.get(literal, cls.def_level)
		return MCDR.Literal(literal).requires(lambda src: src.has_permission(lvl),
			lambda: MCDR.RText(tr('permission.denied', cls.msg_id.to_plain_text()), color=MCDR.RColor.red))

	def save(self, source: MCDR.CommandSource):
		self._server.save_config_simple(self)
		self.on_saved(source)
		source.reply('Config file saved SUCCESS')

	def on_saved(self, source: MCDR.CommandSource):
		pass

	@classmethod
	def load(cls, source: MCDR.CommandSource, server: MCDR.PluginServerInterface = None):
		oldConfig = cls.instance()
		if server is None:
			assert isinstance(oldConfig, cls)
			server = oldConfig._server
		cls._instance = server.load_config_simple(target_class=cls, echo_in_console=isinstance(source, MCDR.PlayerCommandSource), source_to_reply=source)
		cls._instance._server = server
		cls._instance.after_load(source, oldConfig)

	def after_load(self, source: MCDR.CommandSource, oldConfig):
		pass

	@classmethod
	def instance(cls):
		return cls._instance

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
	return '\\', i

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
