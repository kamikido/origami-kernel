# -*- coding: utf-8 -*-
"""
Origami Kernel — Unit Tests for Pure-Diff BSL Linter (lint_bsl_diff.py).
Standard library unittest. OPCES-1.1 compliant.
"""

import sys
import unittest
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from lint_bsl_diff import (
    lint_bsl_content,
    get_visual_line_length,
    parse_line_ranges
)


class TestLintBslDiff(unittest.TestCase):

    def test_visual_line_length_with_tabs(self):
        # 10 chars + 1 tab (4 cols) = 14 cols
        raw = "1234567890\tABC"
        vis_len = get_visual_line_length(raw, tab_width=4)
        self.assertEqual(vis_len, 15)  # 10 + (4 - 10%4 = 2) + 3 = 15

    def test_line_length_error(self):
        # Line > 120 chars
        long_line = "Перем_А = " + ("1234567890" * 12) + ";"
        code = f"Процедура Тест()\n\t{long_line}\nКонецПроцедуры\n"
        issues = lint_bsl_content("test.bsl", code)
        self.assertTrue(any(i["code"] == "LineLength" for i in issues))

    def test_amnestied_deletion_block(self):
        # Code in deletion block // { - ... } must NOT produce errors even if > 120 chars
        code = """Процедура Тест()
// { - 14.11.2026 Устаревший код удален
\tДлиннаяСтрока = """ + ("\"ABCDEFGHIJ\" + " * 15) + """\"\";
// }
\tКороткая = 1;
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code)
        self.assertEqual(len(issues), 0)

    def test_using_or_in_where_detected(self):
        code = """Процедура ВыполнитьЗапрос()
\tЗапрос = Новый Запрос;
\tЗапрос.Текст = 
\t\t"ВЫБРАТЬ
\t\t|	Ссылка
\t\t|ИЗ
\t\t|	Справочник.Номенклатура
\t\t|ГДЕ
\t\t|	(ЭтоГруппа ИЛИ ПометкаУдаления)";
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code)
        self.assertTrue(any(i["code"] == "UsingOrInWhere" for i in issues))

    def test_bsl_if_or_not_flagged_as_sql_where(self):
        code = """Процедура Тест()
\t// Обычное ветвление BSL не должно считаться ошибкой Стандарта 658
\tЕсли Режим = 1 ИЛИ Режим = 2 Тогда
\t\tСообщить("Режим валиден");
\tКонецЕсли;
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code)
        self.assertFalse(any(i["code"] == "UsingOrInWhere" for i in issues))

    def test_union_without_all_detected(self):
        code = """Процедура Тест()
\tЗапрос = Новый Запрос;
\tЗапрос.Текст = 
\t\t"ВЫБРАТЬ Ссылка ИЗ Документ.Реализация
\t\t|ОБЪЕДИНИТЬ
\t\t|ВЫБРАТЬ Ссылка ИЗ Документ.Поступление";
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code)
        self.assertTrue(any(i["code"] == "UnionWithoutAll" for i in issues))

    def test_deprecated_error_method(self):
        code = """Процедура Обработать()
\tПопытка
\t\tВызватьИсключение "Ошибка";
\tИсключение
\t\tТекст = ПодробноеПредставлениеОшибки(ИнформацияОбОшибке());
\tКонецПопытки;
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code)
        self.assertTrue(any(i["code"] == "DeprecatedError" for i in issues))

    def test_strict_else_missing_warning(self):
        code = """Процедура Тест(Вид)
\tЕсли Вид = 1 Тогда
\t\tДействие1();
\tИначеЕсли Вид = 2 Тогда
\t\tДействие2();
\tКонецЕсли;
КонецПроцедуры
"""
        issues = lint_bsl_content("test.bsl", code, strict_else=True)
        self.assertTrue(any(i["code"] == "MissingElse" for i in issues))

    def test_zero_diff_lines_isolation(self):
        # Even if file has errors, if target_lines is empty set(), 0 issues must be reported
        code = "Перем_А = " + ("1234567890" * 15) + ";\n"
        issues = lint_bsl_content("test.bsl", code, target_lines=set())
        self.assertEqual(len(issues), 0)


if __name__ == "__main__":
    unittest.main()
