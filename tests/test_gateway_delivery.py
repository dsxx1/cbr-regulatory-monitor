import os
import unittest
from unittest.mock import patch

import config
from b24 import Outbox


class GatewayDeliveryTests(unittest.TestCase):
    def setUp(self):
        config._cache = {}
        os.environ.pop("MONITOR_GATEWAY_URL", None)
        os.environ.pop("MONITOR_SHARED_SECRET", None)

    def test_gateway_is_disabled_without_explicit_send(self):
        os.environ["MONITOR_GATEWAY_URL"] = "https://worker.example"
        os.environ["MONITOR_SHARED_SECRET"] = "test-secret"
        config._cache = None
        outbox = Outbox("unused.json", send=False)
        self.assertFalse(outbox.send_enabled)

    def test_gateway_payload_is_signed(self):
        os.environ["MONITOR_GATEWAY_URL"] = "https://worker.example"
        os.environ["MONITOR_SHARED_SECRET"] = "test-secret"
        config._cache = None
        outbox = Outbox("unused.json", send=True)
        entry = outbox.enqueue({"key": "a", "version": "1", "title": "Ломбарды", "url": "https://cbr.ru/a", "source_title": "ЦБ"})
        with patch("urllib.request.urlopen") as call:
            call.return_value.__enter__.return_value.status = 202
            call.return_value.__enter__.return_value.read.return_value = b'{"accepted":true,"external_id":"10"}'
            outbox._send_gateway(entry)
        request = call.call_args.args[0]
        self.assertEqual("POST", request.method)
        self.assertTrue(request.get_header("X-monitor-signature"))


if __name__ == "__main__":
    unittest.main()
