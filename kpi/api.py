
import re

import mcdreforged.api.all as MCDR
from mcdreforged.plugin.plugin_event import MCDRPluginEvents

__all__ = [
	'watch_info'
]

def watch_info(server: MCDR.PluginServerInterface, callback, filterc=None, *, once: bool = False, priority: int = None):
	assert callable(callback)
	if filterc is None:
		filterc = lambda info: True
	elif isinstance(filterc, re.Pattern):
		pat = filterc
		filterc = lambda info: pat.fullmatch(info.content) is not None
	elif isinstance(filterc, str):
		pat = filterc
		filterc = lambda info: pat in info.content
	assert callable(filterc), f'Unexpect filter type {type(filterc)}'

	flag = True
	def _canceler():
		nonlocal flag
		flag = False
	def _listener(server: MCDR.ServerInterface, info: MCDR.Info):
		nonlocal filterc, callback, flag
		if flag and filterc(info):
			if once:
				flag = False
			callback(server, info)

	server.register_event_listener(MCDRPluginEvents.GENERAL_INFO, _listener, priority)

	return _canceler
