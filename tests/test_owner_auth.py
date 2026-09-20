import tempfile
import unittest
from admin_auth import OwnerAuth


class OwnerTests(unittest.TestCase):
    def test_lan_cannot_login_even_with_key(self):
        with tempfile.TemporaryDirectory() as root:
            auth=OwnerAuth(root)
            self.assertIsNone(auth.login('192.168.1.8',auth.key))

    def test_session_cannot_be_reused_over_lan(self):
        with tempfile.TemporaryDirectory() as root:
            auth=OwnerAuth(root); token=auth.login('127.0.0.1',auth.key)
            self.assertTrue(auth.allowed('127.0.0.1','monitor_owner='+token))
            self.assertFalse(auth.allowed('192.168.1.8','monitor_owner='+token))
            self.assertFalse(auth.allowed('127.0.0.1',''))
            self.assertIsNone(auth.login('127.0.0.1','wrong'))
