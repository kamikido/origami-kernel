# -*- coding: utf-8 -*-
"""
Origami Negative Control Engine — Механизм аппаратного отрицательного контроля линтера.
Проверяет зоркость анализатора BSL на синтетической фикстуре с эталонными дефектами
по стандартам 1С и классификации BSL Language Server до допуска к боевому анализу.
Чистая стандартная библиотека Python.
"""

import sys
import os
import re
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Set, Tuple, Optional

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

# Подключаем каталог tools в sys.path
CUR_DIR = Path(__file__).resolve().parent
if str(CUR_DIR) not in sys.path:
    sys.path.insert(0, str(CUR_DIR))

# Эталонная матрица ожидаемых дефектов отрицательного контроля
EXPECTED_DEFECTS: Dict[str, str] = {
    "LineLength": "Стандарт 456 (Визуальная длина строки > 120 символов)",
    "DeprecatedError": "Стандарт БСП (Устаревший вызов ПодробноеПредставлениеОшибки)",
    "UsingOrInWhere": "Стандарт 658 (Использование ИЛИ в секции ГДЕ запроса)",
    "UnionWithoutAll": "Стандарт 434 (Использование ОБЪЕДИНИТЬ без ВСЕ в запросе)",
    "MissingElse": "Строгий режим (Ветка Если-ИначеЕсли без блока Иначе)",
    "CognitiveComplexity": "Стандарт 1С (Высокая когнитивная сложность / вложенность блоков >= 5)"
}


def find_default_fixture() -> Optional[Path]:
    """Ищет эталонную синтетическую фикстуру в стандартных путях ядра."""
    root_dir = CUR_DIR.parent
    candidates = [
        root_dir / "tests" / "fixtures" / "negative_control_synthetic.bsl",
        CUR_DIR / "fixtures" / "negative_control_synthetic.bsl",
        Path.cwd() / "tests" / "fixtures" / "negative_control_synthetic.bsl"
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def run_negative_control(
    fixture_path: Optional[str] = None,
    verbose: bool = False
) -> Tuple[bool, Dict[str, Any]]:
    """
    Выполняет отрицательный контроль линтера на эталонной синтетической фикстуре.
    Возвращает (is_healthy, report_dict).
    """
    if fixture_path:
        f_path = Path(fixture_path)
    else:
        f_path = find_default_fixture()

    if not f_path or not f_path.is_file():
        return False, {
            "status": "CRITICAL_ERROR",
            "message": f"Файл синтетической фикстуры не найден: {f_path}",
            "exit_code": 2,
            "detected": [],
            "missing": list(EXPECTED_DEFECTS.keys()),
            "unexpected": []
        }

    # Пытаемся импортировать линтер напрямую для быстродействия (< 5 мс)
    try:
        from lint_bsl_diff import lint_bsl_content
    except ImportError:
        # Fallback: пробуем динамическую загрузку
        lint_file = CUR_DIR / "lint_bsl_diff.py"
        if not lint_file.is_file():
            return False, {
                "status": "CRITICAL_ERROR",
                "message": f"Модуль lint_bsl_diff.py не найден по пути: {lint_file}",
                "exit_code": 2,
                "detected": [],
                "missing": list(EXPECTED_DEFECTS.keys()),
                "unexpected": []
            }
        import importlib.util
        spec = importlib.util.spec_from_file_location("lint_bsl_diff", str(lint_file))
        lint_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(lint_module)
        lint_bsl_content = lint_module.lint_bsl_content

    # Читаем содержимое фикстуры
    try:
        content = f_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return False, {
            "status": "CRITICAL_ERROR",
            "message": f"Ошибка чтения фикстуры: {e}",
            "exit_code": 2,
            "detected": [],
            "missing": list(EXPECTED_DEFECTS.keys()),
            "unexpected": []
        }

    # Запускаем анализ содержимого со строгим режимом (strict_else=True)
    try:
        issues = lint_bsl_content(
            file_path=str(f_path),
            content=content,
            target_lines=None,
            author=None,
            tab_width=4,
            strict_else=True
        )
    except Exception as e:
        return False, {
            "status": "LINTER_CRASH",
            "message": f"Критический сбой анализатора при проверке фикстуры: {e}",
            "exit_code": 2,
            "detected": [],
            "missing": list(EXPECTED_DEFECTS.keys()),
            "unexpected": []
        }

    detected_codes = {issue.get("code") for issue in issues if issue.get("code")}
    expected_set = set(EXPECTED_DEFECTS.keys())

    missing = sorted(list(expected_set - detected_codes))
    unexpected = sorted(list(detected_codes - expected_set))

    is_healthy = (len(missing) == 0 and len(unexpected) == 0)

    report = {
        "status": "PASSED" if is_healthy else "BLINDNESS_DETECTED",
        "fixture": str(f_path),
        "total_expected": len(expected_set),
        "total_detected": len(detected_codes),
        "detected": sorted(list(detected_codes)),
        "missing": missing,
        "unexpected": unexpected,
        "issues": issues if verbose else [],
        "exit_code": 0 if is_healthy else 1
    }

    return is_healthy, report


def main():
    parser = argparse.ArgumentParser(
        description="Origami Negative Control Engine — Аппаратный отрицательный контроль зоркости линтера BSL."
    )
    parser.add_argument("--fixture", help="Путь к синтетической фикстуре с эталонными дефектами")
    parser.add_argument("--json", action="store_true", help="Вывод отчета в формате JSON")
    parser.add_argument("--verbose", "-v", action="store_true", help="Подробный вывод найденных замечаний")
    parser.add_argument("--strict", action="store_true", help="Строгий режим: падать с exit code 2 при любых отклонениях")

    args = parser.parse_args()

    is_healthy, report = run_negative_control(fixture_path=args.fixture, verbose=args.verbose)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        sys.exit(report.get("exit_code", 0))

    print("=== Origami Platform: Механизм отрицательного контроля (Negative Control) ===")
    print(f"[*] Синтетическая фикстура: {report.get('fixture', 'Н/Д')}")
    print(f"[*] Проверено стандартов BSL: {report.get('total_expected', 0)}")
    print(f"[*] Обнаружено дефектов:     {report.get('total_detected', 0)}")

    if is_healthy:
        print("\n[OK] Отрицательный контроль успешно пройден!")
        print("     Анализатор Pure-Diff BSL на 100% зряч и детектирует все эталонные классы дефектов.")
        for code in report.get("detected", []):
            desc = EXPECTED_DEFECTS.get(code, "Пользовательский стандарт")
            print(f"     + [Пойман] {code}: {desc}")
        sys.exit(0)
    else:
        print("\n[CRITICAL FAIL] ОТРИЦАТЕЛЬНЫЙ КОНТРОЛЬ НЕ ПРОЙДЕН! ЛИНТЕР ОСЛЕП!")
        if report.get("status") == "CRITICAL_ERROR" or report.get("status") == "LINTER_CRASH":
            print(f"     [!] Ошибка среды: {report.get('message')}")
            sys.exit(2)

        if report.get("missing"):
            print("     [!] Пропущенные обязательные дефекты (линтер не видит нарушения):")
            for code in report["missing"]:
                desc = EXPECTED_DEFECTS.get(code, "Неизвестный стандарт")
                print(f"       - [ПРОПУСК] {code}: {desc}")

        if report.get("unexpected"):
            print("     [!] Обнаружены непредвиденные дефекты (ложные срабатывания):")
            for code in report["unexpected"]:
                print(f"       ? [ЛОЖНОЕ] {code}")

        print("\n[BLOCKED] Анализ боевого кода заблокирован до восстановления зоркости линтера.")
        exit_code = 2 if args.strict else report.get("exit_code", 1)
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
