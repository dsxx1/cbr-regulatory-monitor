import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from bot_cloud import call, DeliveryBlocked
from dashboard_export import project
from material_analysis import valid_brief
from pathlib import Path
import json


class MaterialTests(unittest.TestCase):
    def test_headline_never_assigns_importance(self):
        for title in ('Новые правила ломбардам','Вступил в силу закон','Отчётность'):
            self.assertEqual(project({'key':'test','title':title,'source':'cbr-na'},'pending')['priority'],'unknown')

    def test_verified_brief_must_explain_importance(self):
        doc={'key':'a','brief_verified':True,'brief':{'priority':'medium','priority_reason':'Инициатива затронет процессы после принятия.'}}
        self.assertEqual(project(doc,'verified')['priority'],'medium')
        doc['brief']['priority_reason']=''
        self.assertEqual(project(doc,'verified')['priority'],'unknown')

    def test_scope_block_has_specific_type(self):
        error=HTTPError('redacted',401,'Unauthorized',{},io.BytesIO(b'{"error":"insufficient_scope"}'))
        with patch.dict('os.environ',{'B24_WEBHOOK':'https://sks-portal.bitrix24.ru/rest/test/'}),patch('bot_cloud.urlopen',side_effect=error):
            with self.assertRaises(DeliveryBlocked):call('imbot.v2.Bot.register',{})

    def test_other_failure_is_not_configuration_block(self):
        error=HTTPError('redacted',500,'Failure',{},io.BytesIO(b'{}'))
        with patch.dict('os.environ',{'B24_WEBHOOK':'https://sks-portal.bitrix24.ru/rest/test/'}),patch('bot_cloud.urlopen',side_effect=error):
            with self.assertRaises(RuntimeError) as result:call('imbot.v2.Bot.register',{})
            self.assertNotIsInstance(result.exception,DeliveryBlocked)

    def test_fabricated_quote_rejected(self):
        brief={'priority':'medium','event_status':'инициатива','summary':'s','priority_reason':'r','impact':'i','timing':'t',
               'actions':[],'uncertainties':[],'evidence':[{'claim':'a','citation':'Несуществующая цитата длиной более 25 символов'}]}
        self.assertFalse(valid_brief(brief,'Настоящий исходник'))

    def test_published_example_has_real_source_and_supported_quotes(self):
        records=json.loads(Path('material-briefs.json').read_text(encoding='utf-8'))
        material=records['sro:/1000018373.html']
        self.assertTrue(valid_brief(material['brief'],material['title']+'\n'+material['body']))
        self.assertEqual(material['brief']['event_status'],'инициатива')
        self.assertIn('не подтверждено',material['brief']['timing'])
