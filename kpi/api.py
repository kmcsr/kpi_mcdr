
import re

import mcdreforged.api.all as MCDR
from mcdreforged.plugin.plugin_event import MCDRPluginEvents

from .utils import *

__all__ = [
	'watch_info'
]

def watch_info(server: MCDR.PluginServerInterface,
	callback, filterc=None, *, once: bool = False, priority: int | None = None):
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
			callback(server, info)

	server.register_event_listener(MCDRPluginEvents.GENERAL_INFO, listener, priority)

	return canceler
