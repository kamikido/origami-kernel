# -*- coding: utf-8 -*-
"""
Origami Kernel — Unit Tests for Negative Control Engine (negative_control.py).
Standard library unittest. OPCES-1.1 compliant.
"""

import sys
import tempfile
import unittest
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from negative_control import (
    run_negative_control,
    EXPECTED_DEFECTS,
    find_default_fixture
)


class TestNegativeControl(unittest.TestCase):

    def test_default_fixture_exists(self):
        fixture = find_default_fixture()
        self.assertIsNotNone(fixture, "Эталонная синтетическая фикстура должна быть найдена в репозитории")
        self.assertTrue(fixture.is_file(), f"Файл фикстуры должен существовать: {fixture}")

    def test_negative_control_passes_on_synthetic_fixture(self):
        is_healthy, report = run_negative_control()
        self.assertTrue(is_healthy, f"Отрицательный контроль должен успешно пройти на эталонной фикстуре. Отчет: {report}")
        self.assertEqual(report["status"], "PASSED")
        self.assertEqual(report["total_expected"], 6)
        self.assertEqual(report["total_detected"], 6)
        self.assertEqual(len(report["missing"]), 0)
        self.assertEqual(len(report["unexpected"]), 0)

        # Все ожидаемые коды должны присутствовать
        for code in EXPECTED_DEFECTS.keys():
            self.assertIn(code, report["detected"])

    def test_negative_control_detects_blindness_when_defect_missing(self):
        # Создаем временную фикстуру, в которой удален дефект LineLength
        default_fixture = find_default_fixture()
        original_content = default_fixture.read_text(encoding="utf-8")

        # Убираем длинную строку
        lines = original_content.splitlines()
        filtered_lines = [l for l in lines if "ДлиннаяСтрокаКомментария" not in l]
        incomplete_content = "\n".join(filtered_lines)

        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", suffix=".bsl", delete=False) as tf:
            tf.write(incomplete_content)
            temp_path = tf.name

        try:
            is_healthy, report = run_negative_control(fixture_path=temp_path)
            self.assertFalse(is_healthy, "Отрицательный контроль обязан зафиксировать ослепление линтера при отсутствии дефекта")
            self.assertEqual(report["status"], "BLINDNESS_DETECTED")
            self.assertIn("LineLength", report["missing"])
            self.assertEqual(report["exit_code"], 1)
        finally:
            Path(temp_path).unlink(missing_ok=True)

    def test_negative_control_handles_missing_fixture_file(self):
        non_existent = "non_existent_negative_fixture_12345.bsl"
        is_healthy, report = run_negative_control(fixture_path=non_existent)
        self.assertFalse(is_healthy)
        self.assertEqual(report["status"], "CRITICAL_ERROR")
        self.assertEqual(report["exit_code"], 2)


if __name__ == "__main__":
    unittest.main()
