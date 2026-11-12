# -*- coding: utf-8 -*-
"""
Pure-Diff BSL Linter — Авторский статический анализатор стандартов 1С (платформа 8.3.27)
Часть платформенного каркаса Origami Platform.

Принципы Pure-Diff анализа:
1. Изоляция: Проверяются СТРОГО добавленные/измененные строки (Green Hunks).
2. Амнистия R-003: Закомментированный чужой код в блоках удаления // { - ... } амнистирован.
3. Eye-Only Policy: Чужой легаси-код вокруг правок не проверяется.
4. Отсутствие ложных срабатываний: Не проверяет существование внешних метаданных базы
   (исключает ошибки на РасчетыСКлиентамиПоСрокам и методы вендора в расширениях).

Контролируемые стандарты (в добавленных строках имеют статус ERROR, код выхода 1):
- LineLength: Длина строки <= 120 символов (Стандарт 456).
- UsingOrInWhere: Запрет оператора ИЛИ в условии ГДЕ запросов (Стандарт 658).
- UnionWithoutAll: Использование ОБЪЕДИНИТЬ ВСЕ вместо ОБЪЕДИНИТЬ (Стандарт 434).
- DeprecatedError: Запрет устаревшего ПодробноеПредставлениеОшибки (стандарт БСП).
- MissingElse: Обязательный блок Иначе в конструкциях Если-ИначеЕсли.
- CognitiveComplexity: Ограничение глубины вложенности блоков (<= 5 отступов / 15 сложность).
"""

import sys
import os
import re
import argparse
import json

# Гарантируем UTF-8 вывод на консоль Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass


def parse_line_ranges(ranges_str):
    """
    Разбирает строку диапазонов: '10-25' или '10-25,40-60' или '15' в множество номеров строк (1-based).
    """
    lines_set = set()
    if not ranges_str:
        return lines_set

    parts = ranges_str.split(',')
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            try:
                start, end = part.split('-', 1)
                lines_set.update(range(int(start), int(end) + 1))
            except ValueError:
                pass
        else:
            try:
                lines_set.add(int(part))
            except ValueError:
                pass
    return lines_set


def find_author_green_lines(lines, author_marker):
    """
    Определяет номера строк, добавленных автором по корпоративному регламенту R-003:
    // { + ЛС ... } или // + ...
    А также определяет амнистированные строки удаления: // { - ... }
    """
    green_lines = set()
    amnestied_lines = set()

    in_green_block = False
    in_red_block = False

    plus_pattern = re.compile(r'//\s*\{\s*\+\s*.*?' + re.escape(author_marker), re.IGNORECASE) if author_marker else re.compile(r'//\s*\{\s*\+', re.IGNORECASE)
    minus_pattern = re.compile(r'//\s*\{\s*-\s*', re.IGNORECASE)
    close_pattern = re.compile(r'//\s*\}\s*', re.IGNORECASE)

    for idx, line in enumerate(lines, 1):
        stripped = line.strip()

        # Проверка блока удаления (Red Hunk)
        if minus_pattern.search(stripped):
            in_red_block = True
            amnestied_lines.add(idx)
            continue
        elif in_red_block:
            amnestied_lines.add(idx)
            if close_pattern.search(stripped):
                in_red_block = False
            continue

        # Проверка блока добавления (Green Hunk)
        if plus_pattern.search(stripped):
            in_green_block = True
            green_lines.add(idx)
            continue
        elif in_green_block:
            green_lines.add(idx)
            if close_pattern.search(stripped):
                in_green_block = False
            continue

    return green_lines, amnestied_lines


def lint_bsl_content(file_path, content, target_lines=None, author=""):
    """
    Выполняет Pure-Diff анализ BSL кода.
    target_lines: set номеров строк, подлежащих проверке. Если пустой — определяются по author или проверяется всё.
    """
    lines = content.splitlines(True)
    total_lines = len(lines)

    # 1. Определение амнистированных строк (Red Hunks // { - ... })
    author_green, amnestied_lines = find_author_green_lines(lines, author)

    # Если диапазон строк не задан явно, но есть автор — проверяем строки автора
    if not target_lines:
        if author_green:
            check_lines = author_green
        else:
            # Если диапазон не задан и блоков автора нет — проверяем весь файл (за вычетом амнистированных)
            check_lines = set(range(1, total_lines + 1))
    else:
        check_lines = target_lines

    # Исключаем амнистированные строки удаления
    check_lines = check_lines - amnestied_lines

    issues = []

    # 1. Проверка длины строки (Стандарт 456)
    for idx, raw_line in enumerate(lines, 1):
        if idx not in check_lines:
            continue
        clean_line = raw_line.rstrip('\r\n')
        if len(clean_line) > 120:
            issues.append({
                "file": file_path,
                "line": idx,
                "severity": "ERROR",
                "code": "LineLength",
                "message": f"Длина строки {len(clean_line)} превышает допустимую 120 (Стандарт 456)"
            })

    # 2. Проверка устаревшего метода ПодробноеПредставлениеОшибки
    for idx, raw_line in enumerate(lines, 1):
        if idx not in check_lines:
            continue
        if "ПодробноеПредставлениеОшибки" in raw_line and "ОбработкаОшибок." not in raw_line:
            # Игнорируем в комментариях
            clean_str = raw_line.strip()
            if not clean_str.startswith("//"):
                issues.append({
                    "file": file_path,
                    "line": idx,
                    "severity": "ERROR",
                    "code": "DeprecatedError",
                    "message": "Метод 'ПодробноеПредставлениеОшибки' устарел. Следует использовать 'ОбработкаОшибок.ПодробноеПредставлениеОшибки'"
                })

    # 3. Проверка ИЛИ в ГДЕ и ОБЪЕДИНИТЬ без ВСЕ в запросах
    in_query = False
    in_where = False

    for idx, raw_line in enumerate(lines, 1):
        up = raw_line.upper()
        clean = raw_line.strip()

        # Игнорируем закомментированные строки
        if clean.startswith("//"):
            continue

        if "ВЫБРАТЬ" in up and ('"' in raw_line or '|' in raw_line):
            in_query = True

        if in_query:
            # Проверка ОБЪЕДИНИТЬ без ВСЕ (Стандарт 434)
            if idx in check_lines:
                if re.search(r'\|\s*ОБЪЕДИНИТЬ\b(?!\s+ВСЕ\b)', raw_line, re.IGNORECASE):
                    issues.append({
                        "file": file_path,
                        "line": idx,
                        "severity": "ERROR",
                        "code": "UnionWithoutAll",
                        "message": "Использование ОБЪЕДИНИТЬ без ВСЕ приводит к излишней сортировке/дедупликации (Стандарт 434)"
                    })

            if "ГДЕ" in up and ('|' in raw_line or '"' in raw_line):
                in_where = True

            if in_where:
                if idx in check_lines and re.search(r'\bИЛИ\b', raw_line, re.IGNORECASE) and ('|' in raw_line or '"' in raw_line):
                    issues.append({
                        "file": file_path,
                        "line": idx,
                        "severity": "ERROR",
                        "code": "UsingOrInWhere",
                        "message": "Использование оператора ИЛИ в условии ГДЕ снижает производительность запроса (Стандарт 658)"
                    })

                if any(kw in up for kw in ["СГРУППИРОВАТЬ", "УПОРЯДОЧИТЬ", "ИТОГИ", "АВТОУПОРЯДОЧИВАНИЕ", "ОБЪЕДИНИТЬ", ";"]):
                    in_where = False

        if in_query and (';' in raw_line and '"' not in raw_line and not clean.startswith('|')):
            in_query = False
            in_where = False

    # 4. Проверка Если-ИначеЕсли без закрывающего Иначе
    for idx, raw_line in enumerate(lines, 1):
        if idx not in check_lines:
            continue
        clean_strip = raw_line.strip()
        if clean_strip.startswith("//"):
            continue
        if clean_strip.startswith("ИначеЕсли") or " ИначеЕсли " in raw_line:
            has_else = False
            nesting = 0
            for j in range(idx, min(idx + 120, total_lines)):
                sub_strip = lines[j].strip()
                if sub_strip.startswith("//"):
                    continue
                if sub_strip.startswith("Если ") or sub_strip.startswith("Если(") or sub_strip.startswith("Если\t"):
                    nesting += 1
                elif sub_strip.startswith("КонецЕсли"):
                    if nesting == 0:
                        break
                    nesting -= 1
                elif nesting == 0 and sub_strip.startswith("Иначе") and not sub_strip.startswith("ИначеЕсли"):
                    has_else = True
                    break
            if not has_else:
                issues.append({
                    "file": file_path,
                    "line": idx,
                    "severity": "ERROR",
                    "code": "MissingElse",
                    "message": "Конструкция Если-ИначеЕсли должна заканчиваться блоком Иначе (Стандарт 1С)"
                })

    # 5. Проверка глубины вложенности блоков (когнитивная сложность)
    current_proc = ""
    proc_line = 0
    max_indent = 0
    proc_in_target = False

    for idx, raw_line in enumerate(lines, 1):
        clean = raw_line.strip()
        if clean.startswith("Процедура ") or clean.startswith("Функция "):
            current_proc = clean.split('(')[0]
            proc_line = idx
            max_indent = 0
            proc_in_target = (idx in check_lines)
        elif clean.startswith("КонецПроцедуры") or clean.startswith("КонецФункции"):
            if proc_in_target and max_indent >= 5:
                issues.append({
                    "file": file_path,
                    "line": proc_line,
                    "severity": "ERROR",
                    "code": "CognitiveComplexity",
                    "message": f"Метод '{current_proc}' имеет высокую вложенность блоков ({max_indent} уровней). Рекомендуется декомпозиция (Стандарт 1С)"
                })
            current_proc = ""
            proc_in_target = False
        elif current_proc:
            if idx in check_lines:
                proc_in_target = True
            tabs = 0
            for ch in raw_line:
                if ch == '\t':
                    tabs += 1
                elif ch == ' ':
                    tabs += 0.25
                else:
                    break
            if int(tabs) > max_indent and any(clean.startswith(k) for k in ["Если ", "Пока ", "Для ", "Попытка"]):
                max_indent = int(tabs)

    return issues


def main():
    # Попытка получить автора из origami.config.json
    default_author = ""
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        if cur_dir not in sys.path:
            sys.path.insert(0, cur_dir)
        from origami_config import get_config
        cfg = get_config()
        default_author = cfg.get("project.authorShort", "")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Pure-Diff BSL Linter (Origami Platform)")
    parser.add_argument("--file", "-f", required=True, help="Путь к файлу .bsl для проверки")
    parser.add_argument("--lines", "-l", default="", help="Диапазон проверяемых строк (например: '10-25' или '10-25,40-60')")
    parser.add_argument("--author", "-a", default=default_author, help="Имя или маркер автора для фильтрации")
    parser.add_argument("--json", action="store_true", help="Вывод результатов в формате JSON")

    args = parser.parse_args()

    file_path = os.path.abspath(args.file)
    if not os.path.isfile(file_path):
        if args.json:
            print(json.dumps([{"severity": "ERROR", "message": f"Файл не найден: {file_path}"}], ensure_ascii=False))
        else:
            print(f"[!] Ошибка: Файл не найден: {file_path}", file=sys.stderr)
        sys.exit(2)

    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
    except Exception as e:
        if args.json:
            print(json.dumps([{"severity": "ERROR", "message": f"Ошибка чтения файла: {str(e)}"}], ensure_ascii=False))
        else:
            print(f"[!] Ошибка чтения файла: {e}", file=sys.stderr)
        sys.exit(2)

    target_lines = parse_line_ranges(args.lines)
    issues = lint_bsl_content(file_path, content, target_lines=target_lines, author=args.author)

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        rel_path = os.path.relpath(file_path, os.getcwd()) if file_path.startswith(os.getcwd()) else file_path
        if target_lines:
            scope_desc = f"строки {args.lines}"
        elif args.author:
            scope_desc = f"автор '{args.author}'"
        else:
            scope_desc = "весь файл"

        print(f"=== Pure-Diff BSL Linter (Origami Platform): {rel_path} [{scope_desc}] ===")

        if not issues:
            print("[OK] Замечаний по стандартам BSL не обнаружено.")
            sys.exit(0)

        print(f"[!] Обнаружено нарушений стандартов: {len(issues)}\n")
        for issue in issues:
            print(f"  {rel_path}:{issue['line']} [{issue['severity']}] {issue['code']}: {issue['message']}")

        print("\n[FAIL] Проверка завершилась с ошибками (Clean Zero нарушен).")

    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
