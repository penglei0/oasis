import unittest
from pathlib import Path
import yaml


class TestProtocolCiConfig(unittest.TestCase):

    def test_protocol_ci_bats_iperf_config_is_nested(self):
        repo_root = Path(__file__).resolve().parents[2]
        with open(repo_root / 'test' / 'protocol-ci-test.yaml', 'r', encoding='utf-8') as stream:
            yaml_content = yaml.safe_load(stream)

        test_tools = yaml_content['tests']['test3']['test_tools']
        self.assertEqual(set(test_tools.keys()), {'bats_iperf'})
        self.assertEqual(test_tools['bats_iperf'], {
            'interval': 1,
            'interval_num': 20,
            'client_host': 0,
            'server_host': 1,
        })


if __name__ == '__main__':
    unittest.main()
