import unittest
from dashboard_export import project, safe_url, settings

class DashboardTests(unittest.TestCase):
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
