"""Isolated CPU converter used by PDF extraction, not a permanent server."""
import sys
from pathlib import Path


def main():
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat, ConversionStatus
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption
    options = PdfPipelineOptions()
    options.do_ocr = True
    options.do_table_structure = True
    options.ocr_options = TesseractCliOcrOptions(lang=['rus', 'eng'])
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)})
    result = converter.convert(sys.argv[1], max_num_pages=200)
    if result.status != ConversionStatus.SUCCESS:
        raise ValueError('Docling conversion incomplete')
    # Keep page provenance; do not replace the original PDF with a model paraphrase.
    pages = []
    for number in sorted(result.document.pages):
        text = result.document.export_to_markdown(page_no=number)
        pages.append(f'## Страница {number} (Docling, OCR и таблицы)\n\n{text}')
    Path(sys.argv[2]).write_text('\n\n'.join(pages), encoding='utf-8')


if __name__ == '__main__':
    main()
