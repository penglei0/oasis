import tempfile
import unittest
import logging
import os
from unittest.mock import patch

from src.tools.log_setup import configure_run_logging


class TestConfigureRunLogging(unittest.TestCase):

    def test_info_level_with_append_mode(self):
        with tempfile.TemporaryDirectory() as temp_root:
            with patch('src.tools.log_setup.logging.basicConfig') as mock_basic_config:
                configure_run_logging(False, temp_root)

            self.assertTrue(mock_basic_config.called)
            kwargs = mock_basic_config.call_args.kwargs
            self.assertEqual(kwargs['level'], logging.INFO)
            self.assertTrue(kwargs['force'])
            handlers = kwargs['handlers']
            file_handler = next(
                (handler for handler in handlers if handler.__class__.__name__ == 'FileHandler'),
                None
            )
            self.assertIsNotNone(file_handler)
            self.assertEqual(file_handler.mode, 'a')
            self.assertTrue(
                file_handler.baseFilename.endswith(
                    os.path.join('test_results', 'oasis.log')
                )
            )

    def test_configure_run_logging_with_debug_level(self):
        with tempfile.TemporaryDirectory() as temp_root:
            with patch('src.tools.log_setup.logging.basicConfig') as mock_basic_config:
                configure_run_logging(True, temp_root)

            kwargs = mock_basic_config.call_args.kwargs
            self.assertEqual(kwargs['level'], logging.DEBUG)
            handlers = kwargs['handlers']
            file_handler = next(
                (handler for handler in handlers if handler.__class__.__name__ == 'FileHandler'),
                None
            )
            self.assertIsNotNone(file_handler)
            self.assertEqual(file_handler.mode, 'a')


if __name__ == '__main__':
    unittest.main()
