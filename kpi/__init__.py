
import mcdreforged.api.all as MCDR

from . import config
from .config import *
from . import utils
from .utils import *
from . import api
from .api import *

__all__ = [
	'config', 'utils',
]

__all__.extend(config.__all__)
__all__.extend(utils.__all__)
__all__.extend(api.__all__)

def on_info(server: MCDR.ServerInterface, info: MCDR.Info):
	api.on_info(server, info)
