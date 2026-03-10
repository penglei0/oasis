import unittest
from src.var.settings import OasisSettings, DEFAULT_ROOT_PATH


class TestOasisSettings(unittest.TestCase):
    """Unit tests for OasisSettings dataclass."""

    def test_default_root_path(self):
        settings = OasisSettings()
        self.assertEqual(settings.root_path, '/root/oasis/')

    def test_default_root_path_matches_constant(self):
        settings = OasisSettings()
        self.assertEqual(settings.root_path, DEFAULT_ROOT_PATH)

    def test_custom_root_path(self):
        settings = OasisSettings(root_path='/custom/path/')
        self.assertEqual(settings.root_path, '/custom/path/')

    def test_root_fs_path_default(self):
        settings = OasisSettings()
        self.assertEqual(settings.root_fs_path, '/root/oasis/test/rootfs/')

    def test_root_fs_path_custom(self):
        settings = OasisSettings(root_path='/custom/')
        self.assertEqual(settings.root_fs_path, '/custom/test/rootfs/')

    def test_test_results_path_default(self):
        settings = OasisSettings()
        self.assertEqual(settings.test_results_path, '/root/oasis/test_results/')

    def test_test_results_path_custom(self):
        settings = OasisSettings(root_path='/my/workspace/')
        self.assertEqual(settings.test_results_path, '/my/workspace/test_results/')

    def test_default_root_path_constant(self):
        self.assertEqual(DEFAULT_ROOT_PATH, '/root/oasis/')


class TestGlobalVarBackwardCompat(unittest.TestCase):
    """Ensure the old global_var module still exports the same values."""

    def test_g_root_path_value(self):
        from src.var.global_var import g_root_path
        self.assertEqual(g_root_path, '/root/oasis/')

    def test_g_oasis_root_fs_value(self):
        from src.var.global_var import g_oasis_root_fs
        self.assertEqual(g_oasis_root_fs, '/root/oasis/test/rootfs/')


if __name__ == '__main__':
    unittest.main()
