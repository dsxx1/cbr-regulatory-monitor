import unittest
from backfill import retryable, order
from dashboard_export import material_markdown
from material_analysis import semantic_checks

class BackfillTests(unittest.TestCase):
    def test_finished_and_cooling_items_not_reprocessed(self):
        self.assertFalse(retryable({'state':'verified'},'2026-09-20'))
        self.assertFalse(retryable({'state':'retry','retry_at':'2026-09-21'},'2026-09-20'))
        self.assertTrue(retryable({'state':'pending'},'2026-09-20'))

    def test_editorial_priority_only_orders_work(self):
        focus={'key':'sro:/1000018365.html','title':'Цифровой рубль','published':'2026-08-31'}
        old={'key':'old','title':'Отчётность','published':'01.01.2022'}
        new={'key':'new','title':'Отчётность','published':'02.01.2026'}
        self.assertLess(order(focus),order(new))
        self.assertLess(order(new),order(old))

    def test_missing_threshold_is_rejected(self):
        source='Выручка превышает 120 млн рублей; договор на 1 января 2026 года.'
        self.assertEqual(len(semantic_checks({'summary':'Все ломбарды обязаны подключиться'},source)),2)

    def test_no_brief_still_has_honest_source_markdown(self):
        md=material_markdown({'title':'Новость','url':'https://cbr.ru/','brief':None,'body':'Полный исходный текст'})
        self.assertIn('не подтверждённый аналитический разбор',md)
        self.assertIn('Полный исходный текст',md)
