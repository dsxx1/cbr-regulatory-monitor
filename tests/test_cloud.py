import unittest
from cloud_monitor import quality
from unittest.mock import patch
from bot_cloud import call

class CloudTests(unittest.TestCase):
    def test_literal_citation_required(self):
        quote = 'Ломбард представляет отчетность в Банк России.'
        result = {'requirements':[{'text':'Подать отчёт','citation':quote}]}
        self.assertTrue(quality(result, quote))
        self.assertFalse(quality(result,'Другой текст источника'))
        self.assertFalse(quality({'requirements':[]},quote))
        self.assertFalse(quality({'requirements':[{'text':'放在ной текст','citation':quote}]},quote))

    def test_wrong_portal_cannot_receive_messages(self):
        with patch.dict('os.environ',{'B24_WEBHOOK':'https://example.com/rest/x/'},clear=True):
            with self.assertRaises(RuntimeError):
                call('im.message.add',{})
