"""AES-GCM authenticity, nonce uniqueness and sanitized failure behavior."""
import secrets,tempfile,unittest
from pathlib import Path
from app.core.exceptions import APIError
from app.services import provider_crypto as crypto


class CryptoTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.original=crypto.KEY_PATH
        crypto.KEY_PATH=Path(self.temp.name)/'encryption.key'
        crypto.KEY_PATH.write_bytes(secrets.token_bytes(32))
    def tearDown(self):
        crypto.KEY_PATH=self.original
        self.temp.cleanup()
    def test_encryption_random_nonce(self):
        raw='sensitive-provider-test-key'
        a,b=crypto.encrypt_secret(raw),crypto.encrypt_secret(raw)
        self.assertNotEqual(a,b)
        self.assertNotIn(raw,a)
        self.assertEqual(crypto.decrypt_secret(a),raw)
        self.assertEqual(crypto.decrypt_secret(b),raw)
    def test_tamper_rejected(self):
        value=crypto.encrypt_secret('sensitive-provider-test-key')
        replacement='A' if value[-5]!='A' else 'B'
        with self.assertRaises(APIError) as error:
            crypto.decrypt_secret(value[:-5]+replacement+value[-4:])
        self.assertEqual(error.exception.detail['code'],'PROVIDER_KEY_DECRYPT_FAILED')
        self.assertNotIn(value,str(error.exception.detail))
    def test_wrong_key_rejected(self):
        value=crypto.encrypt_secret('sensitive-provider-test-key')
        crypto.KEY_PATH.write_bytes(secrets.token_bytes(32))
        with self.assertRaises(APIError): crypto.decrypt_secret(value)
    def test_missing_or_short_file(self):
        crypto.KEY_PATH.write_bytes(b'short')
        with self.assertRaises(APIError): crypto.encrypt_secret('sensitive-provider-test-key')
        crypto.KEY_PATH.unlink()
        with self.assertRaises(APIError): crypto.encrypt_secret('sensitive-provider-test-key')

if __name__=='__main__': unittest.main()
