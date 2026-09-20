import unittest
import json
import tempfile
from contextlib import chdir
from pathlib import Path
from unittest.mock import patch
from dashboard_export import project, safe_url, settings

class DashboardTests(unittest.TestCase):
    def test_fingerprint_does_not_duplicate_publication(self):
        from dashboard_export import export
        with tempfile.TemporaryDirectory() as folder, chdir(folder):
            doc={'key':'sro:/1.html','title':'Новость','source':'industry-sro','url':'https://sro-lombard.ru/1.html'}
            Path('news-catalog.json').write_text(json.dumps([doc]),encoding='utf-8')
            version={**doc,'key':doc['key']+':'+('a'*64)}
            Path('cloud-state.json').write_text(json.dumps({'cards':[version]}),encoding='utf-8')
            Path('monitor-settings.json').write_text(json.dumps({'generator':'kilo-auto/free','reviewer':'kilo-auto/free','max_calls':1}),encoding='utf-8')
            with patch('dashboard_export.shutil.copyfile'):export()
            cards=json.loads(Path('public/news.json').read_text(encoding='utf-8'))['news']
            self.assertEqual(len(cards),1)
            self.assertEqual(cards[0]['key'],doc['key'])

    def test_projection_excludes_delivery_secrets_and_internal_fields(self):
        doc={'key':'a','title':'Материал','source':'cbr-na','webhook':'secret','external_id':'2390','text':'internal delivery'}
        projected=project(doc,'collected')
        self.assertNotIn('webhook',projected)
        self.assertNotIn('external_id',projected)
        self.assertNotIn('secret',str(projected))

    def test_unsafe_links_removed(self):
        self.assertEqual(safe_url('javascript:alert(1)'), '')
        self.assertEqual(safe_url('https://cbr.ru/a'),'https://cbr.ru/a')

    def test_archive_does_not_become_verified(self):
        item=project({'key':'x','title':'Архив'},'collected',True)
        self.assertTrue(item['archive'])
        self.assertEqual(item['stage'],'collected')

    def test_actual_server_model_settings_load(self):
        self.assertIn(settings()['generator'],('kilo-auto/free','inclusionai/ling-3.0-flash-vl:free'))
