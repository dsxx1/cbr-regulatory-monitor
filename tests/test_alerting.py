import unittest

from alerting import classify_alert


class AlertingTests(unittest.TestCase):
    def test_urgent_lombard_requirement_is_selected_once(self):
        doc = {"title": "Новые требования к ломбардам", "url": "https://cbr.ru/a", "text": "вступает в силу завтра", "key": "a", "version": "1"}
        first = classify_alert(doc, "new")
        self.assertEqual("urgent", first["level"])
        self.assertEqual(first["idempotency_key"], classify_alert(doc, "new")["idempotency_key"])

    def test_unrelated_document_is_not_selected(self):
        self.assertIsNone(classify_alert({"title": "Новости спорта"}, "new"))

    def test_unchanged_document_is_not_selected(self):
        self.assertIsNone(classify_alert({"title": "Ломбарды"}, "unchanged"))


if __name__ == "__main__":
    unittest.main()
