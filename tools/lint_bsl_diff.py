# -*- coding: utf-8 -*-
"""
Pure-Diff BSL Linter — Авторский статический анализатор стандартов 1С (платформа 8.3 / 8.5).
Часть платформенного каркаса Origami Platform.

Принципы Pure-Diff анализа:
1. Изоляция: Проверяются СТРОГО добавленные/измененные строки (Green Hunks).
2. Амнистия R-003: Закомментированный чужой код в блоках удаления // { - ... } амнистирован.
3. Eye-Only Policy: Окружающий легаси-код защищен от проверок.
4. Учет табов: Вычисление длины строки с учетом визуальной ширины таба в Конфигураторе 1С (tab-width=4).
5. Разделение кодов возврата:
   - 0: Замечаний не обнаружено (Clean Zero)
   - 1: Обнаружены нарушения стандартов качества BSL
   - 2: Системная ошибка выполнения (файл не найден, ошибка разбора, сбой среды)
"""

import sys
import os
import re
import argparse
import json
import subprocess
from typing import Set, Tuple, List, Dict, Any

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


def get_visual_line_length(line: str, tab_width: int = 4) -> int:
    """Вычисляет визуальную длину строки в колонках Конфигуратора 1С."""
    return len(line.expandtabs(tab_width))


def parse_line_ranges(ranges_str: str) -> Set[int]:
    """Разбирает строку диапазонов: '10-25' или '10-25,40-60' или '15' в множество номеров строк."""
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


def get_git_changed_lines(file_path: str, ref: str = "HEAD") -> Set[int]:
    """Извлекает номера добавленных/измененных строк (Green Hunks) напрямую через git diff."""
    changed_lines = set()
    try:
        cmd = ["git", "diff", "-U0", ref, "--", file_path]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            return changed_lines

        # Парсим diff hunks: @@ -a,b +start,count @@ или @@ -a,b +start @@
        hunk_pattern = re.compile(r'^@@\s+-[0-9]+(?:,[0-9]+)?\s+\+([0-9]+)(?:,([0-9]+))?\s+@@')
        current_line = 0

        for line in res.stdout.splitlines():
            m = hunk_pattern.match(line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                current_line = start
                if count > 0:
                    changed_lines.update(range(start, start + count))
    except Exception:
        pass

    return changed_lines


def find_author_green_lines(lines: List[str], author_marker: str) -> Tuple[Set[int], Set[int]]:
    """
    Определяет номера строк, добавленных автором по регламенту:
    // { + ЛС ... } или // + ...
    А также амнистированные строки удаления: // { - ... }
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


def lint_bsl_content(
    file_path: str,
    content: str,
    target_lines: Set[int] = None,
    author: str = "",
    tab_width: int = 4,
    strict_else: bool = False
) -> List[Dict[str, Any]]:
    """Выполняет Pure-Diff статический анализ BSL кода."""
    lines = content.splitlines(True)
    total_lines = len(lines)

    # 1. Определение амнистированных строк (Red Hunks // { - ... })
    author_green, amnestied_lines = find_author_green_lines(lines, author)

    if not target_lines:
        if author_green:
            check_lines = author_green
        else:
            check_lines = set(range(1, total_lines + 1))
    else:
        check_lines = target_lines

    # Исключаем амнистированные строки удаления
    check_lines = check_lines - amnestied_lines
    issues = []

    # 1. Проверка визуальной длины строки (Стандарт 456, с учетом ширины таба)
    for idx, raw_line in enumerate(lines, 1):
        if idx not in check_lines:
            continue
        clean_line = raw_line.rstrip('\r\n')
        vis_len = get_visual_line_length(clean_line, tab_width=tab_width)
        if vis_len > 120:
            issues.append({
                "file": file_path,
                "line": idx,
                "severity": "ERROR",
                "code": "LineLength",
                "message": f"Визуальная длина строки {vis_len} (таб={tab_width}) превышает допустимую 120 (Стандарт 456)"
            })

    # 2. Проверка устаревшего метода ПодробноеПредставлениеОшибки
    for idx, raw_line in enumerate(lines, 1):
        if idx not in check_lines:
            continue
        if "ПодробноеПредставлениеОшибки" in raw_line and "ОбработкаОшибок." not in raw_line:
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

        if clean.startswith("//"):
            continue

        if "ВЫБРАТЬ" in up and ('"' in raw_line or '|' in raw_line):
            in_query = True

        if in_query:
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

    # 4. Проверка Если-ИначеЕсли без закрывающего Иначе (Строгий режим)
    if strict_else:
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
                        "severity": "WARNING",
                        "code": "MissingElse",
                        "message": "Ветка Если-ИначеЕсли не содержит завершающего блока Иначе"
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
    parser.add_argument("--git-diff", "-g", nargs="?", const="HEAD", default=None, help="Автоматически извлечь измененные строки из git diff (опционально: git ref, по умолчанию HEAD)")
    parser.add_argument("--author", "-a", default=default_author, help="Имя или маркер автора для фильтрации")
    parser.add_argument("--tab-width", type=int, default=4, help="Визуальная ширина знака табуляции в колонках Конфигуратора (по умолчанию: 4)")
    parser.add_argument("--strict-else", action="store_true", default=False, help="Включить строгий контроль блока Иначе в конструкциях Если-ИначеЕсли")
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

    # Определение проверяемых строк
    target_lines = set()
    if args.git_diff is not None:
        target_lines = get_git_changed_lines(file_path, ref=args.git_diff)
    elif args.lines:
        target_lines = parse_line_ranges(args.lines)

    issues = lint_bsl_content(
        file_path,
        content,
        target_lines=target_lines,
        author=args.author,
        tab_width=args.tab_width,
        strict_else=args.strict_else
    )

    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        rel_path = os.path.relpath(file_path, os.getcwd()) if file_path.startswith(os.getcwd()) else file_path
        if args.git_diff is not None:
            scope_desc = f"git diff {args.git_diff} ({len(target_lines)} строк)"
        elif target_lines:
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

    # Код выхода 1 только при наличии реальных замечаний
    sys.exit(1 if any(i.get("severity") == "ERROR" for i in issues) else 0)


if __name__ == "__main__":
    main()
