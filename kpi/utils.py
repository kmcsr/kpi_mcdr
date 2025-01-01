
import enum
import functools
import inspect
import threading
from types import MethodType
from typing import Any

import mcdreforged.api.all as MCDR
from mcdreforged.logging.debug_option import DebugOption

__all__ = [
	'get_server_instance',
	'export_pkg', 'get_origin_func', 'dyn_call', 'issubtype', 'assert_instanceof',
	'LockedData', 'LazyData', 'JobManager', 'ChannelStatus', 'Channel',
	'new_timer',
	'command_assert', 'assert_player', 'assert_console', 'require_player', 'require_console',
	'new_command', 'new_link', 'new_copyable',
	'join_rtext', 'send_message', 'broadcast_message',
	'debug', 'log_info', 'log_warn', 'log_error'
]

def get_server_instance():
	server = MCDR.ServerInterface.get_instance()
	assert server is not None
	return server

def tr(key: str, *args, **kwargs):
	return get_server_instance().rtr(f'kpi.{key}', *args, **kwargs)

def export_pkg(globals_, pkg):
	if hasattr(pkg, '__all__'):
		globals_['__all__'].extend(pkg.__all__)
		for n in pkg.__all__:
			globals_[n] = getattr(pkg, n)

def get_origin_func(fn, /, stop_at=None):
	while (stop_at is None or not stop_at(fn)) and hasattr(fn, '__wrapped__'):
		fn = fn.__wrapped__
	return fn

def dyn_call(fn, *args, src=None, kwargs: dict | None = None):
	if src is None:
		src = get_origin_func(fn)
	sig = inspect.signature(src)
	argspec = inspect.getfullargspec(src)
	if argspec.varargs is None:
		arg_len = len(argspec.args)
		if isinstance(src, MethodType):
			arg_len -= 1
		args = args[:arg_len]
	if kwargs is None:
		kwargs = {}
	try:
		sig.bind(*args, **kwargs)
	except TypeError:
		raise
	return fn(*args, **kwargs)

def issubtype(typ, classes):
	return isinstance(typ, type) and issubclass(typ, classes)

def assert_instanceof(obj, types):
	if not isinstance(obj, types):
		if isinstance(types, (list, tuple)):
			raise TypeError('Unexpected type {}, expect {}'.format(
				type(obj), ' | '.join(str(t) for t in types)))
		raise TypeError('Unexpected type {}, expect {}'.format(type(obj), str(types)))

def __lockeddata_proxy(method: str, expr: bool = False):
	if expr:
		def wrapper(self, *args):
			with self.l:
				v = getattr(self.d, method)(*args)
				return LockedData(v, lock=self.l)
	else:
		def wrapper(self, *args):
			with self.l:
				return getattr(self.d, method)(*args)
	return wrapper

def __lockeddata_proxy_wrapper(exprs: list, methods: list):
	def w(cls: type) -> type:
		for m in exprs:
			setattr(cls, m, __lockeddata_proxy(m, True))
		for m in methods:
			# assert not hasattr(cls, m), f'Method "{m}" already exists'
			setattr(cls, m, __lockeddata_proxy(m))
		return cls
	return w

@__lockeddata_proxy_wrapper([
	'__pos__', '__neg__', '__add__', '__sub__', '__lshift__', '__rshift__', '__xor__',
	'__mul__', '__mod__', '__divmod__', '__floordiv__', '__truediv__', '__pow__',
],
[
	'__radd__', '__rsub__', '__rlshift__', '__rrshift__', '__rxor__',
	'__rmul__', '__rdivmod__', '__rfloordiv__', '__rtruediv__', '__rmod__', '__rpow__',
	'__eq__', '__gt__', '__lt__', '__ge__', '__le__', '__ne__',
	'__abs__', '__ceil__', '__floor__', '__round__', '__invert__', '__trunc__',
	'__str__', '__int__', '__float__', '__bool__',
	'__delitem__', '__getitem__', '__setitem__',
	'__len__', '__iter__',
])
class LockedData:
	def __init__(self, data, lock=None):
		self._data = data
		self._lock = threading.RLock() if lock is None else lock

	@property
	def l(self): # noqa: E743
		return self._lock

	def __enter__(self):
		self._lock.__enter__()
		return self

	def __exit__(self, *args, **kwargs):
		return self._lock.__exit__(*args, **kwargs)

	@property
	def d(self):
		return self._data

	@d.setter
	def d(self, data):
		assert data is not self
		self._data = data

	def copy(self):
		with self._lock:
			return self._data.copy()

def __lazydata_proxy(method: str):
	def wrapper(self, *args):
		return getattr(object.__getattribute__(self, '_LazyData__data'), method)(*args)
	return wrapper

def __lazydata_proxy_wrapper(methods: list):
	def w(cls: type) -> type:
		for m in methods:
			setattr(cls, m, __lazydata_proxy(m))
		return cls
	return w

@__lazydata_proxy_wrapper([
	'__pos__', '__neg__', '__add__', '__sub__', '__lshift__', '__rshift__', '__xor__',
	'__mul__', '__mod__', '__divmod__', '__floordiv__', '__truediv__', '__pow__',
	'__radd__', '__rsub__', '__rlshift__', '__rrshift__', '__rxor__',
	'__rmul__', '__rdivmod__', '__rfloordiv__', '__rtruediv__', '__rmod__', '__rpow__',
	'__eq__', '__gt__', '__lt__', '__ge__', '__le__', '__ne__',
	'__abs__', '__ceil__', '__floor__', '__round__', '__invert__', '__trunc__',
	'__str__', '__int__', '__float__', '__bool__',
	'__delitem__', '__getitem__', '__setitem__',
	'__len__', '__iter__',
])
class LazyData:
	__None = object()

	def __init__(self, generater):
		self.__generater = generater
		self.__data = LazyData.__None

	@staticmethod
	def load(self, *args, **kwargs):
		data = self.__generater(*args, **kwargs)
		self.__data = data

	@staticmethod
	def isloaded(self):
		return self.__issetted

	@property
	def __issetted(self) -> bool:
		return self.__data is not LazyData.__None

	def __repr__(self):
		return '<LazeData {}>'.format(repr(self.__data) if self.__issetted else 'Unsetted')

	def __getattribute__(self, key: str):
		if key.startswith('_LazyData__'):
			return super().__getattribute__(key)
		assert self.__issetted, 'Data was not initialized yet'
		return getattr(self.__data, key)

	def __setattr__(self, key: str, val):
		if key.startswith('_LazyData__'):
			return super().__setattr__(key, val)
		assert self.__issetted, 'Data was not initialized yet'
		return setattr(self.__data, key, val)

	def __delattr__(self, key: str):
		assert self.__issetted, 'Data was not initialized yet'
		return delattr(self.__data, key)

class Job:
	def __init__(self, manager: 'JobManager', call, block: bool, name: str):
		self._manager = manager
		self._call = call
		self.block = block
		self.name = name

	@property
	def manager(self):
		return self._manager

	def __call__(self, *args, **kwargs):
		with self._manager._l:
			if self._manager._l.d is not None and not self.block:
				if len(args) > 0 and isinstance(args[0], MCDR.CommandSource):
					send_message(args[0],
						MCDR.RText('In progress {} now'.format(self._manager._l.d[0]), color=MCDR.RColor.red))
				else:
					log_warn('In progress {0} now, cannot do {1}'.format(self._manager._l.d[0], self.name))
				return None
			debug(f'Pending job "{self.name}"')
			self._manager.begin(self.name, block=True)
		try:
			debug(f'Calling job "{self.name}"')
			return self.call_unsafe(*args, **kwargs)
		finally:
			debug(f'Finish job "{self.name}"')
			self._manager.after()

	def call_unsafe(self, *args, **kwargs):
		return self._call(*args, **kwargs)

	def __str__(self):
		return f'<Job "{self.name}">'

	def __repr__(self):
		return f'<Job "{self.name}" block={self.block} call={repr(self._call)}>'

class JobManager:
	def __init__(self):
		self._l = LockedData(None, threading.Condition(threading.RLock()))

	def check(self):
		with self._l:
			return self._l.d is None

	def _clear(self):
		with self._l:
			self._l.d = None

	def begin(self, job: str, block: bool = False):
		with self._l:
			while True:
				if self._l.d is None or self._l.d is False:
					self._l.d = [job, 1]
					return True
				if not block:
					break
				self._l.l.wait()
		return False

	def prepare(self):
		with self._l:
			assert_instanceof(self._l.d, list)
			self._l.d[1] += 1

	def after(self):
		with self._l:
			if self._l.d is not None:
				self._l.d[1] -= 1
				if self._l.d[1] == 0:
					self._l.d = None
					self._l.l.notify()

	def after_wrapper(self, call):
		@functools.wraps(call)
		def c(*args, **kwargs):
			try:
				return call(*args, **kwargs)
			finally:
				self.after()
		return c

	def new(self, name: str, block=False):
		def w(call):
			return Job(self, call, block, name)
		return w

class ChannelStatus(int, enum.Enum):
	IDLE = 0
	RECVING = 1
	SENDING = 2

class Channel:
	def __init__(self, cond: threading.Condition | None = None):
		self._cond = threading.Condition() if cond is None else cond
		self._status = ChannelStatus.IDLE
		self._value: Any = None

	@property
	def cond(self) -> threading.Condition:
		return self._cond

	@property
	def status(self) -> ChannelStatus:
		return self._status

	def recv(self) -> Any:
		with self.cond:
			while self._status == ChannelStatus.RECVING:
				self.cond.wait()
			if self._status == ChannelStatus.SENDING:
				self._status = ChannelStatus.IDLE
				self.cond.notify_all()
			else:
				self._status = ChannelStatus.RECVING
				self.cond.wait()
			return self._value

	def send(self, value: Any = None):
		with self.cond:
			while self._status == ChannelStatus.SENDING:
				self.cond.wait()
			if self._status == ChannelStatus.RECVING:
				self._status = ChannelStatus.IDLE
				self._value = value
				self.cond.notify_all()
			else:
				self._status = ChannelStatus.SENDING
				self.cond.wait()
				self._value = value

def new_timer(interval, call, args: list | None = None, kwargs: dict | None = None,
	daemon: bool = True, name: str = 'kpi_timer'):
	tm = threading.Timer(interval, call, args=args, kwargs=kwargs)
	tm.name = name
	tm.daemon = daemon
	tm.start()
	return tm

def command_assert(asserter):
	assert callable(asserter)
	def wrapper(cb):
		assert callable(cb)
		def wrapped(source: MCDR.CommandSource, *args, **kwargs):
			res = asserter(source, *args, **kwargs)
			if res is not None and res is not True:
				if res is False:
					res = MCDR.RText('Command assert failed', color=MCDR.RColor.red)
				# TODO: support i18n
				if not isinstance(res, MCDR.RTextBase):
					if isinstance(res, str):
						res = MCDR.RText(res, color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
					else:
						res = MCDR.RText('Command assert failed: {}'.format(res),
							color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
				send_message(source, res)
				return None
			return cb(source, *args, **kwargs)
		return functools.wraps(cb)(wrapped)
	return wrapper

def assert_player(arg):
	msg = MCDR.RText('Only player can execute this command', color=MCDR.RColor.red)
	wrapper = command_assert(lambda source: msg if source.is_player else None)
	if callable(arg):
		return wrapper(arg)
	# TODO: support i18n
	if not isinstance(arg, (str, MCDR.RTextBase)):
		raise TypeError('Assert message must be a string or a RTextBase')
	msg = arg
	return wrapper

def assert_console(arg):
	msg = MCDR.RText('Only console can execute this command', color=MCDR.RColor.red)
	wrapper = command_assert(lambda source: msg if source.is_console else None)
	if callable(arg):
		return wrapper(arg)
	# TODO: support i18n
	if not isinstance(arg, (str, MCDR.RTextBase)):
		raise TypeError('Assert message must be a string or a RTextBase')
	msg = arg
	return wrapper

def require_player(node):
	return node.requires(lambda src: src.is_player,
		lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red))

def require_console(node):
	return node.requires(lambda src: src.is_console,
		lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red))

def new_command(cmd: str, text: str | None = None, *,
	action: MCDR.RAction = MCDR.RAction.suggest_command, **kwargs) -> MCDR.RText:
	if text is None:
		text = cmd
	if 'color' not in kwargs:
		kwargs['color'] = MCDR.RColor.yellow
	elif kwargs['color'] is None:
		kwargs.pop('color')
	if 'styles' not in kwargs:
		kwargs['styles'] = MCDR.RStyle.underlined
	elif kwargs['styles'] is None:
		kwargs.pop('styles')
	return MCDR.RText(text, **kwargs).c(action, cmd).h('Click to execute', cmd)

def new_link(link: str, text: str, *,
	action: MCDR.RAction = MCDR.RAction.open_url, **kwargs) -> MCDR.RText:
	if 'color' not in kwargs:
		kwargs['color'] = MCDR.RColor.dark_blue
	elif kwargs['color'] is None:
		kwargs.pop('color')
	if 'styles' not in kwargs:
		kwargs['styles'] = MCDR.RStyle.underlined
	elif kwargs['styles'] is None:
		kwargs.pop('styles')
	return MCDR.RText(text, **kwargs).c(action, link).h(
		'Click to open' if action is MCDR.RAction.open_url else '', link)

def new_copyable(copyable: str, text: str | None = None, *,
	action: MCDR.RAction = MCDR.RAction.copy_to_clipboard, **kwargs) -> MCDR.RText:
	if text is None:
		text = copyable
	if 'color' not in kwargs:
		kwargs['color'] = MCDR.RColor.gold
	elif kwargs['color'] is None:
		kwargs.pop('color')
	if 'styles' not in kwargs:
		kwargs['styles'] = MCDR.RStyle.underlined
	elif kwargs['styles'] is None:
		kwargs.pop('styles')
	return MCDR.RText(text, **kwargs).c(action, text).h(
		'Click to copy to clipboard' if action is MCDR.RAction.copy_to_clipboard else '', text)

sepTypes = None | str | MCDR.RTextBase

def join_rtext(*args, sep: sepTypes = ' ') -> MCDR.RTextList:
	if len(args) == 0:
		return MCDR.RTextList()
	if len(args) == 1:
		return MCDR.RTextList(args[0])
	if sep is None:
		return MCDR.RTextList(*args)
	t = MCDR.RTextList(args[0])
	for a in args[1:]:
		t.append(sep, a)
	return t

def send_message(source: MCDR.CommandSource, *args,
	sep: sepTypes = ' ', log: bool = False):
	if source is not None:
		t = join_rtext(*args, sep=sep)
		source.reply(t)
		if log and source.is_player:
			source.get_server().logger.info(t)

def broadcast_message(*args, sep: sepTypes = ' '):
	server = get_server_instance()
	if server.is_server_running():
		server.broadcast(join_rtext(*args, sep=sep))
	else:
		log_info(*args, sep=sep)

def debug(*args, sep: sepTypes = ' '):
	get_server_instance().logger.debug(join_rtext(*args, sep=sep),
		option=DebugOption.PLUGIN)

def log_info(*args, sep: sepTypes = ' '):
	get_server_instance().logger.info(join_rtext(*args, sep=sep))

def log_warn(*args, sep: sepTypes = ' '):
	get_server_instance().logger.warn(join_rtext(*args, sep=sep))

def log_error(*args, sep: sepTypes = ' '):
	get_server_instance().logger.error(join_rtext(*args, sep=sep))
