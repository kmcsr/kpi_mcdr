
import threading
import functools

import mcdreforged.api.all as MCDR

__all__ = [
	'export_pkg',
	'LockedData', 'JobManager',
	'new_timer', 'new_command', 'join_rtext', 'send_message', 'broadcast_message', 'log_info'
]

def export_pkg(globals_, pkg):
	if hasattr(pkg, '__all__'):
		globals_['__all__'].extend(pkg.__all__)
		for n in pkg.__all__:
			globals_[n] = getattr(pkg, n)

class LockedData:
	def __init__(self, data, lock=None):
		self._data = data
		self._lock = threading.Lock() if lock is None else lock

	@property
	def d(self):
		return self._data

	@d.setter
	def d(self, data):
		self._data = data

	@property
	def l(self):
		return self._lock

	def __enter__(self):
		self._lock.__enter__()
		return self

	def __exit__(self, *args, **kwargs):
		return self._lock.__exit__(*args, **kwargs)

class JobManager: pass

class Job:
	def __init__(self, manager: JobManager, call, block: bool, name: str):
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
					send_message(args[0], MCDR.RText('In progress {} now'.format(self._manager._l.d[0]), color=MCDR.RColor.red))
				else:
					log_info(MCDR.RText('In progress {0} now, cannot do {1}'.format(self._manager._l.d[0], self.name), color=MCDR.RColor.red))
				return None
			self._manager.begin(self.name, block=True)
		try:
			return self.call_unsafe(*args, **kwargs)
		finally:
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

	def ping(self):
		with self._l:
			assert isinstance(self._l.d, list)
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

def new_timer(interval, call, args: list=None, kwargs: dict=None, daemon: bool=True, name: str='kpi_timer'):
	tm = threading.Timer(interval, call, args=args, kwargs=kwargs)
	tm.name = name
	tm.daemon = daemon
	tm.start()
	return tm

def new_command(cmd: str, text=None, **kwargs):
	if text is None:
		text = cmd
	if 'color' not in kwargs:
		kwargs['color'] = MCDR.RColor.yellow
	if 'styles' not in kwargs:
		kwargs['styles'] = MCDR.RStyle.underlined
	return MCDR.RText(text, **kwargs).c(MCDR.RAction.run_command, cmd).h(cmd)

def join_rtext(*args, sep=' '):
	if len(args) == 0:
		return MCDR.RTextList()
	if len(args) == 1:
		return MCDR.RTextList(args[0])
	return MCDR.RTextList(args[0], *(MCDR.RTextList(sep, a) for a in args[1:]))

def send_message(source: MCDR.CommandSource, *args, sep=' ', log=False):
	if source is not None:
		t = join_rtext(*args, sep=sep)
		source.reply(t)
		if log and source.is_player:
			source.get_server().logger.info(t)

def broadcast_message(*args, sep=' '):
	MCDR.ServerInterface.get_instance().broadcast(join_rtext(*args, sep=sep))

def log_info(*args, sep=' '):
	MCDR.ServerInterface.get_instance().logger.info(join_rtext(*args, sep=sep))
