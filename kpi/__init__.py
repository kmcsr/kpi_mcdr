
import mcdreforged.api.all as MCDR

from . import config
from . import utils
from . import api

__all__ = [
	'config', 'utils',
]

utils.export_pkg(globals(), config)
utils.export_pkg(globals(), utils)
utils.export_pkg(globals(), api)

def on_info(server: MCDR.ServerInterface, info: MCDR.Info):
	pass
	# api.on_info(server, info)
