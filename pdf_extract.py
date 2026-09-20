"""Page-aware PDF extraction. Unread pages fail closed, not as complete sources."""
import io
import os
import shutil
import subprocess
import tempfile
import sys
from pathlib import Path


def readable(text):
    letters = sum(c.isalpha() for c in text)
    return letters >= 35 and text.count('\ufffd') <= max(2, len(text) // 100)


def ocr_page(raw, number):
    if not shutil.which('pdftoppm') or not shutil.which('tesseract'):
        raise ValueError('Scanned PDF requires OCR tools')
    with tempfile.TemporaryDirectory(prefix='regulator-page-') as folder:
        root = Path(folder)
        source = root / 'source.pdf'
        source.write_bytes(raw)
        subprocess.run(['pdftoppm', '-f', str(number), '-l', str(number),
                        '-singlefile', '-r', '180', '-png', str(source), str(root / 'page')],
                       check=True, capture_output=True, timeout=90)
        result = subprocess.run(['tesseract', str(root / 'page.png'), 'stdout', '-l', 'rus+eng'],
                                check=True, capture_output=True, timeout=60)
        return result.stdout.decode('utf-8', errors='replace')


def extract_pages(raw, pages, ocr_enabled=False):
    missing = [i for i, text in enumerate(pages) if not readable(text)]
    if len(missing) > 25:
        raise ValueError('Scanned PDF exceeds automatic OCR page limit (25); document not truncated')
    results = []
    for number, text in enumerate(pages, 1):
        method = 'текстовый слой PDF'
        if not readable(text):
            if not ocr_enabled:
                raise ValueError(f'Scanned PDF requires OCR: page {number}')
            text = ocr_page(raw, number)
            method = 'OCR; реквизиты требуют сверки с оригиналом'
            if not readable(text):
                raise ValueError(f'OCR did not extract sufficient text: page {number}; review original')
        results.append(f'## Страница {number} ({method})\n\n{text.strip()}')
    return '\n\n'.join(results)


def extract_pdf(raw):
    from pypdf import PdfReader
    pdf = PdfReader(io.BytesIO(raw))
    if len(pdf.pages) > 200:
        raise ValueError('PDF exceeds 200 pages; requires split')
    pages = []
    for page in pdf.pages:
        try:
            pages.append(page.extract_text() or '')
        except Exception:
            pages.append('')
    if os.environ.get('DOCLING_ENABLED') == 'yes':
        with tempfile.TemporaryDirectory(prefix='regulator-docling-') as folder:
            source, output = Path(folder) / 'source.pdf', Path(folder) / 'source.md'
            source.write_bytes(raw)
            subprocess.run([sys.executable, str(Path(__file__).with_name('docling_convert.py')),
                            str(source), str(output)], check=True, capture_output=True, timeout=360)
            markdown = output.read_text(encoding='utf-8')
            # Fail explicitly if the converter silently lost any page.
            sections = markdown.split('## Страница ')[1:]
            if len(sections) != len(pages) or any(not readable(s.partition('\n')[2]) for s in sections):
                raise ValueError('Docling page coverage incomplete; review original')
            return markdown
    return extract_pages(raw, pages, os.environ.get('OCR_ENABLED') == 'yes')
