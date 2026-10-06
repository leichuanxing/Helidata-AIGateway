"""Configuration validation and secret-safe errors, no running services required."""
import os
from pathlib import Path
import tempfile
import unittest
import yaml

from app.core.config import ConfigurationError, ensure_config, load_settings


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / 'config.yaml'
        self.previous = {name: os.environ.get(name) for name in ('GATEWAY_CONFIG','GATEWAY_CONFIG_TEMPLATE')}
        os.environ['GATEWAY_CONFIG'] = str(self.path)
        os.environ['GATEWAY_CONFIG_TEMPLATE'] = '/app/config/config.yaml.example'

    def tearDown(self):
        for name, value in self.previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        self.directory.cleanup()

    def test_generation_and_preservation(self):
        ensure_config()
        first = self.path.read_bytes()
        settings = load_settings()
        self.assertGreaterEqual(len(settings.database.password.get_secret_value()), 32)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(settings.database.password.get_secret_value(), repr(settings))
        ensure_config()
        self.assertEqual(self.path.read_bytes(), first)

    def test_edits_and_validation(self):
        ensure_config()
        value = yaml.safe_load(self.path.read_text())
        value['gateway']['max_concurrency'] = 123
        value['gateway']['queue_size'] = 0
        self.path.write_text(yaml.safe_dump(value))
        self.assertEqual(load_settings().gateway.max_concurrency, 123)
        self.assertEqual(load_settings().gateway.queue_size, 0)
        value['gateway']['max_concurrency'] = -1
        self.path.write_text(yaml.safe_dump(value))
        with self.assertRaisesRegex(ConfigurationError, 'gateway.max_concurrency'):
            load_settings()

    def test_secret_errors_are_redacted(self):
        ensure_config()
        value = yaml.safe_load(self.path.read_text())
        value['security']['jwt_secret'] = 'BAD-SECRET'
        self.path.write_text(yaml.safe_dump(value))
        with self.assertRaises(ConfigurationError) as caught:
            load_settings()
        self.assertNotIn('BAD-SECRET', str(caught.exception))
        self.assertIn('security.jwt_secret', str(caught.exception))

    def test_invalid_yaml_and_unknown_fields(self):
        self.path.write_text('database: [invalid')
        with self.assertRaises(ConfigurationError):
            load_settings()
        ensure_config_value = {'unknown_field': 'SENSITIVE-VALUE'}
        self.path.write_text(yaml.safe_dump(ensure_config_value))
        with self.assertRaises(ConfigurationError) as caught:
            load_settings()
        self.assertNotIn('SENSITIVE-VALUE', str(caught.exception))

    def test_listener_conflicts(self):
        ensure_config()
        value = yaml.safe_load(self.path.read_text())
        value['redis']['port'] = value['server']['port']
        self.path.write_text(yaml.safe_dump(value))
        with self.assertRaisesRegex(ConfigurationError, 'conflicts'):
            load_settings()


if __name__ == '__main__':
    unittest.main()
