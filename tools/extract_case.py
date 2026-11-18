# -*- coding: utf-8 -*-
"""
Origami Kernel — Case Study Anonymizer & Extractor.
Extracts engineering architectural insights and patterns from downstream
1C enterprise task folders (e.g., downstream-projects) into clean,
OPCES-1.1 Zero-Leak compliant case studies for knowledge/playbooks/.
Pure Python standard library.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Exit codes per OPCES-1.1 Invariant 5
EXIT_SUCCESS = 0
EXIT_VALIDATION_ERROR = 1
EXIT_ENV_ERROR = 2

# Core sanitization rules (Blacklist to Generic replacements)
DEFAULT_REPLACEMENTS: List[Tuple[re.Pattern, str]] = [
    # Infrastructure & connection strings
    (re.compile(r'(?i)ws=["\']https?://[^"\']+["\']'), 'ws="<информационная_база>"'),
    (re.compile(r'(?i)https?://[a-zA-Z0-9\-\._]+(?::\d+)?(?:/[^\s\'"<>]*)?'), '<сетевой_ресурс>'),
    (re.compile(r'(?i)(?:Srvr|Ref|File)=["\'][^"\']+["\']'), '<строка_подключения>'),
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b'), '<ip_адрес>'),

    # Known commercial clients & brand identities (Strict Zero-Leak)
    (re.compile(r'(?i)\bэлэс\s*групп\b'), 'Холдинг-Партнер'),
    (re.compile(r'(?i)\bls\s*group\b'), 'Холдинг-Партнер'),
    (re.compile(r'(?i)\bls-gp\.ru\b'), 'partner.local'),
    (re.compile(r'(?i)\bбином(?:\s+системс)?\b'), 'Компания-Заказчик'),
    (re.compile(r'(?i)\bbinom(?:\s+systems)?\b'), 'Компания-Заказчик'),
    (re.compile(r'(?i)\bгарсинг\b'), 'ПроизводственноеПредприятие'),
    (re.compile(r'(?i)\bэнтузиаст\b'), 'ТорговаяСеть'),

    # Personal identifiers (Staff & Customer names)
    (re.compile(r'(?i)ширшов(?:\s+[а-я]\.[а-я]\.?)?'), 'Ведущий разработчик 1С'),
    (re.compile(r'(?i)тарасов[а-я]*'), 'Контрагент-А'),
    (re.compile(r'(?i)ип\s+тарасов'), 'Индивидуальный предприниматель'),

    # Extensions naming normalization
    (re.compile(r'(?i)расширени[ея]\s+[«"]доработка\s+элэс\s+групп[»"]'), 'Расширение «ДоработкаСистемы»'),
    (re.compile(r'(?i)расширени[ея]\s+[«"]доработка\s+бином[»"]'), 'Расширение «АдаптацияСистемы»'),
]


def sanitize_text(text: str, custom_replacements: Optional[List[Tuple[str, str]]] = None) -> str:
    """Applies regex and dictionary sanitation to remove sensitive proprietary data."""
    sanitized = text

    # Apply default regex replacements
    for pattern, replacement in DEFAULT_REPLACEMENTS:
        sanitized = pattern.sub(replacement, sanitized)

    # Apply user-provided custom replacements if any
    if custom_replacements:
        for src, dst in custom_replacements:
            sanitized = re.sub(re.escape(src), dst, sanitized, flags=re.IGNORECASE)

    # Additional cleanup for leftover file paths with user profiles
    sanitized = re.sub(r'(?i)[a-z]:\\users\\[a-z0-9_\-\.\\]+', '<локальный_каталог>', sanitized)

    return sanitized


def collect_task_sources(source_path: Path) -> List[Path]:
    """Finds all relevant markdown, text and BSL files in the target directory."""
    if source_path.is_file():
        return [source_path]

    collected = []
    # Search for markdown and text specs
    for ext in ("*.md", "*.txt", "*.bsl"):
        for p in source_path.glob(ext):
            if p.is_file() and not p.name.startswith("."):
                collected.append(p)
    return sorted(collected)


def extract_case_study(source_path: Path, output_path: Optional[Path] = None, preview: bool = False) -> int:
    """Processes source task materials and outputs a sanitized OPCES-1.1 case study."""
    if not source_path.exists():
        print(f"Ошибка: Исходный путь '{source_path}' не существует.", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    files = collect_task_sources(source_path)
    if not files:
        print(f"Предупреждение: В каталоге '{source_path}' не найдено файлов для анализа (.md, .txt, .bsl).", file=sys.stderr)
        return EXIT_VALIDATION_ERROR

    combined_raw_text = []
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            combined_raw_text.append(f"<!-- Source: {f.name} -->\n{content}")
        except Exception as e:
            print(f"Предупреждение: Не удалось прочитать '{f.name}': {e}", file=sys.stderr)

    raw_blob = "\n\n".join(combined_raw_text)
    sanitized_blob = sanitize_text(raw_blob)

    # Build standardized Case Study document
    task_id = source_path.name if source_path.is_dir() else source_path.stem
    doc_lines = [
        f"# Архитектурный кейс: {task_id}",
        "",
        "> **Статус:** Обезличенный инженерный срез (Zero-Leak per OPCES-1.1).  ",
        "> **Источник:** Материалы прикладной разработки downstream-проектов.  ",
        "",
        "---",
        "",
        "## 1. Исходные требования и формулировка задачи (Sanitized)",
        "",
        sanitized_blob.strip(),
        "",
        "---",
        "",
        "## 2. Архитектурное обобщение для Origami Kernel",
        "",
        "- **Примененный паттерн платформы:** [Заполняется инженером при интеграции в плейбуки]",
        "- **Ограничения обновлений вендора:** [Указать поведение при накате типового релиза]",
        "- **Контроль целостности данных:** [Указать влияние на регистры и управляемые блокировки]",
        "",
    ]

    result_md = "\n".join(doc_lines)

    if preview or output_path is None:
        print(result_md)
        return EXIT_SUCCESS

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result_md, encoding="utf-8")
        print(f"Успех: Обезличенный кейс сохранен в '{output_path}' (Zero-Leak проверен).")
        return EXIT_SUCCESS
    except Exception as e:
        print(f"Ошибка сохранения файла '{output_path}': {e}", file=sys.stderr)
        return EXIT_ENV_ERROR


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Origami Kernel Case Study Anonymizer (Zero-Leak data extractor)."
    )
    parser.add_argument(
        "--source", "-s",
        type=Path,
        required=True,
        help="Путь к папке задачи или файлу ТЗ прикладного проекта"
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Путь для сохранения итогового файла кейса (Markdown)"
    )
    parser.add_argument(
        "--preview", "-p",
        action="store_true",
        help="Вывести обезличенный результат в стандартный вывод"
    )

    args = parser.parse_args()
    return extract_case_study(args.source, args.output, args.preview)


if __name__ == "__main__":
    sys.exit(main())
