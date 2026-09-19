import unittest
from datetime import date
from unittest.mock import patch

from free_llm import MODEL, FreeAnalyzer, verify_price
from five_year_audit import parse_date
from industry_history import visible_date


class HistoryTests(unittest.TestCase):
    def test_liga_visible_date_wins_over_anchor(self):
        self.assertEqual(visible_date('25 августа 2025 г. Новости'), date(2025,8,25))
        self.assertIsNone(visible_date('31 февраля 2025'))

    def test_source_dates(self):
        self.assertEqual(parse_date('20.09.2021'), date(2021, 9, 20))
        self.assertEqual(parse_date('2026-09-20T11:00:00'), date(2026, 9, 20))
        self.assertIsNone(parse_date('неизвестно'))

    def test_paid_and_missing_prices_blocked(self):
        for prices in ({'prompt': '0.001', 'completion': '0'}, {}, {'prompt':'0','completion':'0.01'}):
            with self.assertRaises(ValueError):
                verify_price({'data': [{'id': MODEL, 'pricing': prices}]})
        verify_price({'data': [{'id': MODEL, 'pricing': {'prompt':'0','completion':'0'}}]})

    def test_no_calls_after_budget(self):
        model = FreeAnalyzer(max_calls=0)
        with patch.object(model, '_call') as call:
            self.assertIsNone(model.analyze('text'))
            call.assert_not_called()

    def test_hallucinated_citation_rejected(self):
        model = FreeAnalyzer()
        result = model._validate({'applicability_suggested':'касается', 'requirements':[
            {'text':'выдумка','citation':'Несуществующее правило длиной больше двадцати пяти знаков'}]}, 'Исходный текст документа')
        self.assertEqual(result['requirements'], [])
        self.assertEqual(result['applicability_suggested'], 'неясно')

    def test_nonobject_model_response_is_not_fatal(self):
        model = FreeAnalyzer()
        with patch.object(model, '_call', return_value=[]):
            self.assertIsNone(model.analyze('text'))
        self.assertTrue(model.errors)
