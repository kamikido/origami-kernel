# -*- coding: utf-8 -*-
"""
Тесты Origami Form Studio (Фаза 3, OPCES-1.1).
Проверка парсера OF-DSL, линтера ИТС (Box-Model), генератора XML, BSL-инжектора и предпросмотра.
"""

import unittest
from pathlib import Path
import sys

# Подключаем tools к sys.path
tools_dir = Path(__file__).resolve().parent.parent / "tools"
if str(tools_dir) not in sys.path:
    sys.path.insert(0, str(tools_dir))

from form_studio import (
    load_dsl,
    ITSLayoutLinter,
    FormXMLSynthesizer,
    BSLInjectionSynthesizer,
    HeadlessWireframeRenderer
)


class TestFormStudio(unittest.TestCase):

    def setUp(self):
        self.fixtures_dir = Path(__file__).resolve().parent / "fixtures"
        self.sample_dsl = self.fixtures_dir / "sample_wizard.yaml"
        self.tpl_dir = Path(__file__).resolve().parent.parent / "templates" / "forms"

    def test_sample_dsl_lint_passes(self):
        dsl = load_dsl(self.sample_dsl)
        linter = ITSLayoutLinter(dsl)
        violations = linter.run_all_checks()
        errors = [v for v in violations if v.severity == "ERROR"]
        self.assertEqual(len(errors), 0, f"Ожидалось 0 ошибок, получено: {errors}")

    def test_multiline_without_height_fails_linter(self):
        bad_dsl = {
            "archetype": "wizard",
            "state": {
                "Комментарий": {"type": "str", "multiline": True} # нет height!
            },
            "actions": [{"Далее": {"title": "Далее >"}}]
        }
        linter = ITSLayoutLinter(bad_dsl)
        violations = linter.run_all_checks()
        err_rules = [v.rule_id for v in violations if v.severity == "ERROR"]
        self.assertIn("ITS-02-MULTILINE-HEIGHT", err_rules)

    def test_multiple_stretch_masters_fails_linter(self):
        bad_dsl = {
            "archetype": "wizard",
            "state": {
                "Таблица1": {"type": "table", "stretch": True},
                "Таблица2": {"type": "table", "stretch": True}
            },
            "actions": [{"Далее": {"title": "Далее >"}}]
        }
        linter = ITSLayoutLinter(bad_dsl)
        violations = linter.run_all_checks()
        err_rules = [v.rule_id for v in violations if v.severity == "ERROR"]
        self.assertIn("ITS-01-STRETCH-MASTER", err_rules)

    def test_form_xml_synthesis(self):
        dsl = load_dsl(self.sample_dsl)
        synth = FormXMLSynthesizer(dsl, self.tpl_dir)
        xml = synth.build_xml()
        self.assertIn('<Form xmlns="http://v8.1c.ru/8.3/xcf/logform"', xml)
        self.assertIn('<InputField name="Поставщик"', xml)
        self.assertIn('<ExtendedTooltip name="ПоставщикРасширеннаяПодсказка"', xml)
        self.assertIn('<ContextMenu name="ПоставщикКонтекстноеМеню"', xml)
        self.assertIn('<Attribute name="Поставщик"', xml)
        self.assertIn('d5p1:CatalogRef.Контрагенты', xml)

    def test_bsl_injection_synthesis(self):
        dsl = load_dsl(self.sample_dsl)
        bsl_synth = BSLInjectionSynthesizer(dsl)
        bsl = bsl_synth.build_bsl()
        self.assertIn('&После("ПриСозданииНаСервере")', bsl)
        self.assertIn('ИзменитьРеквизиты(РеквизитыДляДобавления);', bsl)
        self.assertIn('Элементы.Добавить("САА_Поставщик", Тип("ПолеФормы")', bsl)
        self.assertIn('ИмяКонтейнера = "САА_ГруппаКонтейнер_Origami";', bsl)
        self.assertIn('Если Элементы.Найти(ИмяКонтейнера) <> Неопределено Тогда', bsl)

    def test_preview_html_synthesis(self):
        dsl = load_dsl(self.sample_dsl)
        renderer = HeadlessWireframeRenderer(dsl)
        html = renderer.render()
        self.assertIn('<!DOCTYPE html>', html)
        self.assertIn('onec-window', html)
        self.assertIn('onec-btn primary', html)
        self.assertIn('Поставщик', html)


if __name__ == "__main__":
    unittest.main()
