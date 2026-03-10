# mapping oasis workspace to root path
from var.settings import OasisSettings

_default_settings = OasisSettings()
g_root_path = _default_settings.root_path
# after oasis workspace is mapped, the root fs path is at
g_oasis_root_fs = _default_settings.root_fs_path
