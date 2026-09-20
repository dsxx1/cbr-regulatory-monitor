import unittest
from unittest.mock import patch
from pdf_extract import extract_pages


class PdfPipelineTests(unittest.TestCase):
    def test_mixed_document_does_not_skip_scanned_page(self):
        text = 'Первая страница с достаточным количеством текста. ' * 8
        with patch('pdf_extract.ocr_page', return_value='Распознанная вторая страница. ' * 8) as ocr:
            result = extract_pages(b'pdf', [text, ''], ocr_enabled=True)
        self.assertIn('Страница 2', result)
        self.assertIn('Распознанная', result)
        ocr.assert_called_once_with(b'pdf', 2)

    def test_missing_page_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError, 'page 2'):
            extract_pages(b'pdf', ['Текст нормативного документа ' * 10, ''], ocr_enabled=False)

    def test_page_limit_never_returns_partial_document(self):
        with self.assertRaisesRegex(ValueError, 'limit'):
            extract_pages(b'pdf', [''] * 26, ocr_enabled=True)

    def test_unreadable_ocr_is_rejected(self):
        with patch('pdf_extract.ocr_page', return_value='???'):
            with self.assertRaisesRegex(ValueError, 'page 1'):
                extract_pages(b'pdf', [''], ocr_enabled=True)
