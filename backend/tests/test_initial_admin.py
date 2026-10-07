import asyncio
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from argon2 import PasswordHasher
from app.services.initial_admin import encode_credentials, read_credentials
from app.services import bootstrap

class InitialAdminTests(unittest.TestCase):
    def test_hash_roundtrip(self):
        password = 'Offline-Test-2026!'
        value = encode_credentials({'username': 'offlineadmin', 'password': password})
        self.assertNotIn('password', value)
        self.assertTrue(PasswordHasher().verify(value['password_hash'], password))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'admin.json'
            path.write_text(json.dumps(value), encoding='utf-8')
            self.assertEqual(read_credentials(path), ('offlineadmin', value['password_hash']))

    def test_invalid_input(self):
        for username, password in [('ab', 'Offline-Test-2026!'), ('bad\nname', 'Offline-Test-2026!'), ('admin', 'short'), ('admin', 'a' * 129), ('admin', 'abcdefghijkl')]:
            with self.subTest(username=username), self.assertRaises(ValueError):
                encode_credentials({'username': username, 'password': password})

    def test_invalid_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'admin.json'
            for value in [{}, {'username': 'admin', 'password_hash': '$argon2id$bad'}, {'username': 'admin', 'password': 'secret'}]:
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_credentials(path)

    def run_bootstrap(self, existing):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'admin.json'
            value = encode_credentials({'username': 'offlineadmin', 'password': 'Offline-Test-2026!'})
            path.write_text(json.dumps(value), encoding='utf-8')
            users = []
            session = SimpleNamespace(scalar=AsyncMock(side_effect=[existing, 1]), add=users.append)
            @contextlib.asynccontextmanager
            async def begin():
                yield session
            logs = io.StringIO()
            with patch.object(bootstrap, 'session_factory', SimpleNamespace(begin=begin)), patch.object(bootstrap, 'engine', SimpleNamespace(dispose=AsyncMock())), patch.object(bootstrap, 'INITIAL_ADMIN_FILE', path), contextlib.redirect_stdout(logs):
                asyncio.run(bootstrap.bootstrap())
            self.assertFalse(path.exists())
            self.assertNotIn('Offline-Test-2026!', logs.getvalue())
            self.assertNotIn(value['password_hash'], logs.getvalue())
            return users

    def test_custom_administrator(self):
        users = self.run_bootstrap(None)
        self.assertEqual(users[0].username, 'offlineadmin')
        self.assertFalse(users[0].must_change_password)

    def test_existing_administrator_not_reset(self):
        self.assertEqual(self.run_bootstrap(42), [])
