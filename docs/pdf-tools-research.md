# PDF, сканы и таблицы: выбор для бесплатного облачного мониторинга

Проверка первичных источников: 20.09.2026. Это исследование документации, не сравнительный прогон документов Банка России. Страницы `main` и `master` изменяются; при внедрении нужно закрепить версию пакета и проверить её API.

## Решение

Для первого измеряемого варианта предлагается **Docling Python API + Tesseract CLI с `rus` и `eng`, CPU, распознавание таблиц**. Такой выбор объясняется явной настройкой OCR и структурированным результатом; утверждения, что он точнее всех на российских нормативных актах, пока нет. Для простой текстовой версии PDF можно сначала извлекать встроенный текст, а OCR использовать для сканов и проблемных страниц. Отдельно проверять смешанные PDF: наличие текста на первой странице не доказывает, что остальные страницы распознаны.

**docling-mcp не является отдельным OCR-движком.** Он предоставляет агентам интерфейс к конвертации Docling, локально или через сервис. Качество определяется выбранным конвейером, OCR, моделями и входным файлом. Для расписания GitHub Actions прямой вызов Python проще; MCP полезен позднее для интерактивного запроса агентом. В актуальном README по умолчанию выбран remote-режим, а локальный требует соответствующих зависимостей. [Официальный docling-mcp](https://github.com/docling-project/docling-mcp)

## Сравнение

| Средство | Подтверждено документацией/кодом | Практический вывод для проекта |
| --- | --- | --- |
| Docling | Настраиваемые OCR-движки, структура таблиц, CPU, экспорт Markdown и JSON. | Основной кандидат для структурного извлечения; стоимость загрузки моделей, время и память измерить на runner. |
| docling-mcp | Обёртка над конвертацией Docling, локальный и удалённый режимы. | Подключение MCP само по себе не улучшает распознавание. Не требуется для фонового Python-задания. |
| MinerU | Актуальная документация 4.0: Basic обрабатывает OCR/формулы/таблицы на малых моделях без VLM; ONNX работает на CPU. Standard/Advanced добавляют VLM. | Реальный кандидат для контрольного сравнения: CPU Basic. Нельзя объявлять MinerU инструментом только для GPU или переносить результат Standard на Basic. |
| Microsoft MarkItDown | PDF-конвертер использует pdfminer и pdfplumber, содержит обработку таблиц. Отдельный OCR-плагин использует LLM Vision. | Подходит как лёгкий вариант для PDF с текстовым слоем; полноценный бесплатный русский OCR не следует считать гарантированным свойством базового пакета. |

Источники сравнения: [Docling custom conversion](https://github.com/docling-project/docling/blob/main/docs/examples/custom_convert.py), [Docling OCR](https://github.com/docling-project/docling/blob/main/docs/concepts/OCR.md), [MinerU tiers and runtimes](https://opendatalab.github.io/MinerU/usage/tiers/), [MarkItDown PDF converter](https://github.com/microsoft/markitdown/blob/main/packages/markitdown/src/markitdown/converters/_pdf_converter.py), [MarkItDown README, OCR plugin](https://github.com/microsoft/markitdown/blob/main/README.md).

## Конкретная настройка Docling

Ниже пример конфигурации на основе официального API, а не отчёт о выполненном запуске. В Linux должны быть установлены Tesseract CLI и языковые данные `rus`/`eng`; это проверяется командой `tesseract --list-langs`. В Ubuntu пакеты обычно называются `tesseract-ocr`, `tesseract-ocr-rus`, `tesseract-ocr-eng`.

```python
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TesseractCliOcrOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

options = PdfPipelineOptions()
options.do_ocr = True
options.do_table_structure = True
options.ocr_options = TesseractCliOcrOptions(lang=["rus", "eng"])
options.accelerator_options = AcceleratorOptions(
    device=AcceleratorDevice.CPU,
    num_threads=2,
)
converter = DocumentConverter(format_options={
    InputFormat.PDF: PdfFormatOption(pipeline_options=options),
})
result = converter.convert("document.pdf")
markdown = result.document.export_to_markdown()
structured = result.document.export_to_dict()
```

`rus` — официальный код русского языка Tesseract; Docling принимает нативные коды установленного OCR. Число потоков 2 — начальная инженерная настройка, не найденный оптимум. [Коды языков Tesseract](https://tesseract-ocr.github.io/tessdoc/Data-Files-in-different-versions.html), [выбор языка Docling](https://github.com/docling-project/docling/blob/main/docs/concepts/OCR.md), [CPU и потоки](https://github.com/docling-project/docling/blob/main/docling/datamodel/accelerator_options.py).

Для сканов с испорченным скрытым текстовым слоем может понадобиться принудительный OCR всей страницы. В текущем примере `main` используется `mode=OcrMode.FULL_PAGE`; старые версии API могут использовать другое поле. Перед добавлением этого параметра проверить именно закреплённую версию, не копировать настройки разных версий вместе. [Официальный пример полного OCR](https://github.com/docling-project/docling/blob/main/docs/examples/tesseract_lang_detection.py).

## Бесплатный GitHub Actions и проверка результата

По текущей документации стандартный Linux runner публичного репозитория имеет 4 CPU, 16 GB RAM и 14 GB SSD; стандартные runners публичных репозиториев бесплатны. Это не означает бесплатность любого типа runner или любых дополнительных сервисов. Для частного репозитория применяются условия тарифа и квоты. Для OCR предпочесть обычный `ubuntu-24.04`, а не ограниченный `ubuntu-slim`. [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).

Предлагаемая проверка перед выбором постоянного конвейера:

1. Взять одинаковый небольшой набор открытых PDF: цифровой нормативный акт, русский скан, смешанный PDF и приложение с таблицами.
2. Для каждого измерить холодный старт, обработку после кеширования моделей, пик RAM, число обработанных страниц; отдельно учитывать ошибки и тайм-ауты.
3. Проверить по оригиналу номера пунктов, даты, суммы, знак минус, проценты, примечания и связи ячеек таблицы. Красивый Markdown не доказывает верность этих данных.
4. Сохранять URL, хеш исходного PDF, версию конвертера и номер страницы. Отдельно помечать частичный/неудачный разбор; не превращать отсутствие извлечённого текста в вывод «изменений нет».
5. Сравнить Docling и MinerU Basic по этой разметке. MarkItDown использовать как дополнительный контроль текстовых PDF. Ограничения на размер, страницы и время задавать явно; превышение оформлять как незавершённую обработку.

Пункты проверки — рекомендации для проекта. Пока нет результатов такого прогона, нельзя обещать полноту распознавания, превосходство одного инструмента или конкретное число документов в бесплатной квоте. Установка, запуск моделей и изменения облачного workflow в рамках этого исследования не выполнялись.
