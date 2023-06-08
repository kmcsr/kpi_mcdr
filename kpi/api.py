
import re
from typing import Callable

import mcdreforged.api.all as MCDR
from mcdreforged.plugin.plugin_event import MCDRPluginEvents

from .utils import *

__all__ = [
	'watch_info'
]

listeners: list[Callable] = []

def on_info(server: MCDR.ServerInterface, info: MCDR.Info):
	global listeners
	for l in listeners:
		l(server, info)

def watch_info(server: MCDR.PluginServerInterface, callback: Callable,
	filterc: str | Callable | re.Pattern | None = None, *,
	once: bool = False, priority: int | None = None):
	assert callable(callback)
	if filterc is not None and not callable(filterc):
		assert_instanceof(filterc, (re.Pattern, str))

	flag = True
	def canceler():
		nonlocal flag
		flag = False

	def listener(server: MCDR.ServerInterface, info: MCDR.Info):
		nonlocal filterc, callback, flag
		if flag and info.content is not None:
			if isinstance(filterc, re.Pattern):
				if filterc.fullmatch(info.content) is None:
					return
			elif isinstance(filterc, str):
				if filterc not in info.content:
					return
			elif callable(filterc):
				if not filterc(info):
					return
			if once:
				flag = False
			dyn_call(callback, server, info)

	global listeners
	listeners.append(listener)

	# for some reason, it cannot work after load
	# server.register_event_listener(MCDRPluginEvents.GENERAL_INFO, listener, priority)

	return canceler
