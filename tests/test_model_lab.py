import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from model_lab import ask,validate


class ModelLabTests(unittest.TestCase):
    def test_backfill_uses_selected_models(self):
        from backfill import process
        config={'generator':'kilo-auto/free','reviewer':'inclusionai/ling-3.0-flash-vl:free'}
        doc={'key':'test','body':'Документ ' * 30}
        with patch('backfill.analyze_material',return_value={}) as analyze:
            process(doc,{},config)
            self.assertEqual(analyze.call_args.args[1:],(config['generator'],config['reviewer']))
    def test_forbids_paid_or_unknown_model(self):
        with self.assertRaises(ValueError):validate('paid/model','Привет')
    def test_rejects_secret_and_oversize(self):
        for message in ('https://example.test/rest/12/secret_value/','x'*4001,''):
            with self.assertRaises(ValueError):validate('kilo-auto/free',message)
    def test_exact_model_is_strict_and_usage_is_honest(self):
        reply={'result':{'model':'actual','choices':[{'message':{'content':'Ответ'}}]},'route':'inclusionai/ling-3.0-flash-vl:free'}
        with patch('model_lab.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(reply))) as run:
            result=ask('inclusionai/ling-3.0-flash-vl:free','Проверка')
            self.assertTrue(json.loads(run.call_args.kwargs['input'])['_strict_model'])
            self.assertIsNone(result['cost']);self.assertIsNone(result['tokens'])
    def test_no_raw_error_exposed(self):
        with patch('model_lab.subprocess.run',return_value=SimpleNamespace(returncode=1,stderr='HTTP 429 sensitive_detail')):
            with self.assertRaises(ValueError) as failure:ask('kilo-auto/free','Привет')
            self.assertNotIn('sensitive_detail',str(failure.exception))
