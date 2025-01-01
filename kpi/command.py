
import abc
import functools
import inspect
import types
import typing
from typing import Any, Union, Optional
from enum import Enum

import mcdreforged.api.all as MCDR

from .utils import *
from .utils import tr

__all__ = [
	'MiddleWare', 'Requires', 'player_only', 'console_only', 'require_permission',
	'CommandSet', 'PermCommandSet', 'call_with_root',
	'Node', 'Literal',
	'Integer', 'Float', 'Text', 'QuotableText', 'GreedyText',
	'Require',
]

class AbstractNode(abc.ABC):
	@abc.abstractproperty
	def node(self) -> MCDR.AbstractNode:
		raise NotImplementedError()

	def requires(self, requirement, /, failure_message_getter=None, *,
		at_base: bool = False):
		self.node.requires(requirement, failure_message_getter)
		return self

class MiddleWare(abc.ABC):
	def __new__(cls, *args, **kwargs):
		self = super().__new__(cls)
		self.__init__(*args, **kwargs)
		def wrapper(fn, /):
			self._last = None
			if isinstance(fn, MiddleWare):
				self._last = fn
				fn = fn.__wrapped__
			assert callable(fn)
			self._fn = fn
			return functools.wraps(fn)(self)
		return wrapper

	@property
	def __wrapped__(self):
		return self._fn

	@__wrapped__.setter
	def __wrapped__(self, wrapped):
		pass # no action

	@property
	def last(self):
		return self._last

	def __call__(self, *args, **kwargs):
		return self._fn(*args, **kwargs)

	@abc.abstractmethod
	def trigger(self, node: AbstractNode):
		raise NotImplementedError()

class Requires(MiddleWare):
	def __init__(self, requirement, failure_message_getter, *, at_base: bool = False):
		assert callable(requirement)
		assert callable(failure_message_getter)
		self.requirement = requirement
		self.failure_message_getter = failure_message_getter
		self._at_base = at_base

	def trigger(self, node: AbstractNode):
		node.requires(self.requirement, self.failure_message_getter, at_base=self._at_base)

def player_only(fn):
	return Requires(lambda src: src.is_player,
		lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red),
	at_base=True)(fn)

def console_only(fn):
	return Requires(lambda src: src.is_console,
		lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red),
	at_base=True)(fn)

def call_with_root(fn):
	"""
	Call the method with root CommandSet instance.
	If you are using mypy, you probably need disable the error code "misc".

	:param fn: the function need to wrap
	:return: wrapped function, set the first argument `self` to `self.rootset`

	Example::
		class RootSet(CommandSet):
			def __init__(self):
				self.number = 123

			@Literal("number")
			class subset:
				@call_with_root
				def default(self: RootSet, source: MCDR.CommandSource):
					source.reply("The number is {}".format(self.number))

				@Literal("add")
				@call_with_root
				def add(self: RootSet, source: MCDR.CommandSource, n: int):
					self.number += 1
	"""
	@functools.wraps(fn)
	def wrapped(self, *args, **kwargs):
		return fn(self.rootset, *args, **kwargs)
	return wrapped

def _wrap_permission(permission, permission_hint):
	permc = permission
	permh = permission_hint
	if permission_hint is None:
		def permission_hint():
			return MCDR.RText(tr('permission.denied0'), color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
	elif isinstance(permission_hint, str):
		def permission_hint():
			return MCDR.RText(permh, color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)
	elif isinstance(permission_hint, MCDR.RTextBase):
		def permission_hint(): return permh
	elif not callable(permission_hint):
		raise TypeError('Unexpected permission hint type {}, expect callable, str, or RTextBase'.
			format(type(permission_hint)))
	if isinstance(permission, int):
		def permission(src): return src.has_permission(permc)
	elif not callable(permission):
		raise TypeError('Unexpected permission hint type {}, expect callable, or int'.
			format(type(permission)))
	return permission, permission_hint

def require_permission(permission, /, permission_hint=None):
	permission, permission_hint = _wrap_permission(permission, permission_hint)
	return Requires(permission, permission_hint, at_base=True)

class CommandSet(AbstractNode):
	_nodes: list[Union['Node', 'CommandSet', MiddleWare]]

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
		if cls.instance is not None:
			raise RuntimeError('You can only have one command set instance')
		cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, node: MCDR.AbstractNode | None = None, /,
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
			if isinstance(n, MiddleWare):
				mw = n
				while mw is not None:
					mw.trigger(self)
					mw = mw.last
				n = n()
			if isinstance(n, Node):
				n._owner = self
			elif isinstance(n, CommandSet):
				n._parent = self
			else:
				raise TypeError('Unknown type of node {}'.format(type(n)))
			node.then(n.node)
		self._node = node
		self._help_node = None
		if permission is not None:
			permission, permission_hint = _wrap_permission(permission, permission_hint)
			node.requires(permission, permission_hint)
		if cls.help is not CommandSet.help:
			self._help_node = MCDR.Literal('help').runs(self.help)
			self._node.then(self._help_node)
		if cls.default is not CommandSet.default:
			self._node.runs(lambda src, ctx: dyn_call(cls.default, self, src, ctx))
		elif default_help and self._help_node is not None:
			self._node.runs(lambda src, ctx: dyn_call(cls.help, self, src, ctx))

	@property
	def parent(self) -> Optional['CommandSet']:
		return self._parent

	@property
	def rootset(self) -> 'CommandSet':
		p = self
		while p.parent is not None:
			p = p.parent
		return p

	@property
	def node(self) -> MCDR.AbstractNode:
		return self._node

	@property
	def help_node(self) -> MCDR.AbstractNode | None:
		return self._help_node

	def register_to(self, server: MCDR.PluginServerInterface):
		assert_instanceof(server, MCDR.PluginServerInterface)
		assert isinstance(self._node, MCDR.Literal)
		server.register_command(self._node)
		helpmsg = getattr(self.__class__, 'HelpMessage', None)
		if helpmsg is not None and isinstance(self.node, MCDR.Literal):
			for n in self.node.literals:
				server.register_help_message(n, helpmsg)

	def default(self, source: MCDR.CommandSource):
		raise NotImplementedError()

	def help(self, source: MCDR.CommandSource):
		raise NotImplementedError()

def _defarg_wrapper(fn, self, namelist, defs, i):
	def wrapped(src, ctx):
		fn(self.owner, src, *(ctx[n] for n in namelist[:i]), *defs[len(defs) + i - len(namelist):])
	return wrapped

def _get_arg_generator(hint):
	if hasattr(hint, '__origin__'):
		typ = hint.__origin__
		ags = hint.__args__
	else:
		typ = hint
		ags = ()
	if issubclass(typ, Enum):
		return lambda name: MCDR.Enumeration(name, typ)
	if issubclass(typ, bool): # bool must be checked before int, since issubclass(bool, int) is True
		return MCDR.Boolean
	if issubclass(typ, int):
		def g(name):
			n = MCDR.Integer(name)
			if len(ags) == 2:
				n.at_max(ags[1])
			if len(ags) > 0 and ags[0] is not None:
				n.at_min(ags[0])
			return n
		return g
	if issubclass(typ, float):
		def g(name):
			n = MCDR.Float(name)
			if len(ags) == 2:
				n.at_max(ags[1])
			if len(ags) > 0 and ags[0] is not None:
				n.at_min(ags[0])
			return n
		return g
	if issubclass(typ, QuotableText):
		return MCDR.QuotableText
	if issubclass(typ, GreedyText):
		return MCDR.GreedyText
	if issubclass(typ, (Text, str)):
		return MCDR.Text
	raise TypeError('Unsupported type hint {}, {}'.format(hint, typ))

class Node(AbstractNode):
	_node: MCDR.AbstractNode
	_arg_wrapper: typing.Callable
	_owner: None | CommandSet
	_entries: list[MCDR.AbstractNode]

	def __new__(cls, node: MCDR.AbstractNode, /, arg_wrapper=None, args: list | None = None, *,
		player_only: bool = False, console_only: bool = False,
		requires: list[tuple] | None = None):
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
		self._node = base
		self._arg_wrapper = arg_wrapper
		self._owner = None
		if console_only:
			self.node.requires(lambda src: src.is_console,
				lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red))
		elif player_only:
			self.node.requires(lambda src: src.is_player,
				lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red))
		_none_args = args is None
		def wrapper(fn, /):
			if issubtype(fn, CommandSet):
				return fn(node)
			if not isinstance(fn, MiddleWare):
				assert callable(fn)
			origin = get_origin_func(fn)
			if self.arg_wrapper is None:
				if _none_args:
					argspec = inspect.getfullargspec(origin)
					hints = typing.get_type_hints(origin)
					if not issubclass(hints[argspec.args[1]], MCDR.CommandSource):
						raise TypeError('The first argument must be CommandSource')
					args = argspec.args[2:]
					self._entries = []
					namelist = []
					defs = () if argspec.defaults is None else argspec.defaults
					if len(defs) > len(args):
						defs = defs[len(defs) - len(args):]
					nodes = [([], self.node)]
					for i, name in enumerate(args):
						hint = hints[name]
						if name in namelist:
							raise KeyError('Duplicate name "{}"'.format(name))
						namelist.append(name)
						if len(defs) + i >= len(args): # have default value
							for _, n in nodes:
								n.runs(_defarg_wrapper(fn, self, namelist, defs, i))
								self._entries.append(n)
						r = Require.get_require(hint)
						if r:
							hint = hint.__origin__
						if isinstance(hint, types.UnionType):
							nodes0 = nodes.copy()
							nodes.clear()
							for t in hint.__args__:
								if t is None:
									for _, n in nodes0:
										nodes.append(n)
								else:
									g = _get_arg_generator(t)
									for _, m in nodes0:
										n = g(name)
										m.then(n)
										nodes.append(n)
						else:
							g = _get_arg_generator(hint)
							for i, (_, m) in enumerate(nodes):
								n = g(name)
								m.then(n)
								nodes[i] = n
					for n in nodes:
						if n not in self._entries:
							n.runs(lambda src, ctx: fn(self.owner, src, *(ctx[n] for n in namelist)))
							self._entries.append(n)
				else:
					self._entries = [node]
					node.runs(lambda src, ctx: dyn_call(fn, self.owner, src, ctx, src=origin))
			else:
				self._entries = [node]
				node.runs(lambda src, ctx: fn(self.owner, *(dyn_call(self.arg_wrapper, src, ctx))) )
			if requires is not None:
				for req, msg in requires:
					self.node.requires(req, msg)
			if isinstance(fn, MiddleWare):
				mw = fn
				while True:
					mw.trigger(self)
					if mw.last is None:
						self._fn = mw.__wrapped__
						break
					mw = mw.last
			else:
				self._fn = fn
			return self
		return wrapper

	@property
	def node(self) -> MCDR.AbstractNode:
		return self._node

	@property
	def entries(self) -> list[MCDR.AbstractNode]:
		return self._entries.copy()

	def __iter__(self):
		return iter(self._entries)

	def requires(self, requirement, /, failure_message_getter=None, *, at_base: bool = False):
		if at_base:
			self.node.requires(requirement, failure_message_getter)
		else:
			for e in self.entries:
				e.requires(requirement, failure_message_getter)
		return self

	@property
	def arg_wrapper(self):
		return self._arg_wrapper

	@property
	def owner(self) -> Optional[CommandSet]:
		return self._owner

	def __call__(self, *args, **kwargs):
		return self._fn(*args, **kwargs)

class Literal(Node):
	_literals: tuple[str]
	_literal: str
	def __new__(cls, literal: str | list[str], /, *args, **kwargs):
		if isinstance(literal, (list, tuple)):
			if len(literal) == 0:
				raise TypeError('Literal list must have at least one element')
			for n in literal:
				if not isinstance(n, str):
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
					(lambda literal: lambda src: self.has_permission(src, literal))(node.literal),
						self.get_perm_failure_message)

	@abc.abstractmethod
	def has_permission(self, src: MCDR.CommandSource, literal: str) -> int:
		raise NotImplementedError()

	def get_perm_failure_message(self, src: MCDR.CommandSource, literal: str) -> MCDR.RTextBase:
		return MCDR.RText(tr('permission.denied0'), color=MCDR.RColor.red, styles=MCDR.RStyle.underlined)

class Integer(int):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 2:
			raise ValueError(
				'Unexpected subscript argument, expect at most 2 but got {}'.format(len(args)))
		if len(args) == 2:
			if args[0] is not None and not isinstance(args[0], int):
				raise TypeError('Unexpected type {} at 1st argument, expect int or None'.format(type(args[0])))
			if not isinstance(args[1], int):
				raise TypeError('Unexpected type {} at 2nd argument, expect int'.format(type(args[1])))
			if args[0] is not None and args[0] > args[1]:
				raise ValueError('Maximum value must greather than minimum value')
		elif not isinstance(args[0], int):
			raise TypeError('Unexpected type {}, expect int'.format(type(args[i])))
		return types.GenericAlias(cls, args)

class Float(float):
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)):
			args = (args, )
		if len(args) > 2:
			raise ValueError(
				'Unexpected subscript argument, expect at most 2 but got {}'.format(len(args)))
		if len(args) == 2:
			if args[i] is not None and not isinstance(args[0], (float, int)):
				raise TypeError('Unexpected type {} at 1st argument, expect float, int, or None'.
					format(type(args[0])))
			if not isinstance(args[1], (float, int)):
				raise TypeError('Unexpected type {} at 2nd argument, expect float, or int'.
					format(type(args[1])))
			if args[0] is not None and args[0] > args[1]:
				raise ValueError('Maximum value must greather than minimum value')
		elif not isinstance(args[0], (float, int)):
			raise TypeError('Unexpected type {}, expect float or int'.format(type(args[0])))
		return types.GenericAlias(cls, args)

class Text(str): pass

class QuotableText(str): pass

class GreedyText(str): pass

class Require:
	def __class_getitem__(cls, args):
		if not isinstance(args, (list, tuple)) or len(args) != 2:
			raise ValueError('Unexpected number of subscript arguments, expect two')
		name, typ = args
		if not isinstance(name, str) or type(typ) is not type:
			raise ValueError('Unexpected type of subscript arguments, expect [str, type]')
		return types.GenericAlias(Optional[typ], (cls, name))

	@classmethod
	def get_require(cls, typ: Any) -> str | None:
		if (not hasattr(typ, '__origin__') or not is_optional(typ.__origin__) or
				not isinstance(typ.__args__, tuple) or len(typ.__args__) != 2 or typ.__args__[0] is not cls):
			return None
		return typ.__args__[1]

def is_optional(typ: Any) -> bool:
	return typ.__origin__ is Union and len(typ.__args__) == 2 and types.NoneType in typ.__args__
