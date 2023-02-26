
import abc

import mcdreforged.api.all as MCDR

from .utils import *
from .config import tr

__all__ = [
	'CommandSet', 'PermCommandSet',
	'Node', 'Literal',
]

class AbstractNode(abc.ABC):
	@abc.abstractproperty
	def base(self) -> MCDR.AbstractNode:
		raise NotImplementedError()

class CommandSet(AbstractNode):
	def __init_subclass__(cls, **kwargs):
		super().__init_subclass__(**kwargs)
		cls._nodes = [n for n in vars(cls).values() if isinstance(n, (Node, CommandSet))]
		cls.instance = None

	def __new__(cls, *args, **kwargs):
		assert cls.instance is None, 'You can only have one command set instance'
		cls.instance = super().__new__(cls)
		return cls.instance

	def __init__(self, node: MCDR.AbstractNode, /, permission=None, permission_hint=None, *, default_help: bool = True):
		if isinstance(node, str):
			node = MCDR.Literal(node)
		elif not isinstance(node, MCDR.AbstractNode):
			raise TypeError('Node must be a AbstractNode or a string')
		if permission is not None:
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
			node.requires(permission, permission_hint)
		cls = self.__class__
		for n in cls._nodes:
			n._owner = self
			node.then(n.base)
		self._node = node
		self._help_node = None
		if cls.help is not CommandSet.help:
			self._help_node = MCDR.Literal('help').runs(self.help)
			self._node.then(self._help_node)
		if cls.default is not CommandSet.default:
			self._node.runs(self.default)
		elif default_help and self._help_node is not None:
			self._node.runs(self.help)

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

	def default(self, source: MCDR.CommandSource):
		raise NotImplementedError()

	def help(self, source: MCDR.CommandSource):
		raise NotImplementedError()

class Node(AbstractNode):
	def __new__(cls, node: MCDR.AbstractNode, /, arg_wrapper=None, args: list = None, *,
		player_only: bool = False, console_only: bool = False):
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
			self.require_console()
		elif player_only:
			self.require_player()
		def wrapper(fn, /):
			assert callable(fn)
			self._fn = fn
			if self.arg_wrapper is None:
				self.node.runs(lambda src, ctx: dyn_call(self._fn, self._owner, src, ctx))
			else:
				self.node.runs(lambda src, ctx: self._fn(self._owner, *(dyn_call(self.arg_wrapper, src, ctx))) )
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

	def requires(self, requirement, failure_message_getter):
		self._base_node.requires(requirement, failure_message_getter)
		return self

	def require_player(self):
		return self.requires(lambda src: src.is_player, lambda: MCDR.RText(tr('command.player_only'), color=MCDR.RColor.red))

	def require_console(self):
		return self.requires(lambda src: src.is_console, lambda: MCDR.RText(tr('command.console_only'), color=MCDR.RColor.red))

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
				self._literals = [literal]
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
