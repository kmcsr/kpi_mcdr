
import abc
import functools
import inspect
import types
import typing
from enum import Enum

import mcdreforged.api.all as MCDR

from .utils import *
from .utils import tr

__all__ = [
	'MiddleWare', 'Requires', 'player_only', 'console_only', 'require_permission',
	'CommandSet', 'PermCommandSet', 'call_with_root',
	'Node', 'Literal',
	'Enumeration', 'Integer', 'Float', 'Text', 'QuotableText', 'GreedyText', 'Boolean',
]

class AbstractNode(abc.ABC):
	@abc.abstractproperty
	def base(self) -> MCDR.AbstractNode:
		raise NotImplementedError()

	@abc.abstractproperty
	def node(self) -> MCDR.AbstractNode:
		raise NotImplementedError()

	def requires(self, requirement, failure_message_getter):
		self.node.requires(requirement, failure_message_getter)
		return self

class MiddleWare(abc.ABC):
	def __new__(cls, *args, **kwargs):
		self = super().__new__(cls)
		self.preinit(*args, **kwargs)
		def wrapper(fn, /):
			self._last = None
			if isinstance(fn, MiddleWare):
				self._last = fn
				fn = self._last.fn
			assert callable(fn)
			self._fn = fn
			return functools.wraps(fn)(self)
		return wrapper

	def preinit(self):
		pass

	@property
	def origin(self):
		return self._fn

	@property
	def last(self):
		return self._last

	def __call__(self, *args, **kwargs):
		return self._fn(*args, **kwargs)

	@abc.abstractmethod
	def trigger(self, node: AbstractNode):
		raise NotImplementedError()

class Requires(MiddleWare):
	def preinit(self, requirement, failure_message_getter, *, at_base: bool = False):
		assert callable(requirement)
		assert callable(failure_message_getter)
		self.requirement = requirement
		self.failure_message_getter = failure_message_getter
		self._at_base = at_base

	def trigger(self, node: AbstractNode):
		(node.base if self._at_base else node.node).requires(self.requirement, self.failure_message_getter)

def player_only(fn):
	return Requires(lambda src: src.is_player, lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red), at_base=True)(fn)

def console_only(fn):
	return Requires(lambda src: src.is_console, lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red), at_base=True)(fn)

def call_with_root(fn):
	"""
	Call the method with root CommandSet instance

	:param fn: the function need to wrap
	:return: wrapped function, set the first argument `self` to `self.rootset`

	Example::
		class RootSet(CommandSet):
			def __init__(self):
				self.number = 123

			@Literal("number")
			class subset:
				@call_with_root
				def default(self, source: MCDR.CommandSource):
					source.reply("The number is {}".format(self.number))

				@Literal("add")
				@call_with_root
				def add(self, source: MCDR.CommandSource, n: int):
					self.number += 1
	"""
	@functools.wraps(fn)
	def wrapped(self, *args, **kwargs):
		return fn(self.rootset, *args, **kwargs)
	wrapped.origin = fn
	return wrapped

def _get_origin_fn(fn):
	assert callable(fn)
	return getattr(fn, 'origin', fn)

def _wrap_permission(permission, permission_hint):
	permc = permission
	permh = permission_hint
	if permission_hint is None:
		permission_hint = lambda: MCDR.RText(tr('permission.denied0'), color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
	elif isinstance(permission_hint, str):
		permission_hint = lambda: MCDR.RText(permh, color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
	elif isinstance(permission_hint, MCDR.RTextBase):
		permission_hint = lambda: permh
	elif not callable(permission_hint):
		raise TypeError('Unexpected permission hint type {}, expect callable, str, or RTextBase'.format(type(permission_hint)))
	if isinstance(permission, int):
		permission = lambda src: src.has_permission(permc)
	elif not callable(permission):
		raise TypeError('Unexpected permission hint type {}, expect callable, or int'.format(type(permission)))
	return permission, permission_hint

def require_permission(permission, /, permission_hint=None):
	permission, permission_hint = _wrap_permission(permission, permission_hint)
	return Requires(permission, permission_hint, at_base=True)

class CommandSet: pass

class CommandSet(AbstractNode):
	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)
		cls._nodes = []
		for n in vars(cls).values():
			if isinstance(n, (Node, CommandSet)):
				cls._nodes.append(n)
			elif isinstance(n, MiddleWare):
				cls._nodes.append(n)
			elif issubtype(n, CommandSet):
				cls._nodes.append(n())
		cls.instance = None

	def __new__(cls, *args, **kwargs):
		assert cls.instance is None, 'You can only have one command set instance'
		cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, node: MCDR.AbstractNode = None, /,
		permission=None, permission_hint=None, *,
		default_help: bool = True):
		cls = self.__class__
		if node is None:
			node = getattr(cls, 'Prefix', None)
		if isinstance(node, str):
			node = MCDR.Literal(node)
		elif not isinstance(node, MCDR.AbstractNode):
			raise TypeError('Node must be a AbstractNode or a string')
		self._parent = None
		for n in cls._nodes:
			if isinstance(n, Node):
				n._owner = self
			elif isinstance(n, MiddleWare):
				mw = n
				while mw is not None:
					mw.trigger(self)
					mw = mw.last
				n = n.origin()
			elif isinstance(n, CommandSet):
				n._parent = self
			else:
				raise TypeError('Unknown type of node {}'.format(type(n)))
			node.then(n.base)
		self._node = node
		self._help_node = None
		if permission is not None:
			permission, permission_hint = _wrap_permission(permission, permission_hint)
			node.requires(permission, permission_hint)
		if cls.help is not CommandSet.help:
			self._help_node = MCDR.Literal('help').runs(self.help)
			self._node.then(self._help_node)
		if cls.default is not CommandSet.default:
			self._node.runs(lambda src, ctx: dyn_call(cls.default, self, src, ctx, src=_get_origin_fn(cls.default)))
		elif default_help and self._help_node is not None:
			self._node.runs(lambda src, ctx: dyn_call(cls.help, self, src, ctx, src=_get_origin_fn(cls.help)))

	@property
	def parent(self) -> CommandSet:
		return self._parent

	@property
	def rootset(self) -> CommandSet:
		p = self
		while p.parent is not None:
			p = p.parent
		return p

	@property
	def base(self) -> MCDR.AbstractNode:
		return self._node

	@property
	def node(self) -> MCDR.AbstractNode:
		return self._node

	@property
	def help_node(self) -> MCDR.AbstractNode:
		return self._help_node

	def register_to(self, server: MCDR.PluginServerInterface):
		assert isinstance(server, MCDR.PluginServerInterface)
		server.register_command(self._node)
		helpmsg = getattr(self.__class__, 'HelpMessage', None)
		if helpmsg is not None and isinstance(self.base, MCDR.Literal):
			for l in self.base.literals:
				server.register_help_message(l, helpmsg)

	def default(self, source: MCDR.CommandSource):
		raise NotImplementedError()

	def help(self, source: MCDR.CommandSource):
		raise NotImplementedError()

class Node(AbstractNode):
	def __new__(cls, node: MCDR.AbstractNode, /, arg_wrapper=None, args: list = None, *,
		player_only: bool = False, console_only: bool = False,
		requires: list[tuple] = None):
		if not isinstance(node, MCDR.AbstractNode):
			raise TypeError('Node must be an instance of AbstractNode')
		if arg_wrapper is not None and not callable(arg_wrapper):
			raise TypeError('Argument wrapper must be a callable')
		base = node
		if args is not None:
			for n in args:
				if not isinstance(n, MCDR.AbstractNode):
					raise TypeError('Extra nodes must be instances of AbstractNode')
				node.then(n)
				node = n
		self = super().__new__(cls)
		self._base_node = base
		self._node = node
		self._arg_wrapper = arg_wrapper
		self._owner = None
		if console_only:
			self.base.requires(lambda src: src.is_console, lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red))
		elif player_only:
			self.base.requires(lambda src: src.is_player, lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red))
		def wrapper(fn, /):
			if isinstance(fn, MiddleWare):
				origin = fn.origin
			elif issubtype(fn, CommandSet):
				return fn(node)
			else:
				assert callable(fn)
				origin = _get_origin_fn(fn)
			if self.arg_wrapper is None:
				if args is None:
					argspec = inspect.getfullargspec(origin)
					hints = typing.get_type_hints(origin)
					if not issubclass(hints[argspec.args[1]], MCDR.CommandSource):
						raise TypeError('The first argument must be CommandSource')
					namelist = []
					# TODO: support default values
					for name in argspec.args[2:]:
						hint = hints[name]
						typ = hint
						ags = tuple()
						if hasattr(hint, '__origin__'):
							typ = hint.__origin__
							ags = hint.__args__
							if isinstance(ags[0], str):
								name, ags = ags[0], ags[1:]
						if name in namelist:
							raise KeyError('Duplicate name "{}"'.format(name))
						namelist.append(name)
						n: MCDR.ArgumentNode = None
						if issubclass(typ, Enum):
							n = MCDR.Enumeration(name, typ)
						elif issubclass(typ, int):
							n = MCDR.Integer(name)
							if len(ags) == 2:
								n.at_max(ags[1])
							if len(ags) > 0 and ags[0] is not None:
								n.at_min(ags[0])
						elif issubclass(typ, float):
							n = MCDR.Float(name)
							if len(ags) == 2:
								n.at_max(ags[1])
							if len(ags) > 0 and ags[0] is not None:
								n.at_min(ags[0])
						elif issubclass(typ, bool):
							n = MCDR.Boolean(name)
						elif issubclass(typ, QuotableText):
							n = MCDR.QuotableText(name)
						elif issubclass(typ, GreedyText):
							n = MCDR.GreedyText(name)
						elif issubclass(typ, (Text, str)):
							n = MCDR.Text(name)
						else:
							raise TypeError('Unsupported type hint {}, {}'.format(hint, typ))
						self._node.then(n)
						self._node = n
					self.node.runs(lambda src, ctx: fn(self.owner, src, *(ctx[n] for n in namelist)))
				else:
					self.node.runs(lambda src, ctx: dyn_call(fn, self.owner, src, ctx, src=origin))
			else:
				self.node.runs(lambda src, ctx: fn(self.owner, *(dyn_call(self.arg_wrapper, src, ctx))) )
			if requires is not None:
				for req, msg in requires:
					self.node.requires(req, msg)
			if isinstance(fn, MiddleWare):
				mw = fn
				while mw is not None:
					mw.trigger(self)
					mw = mw.last
			return self
		return wrapper

	@property
	def base(self) -> MCDR.AbstractNode:
		return self._base_node

	@property
	def node(self) -> MCDR.AbstractNode:
		return self._node

	@property
	def arg_wrapper(self):
		return self._arg_wrapper

	@property
	def owner(self) -> CommandSet:
		return self._owner

	def __call__(self, *args, **kwargs):
		return self._fn(*args, **kwargs)

class Literal(Node):
	def __new__(cls, literal: str, /, *args, **kwargs):
		if isinstance(literal, (list, tuple)):
			if len(literal) == 0:
				raise TypeError('Literal list must have at least one element')
			for l in literal:
				if not isinstance(l, str):
					raise TypeError('Literal list elements must be str')
		elif not isinstance(literal, str):
			raise TypeError('Literal must be str or list of str')
		wrapper0 = super().__new__(cls, MCDR.Literal(literal), *args, **kwargs)
		def wrapper(*args, **kwargs):
			self = wrapper0(*args, **kwargs)
			if isinstance(literal, str):
				self._literals = (literal, )
				self._literal = literal
			else:
				self._literals = tuple(literal)
				self._literal = literal[0]
			return self
		return wrapper

	@property
	def literal(self) -> str:
		return self._literal

	@property
	def literals(self) -> tuple[str]:
		return self._literals

class PermCommandSet(CommandSet, abc.ABC):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		for node in vars(self.__class__).values():
			if isinstance(node, Literal):
				node.requires(
					(lambda literal: lambda src: self.has_permission(src, literal))(node.literal), self.get_perm_failure_message)

	@abc.abstractmethod
	def has_permission(self, src: MCDR.CommandSource, literal: str) -> int:
		raise NotImplementedError()

	def get_perm_failure_message(self, src: MCDR.CommandSource, literal: str) -> str:
		return MCDR.RText(tr('permission.denied0'), color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)

class Enumeration:
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 1:
			raise ValueError(
				'Unexpected subscript argument, expect at most 2 but got {}'.format(len(args)))
		i = 1 if isinstance(args[0], str) else 0
		if not issubclass(args[i], Enum):
			raise ValueError('Unexpected argument {}, expect an enum type'.format(args[i]))
		return types.GenericAlias(args[i], args[:-1])

class Integer(int):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 2:
			raise ValueError(
				'Unexpected subscript argument, expect at most 3 but got {}'.format(len(args)))
		i = 1 if isinstance(args[0], str) else 0
		if len(args) == i + 2:
			if args[i] is not None and not isinstance(args[i], int):
				raise TypeError('Unexpected type {} at 1st argument, expect int or None'.format(type(args[i])))
			if not isinstance(args[i + 1], int):
				raise TypeError('Unexpected type {} at 2nd argument, expect int'.format(type(args[i + 1])))
			if args[i] is not None and args[i] > args[i + 1]:
				raise ValueError('Maximum value must greather than minimum value')
		elif not isinstance(args[i], int):
			raise TypeError('Unexpected type {}, expect int'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class Float(float):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 3:
			raise ValueError(
				'Unexpected subscript argument, expect at most 3 but got {}'.format(len(args)))
		i = 1 if isinstance(args[0], str) else 0
		if len(args) == i + 2:
			if args[i] is not None and not isinstance(args[i], (float, int)):
				raise TypeError('Unexpected type {} at 1st argument, expect float, int, or None'.format(type(args[i])))
			if not isinstance(args[i + 1], (float, int)):
				raise TypeError('Unexpected type {} at 2nd argument, expect float, or int'.format(type(args[i + 1])))
			if args[i] is not None and args[i] > args[i + 1]:
				raise ValueError('Maximum value must greather than minimum value')
		elif not isinstance(args[i], (float, int)):
			raise TypeError('Unexpected type {}, expect float or int'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class Text(str):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 1:
			raise ValueError(
				'Unexpected subscript argument, expect at most 1 but got {}'.format(len(args)))
		if not isinstance(args[0], str):
			raise TypeError('Unexpected type {} for name, expect str'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class QuotableText(str):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 1:
			raise ValueError(
				'Unexpected subscript argument, expect at most 1 but got {}'.format(len(args)))
		if not isinstance(args[0], str):
			raise TypeError('Unexpected type {} for name, expect str'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class GreedyText(str):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 1:
			raise ValueError(
				'Unexpected subscript argument, expect at most 1 but got {}'.format(len(args)))
		if not isinstance(args[0], str):
			raise TypeError('Unexpected type {} for name, expect str'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class Boolean:
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 1:
			raise ValueError(
				'Unexpected subscript argument, expect at most 1 but got {}'.format(len(args)))
		if not isinstance(args[0], str):
			raise TypeError('Unexpected type {} for name, expect str'.format(type(args[i])))
		return types.GenericAlias(bool, args)

