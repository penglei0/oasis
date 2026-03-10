"""
OasisSettings encapsulates the global configuration paths
so that callers receive them through dependency injection
instead of importing the module-level constants directly.
"""
from dataclasses import dataclass, field

# Default root path: where oasis workspace is mounted inside nested containernet
DEFAULT_ROOT_PATH = '/root/oasis/'


@dataclass
class OasisSettings:
    """Holds the root-path settings that used to live as bare globals."""
    root_path: str = field(default=DEFAULT_ROOT_PATH)

    @property
    def root_fs_path(self) -> str:
        return f"{self.root_path}test/rootfs/"

    @property
    def test_results_path(self) -> str:
        return f"{self.root_path}test_results/"
