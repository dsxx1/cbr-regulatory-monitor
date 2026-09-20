import unittest
from types import SimpleNamespace
from unittest.mock import patch
from admin_auth import OwnerAuth
from local_server import Handler


class OwnerTests(unittest.TestCase):
    def test_passwordless_owner_requires_loopback_peer_and_host(self):
        with patch('local_server.AUTH',OwnerAuth()):
            for address,host,expected in [('127.0.0.1','localhost:8787',True),('127.0.0.1','127.0.0.1:8787',True),('10.1.2.3','localhost:8787',False),('127.0.0.1','attacker.test:8787',False),('10.1.2.3','10.1.2.4:8787',False)]:
                request=SimpleNamespace(client_address=(address,1),headers={'Host':host})
                self.assertEqual(Handler.owner(request),expected)
