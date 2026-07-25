import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config_loader import AppConfig, load_config, parse_config

VALID_CONFIG = {
    "debug_mode": True,
    "wait_time": 0,
    "timeout": 10,
    "user_agent": "Mozilla/5.0",
    "storage_path": "downloads",
    "database_file": "books.sqlite",
    "logstamp_format": "%(message)s",
    "target_formats": ["epub"],
    "proxy": {"enabled": False, "proxies": []},
}


class ConfigLoaderTestCase(unittest.TestCase):
    def test_parse_config_returns_typed_config_with_defaults(self):
        config = parse_config(VALID_CONFIG)

        self.assertIsInstance(config, AppConfig)
        self.assertFalse(config.verify_ssl)
        self.assertFalse(config.allow_redirects)
        self.assertEqual(config.download_retries, 3)
        self.assertEqual(config.retry_backoff, 2)
        self.assertEqual(config.server_evaluation_timeout, config.timeout)
        self.assertEqual(config.max_consecutive_download_failures, 10)

    def test_parse_config_accepts_server_evaluation_timeout(self):
        config = parse_config(dict(VALID_CONFIG, server_evaluation_timeout=15))

        self.assertEqual(config.server_evaluation_timeout, 15)

    def test_parse_config_accepts_max_consecutive_download_failures(self):
        config = parse_config(dict(VALID_CONFIG, max_consecutive_download_failures=4))

        self.assertEqual(config.max_consecutive_download_failures, 4)

    def test_parse_config_rejects_bool_timeout(self):
        bad_config = dict(VALID_CONFIG, timeout=True)

        with self.assertRaises(ValueError):
            parse_config(bad_config)

    def test_parse_config_rejects_bool_server_evaluation_timeout(self):
        bad_config = dict(VALID_CONFIG, server_evaluation_timeout=True)

        with self.assertRaises(ValueError):
            parse_config(bad_config)

    def test_parse_config_rejects_bool_max_consecutive_download_failures(self):
        bad_config = dict(VALID_CONFIG, max_consecutive_download_failures=True)

        with self.assertRaises(ValueError):
            parse_config(bad_config)

    def test_load_config_reads_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.yaml"
            config_file.write_text(
                """
debug_mode: true
wait_time: 0
timeout: 10
server_evaluation_timeout: 15
user_agent: Mozilla/5.0
storage_path: downloads
database_file: books.sqlite
logstamp_format: "%(message)s"
target_formats:
  - epub
proxy:
  enabled: false
  proxies: []
""",
                encoding="utf-8",
            )

            self.assertIsInstance(load_config(str(config_file)), AppConfig)


if __name__ == "__main__":
    unittest.main()
