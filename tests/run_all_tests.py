# -*- coding: utf-8 -*-
"""
Origami Kernel — Unified Test Runner.
Executes all unit and regression tests for kernel tools.
Pure Python standard library (unittest). OPCES-1.1 compliant.
"""

import sys
import unittest
from pathlib import Path

# Ensure UTF-8 output on Windows
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

TESTS_DIR = Path(__file__).resolve().parent


def run_all() -> bool:
    print("==============================================================================")
    print("                 ORIGAMI KERNEL — ТЕСТОВЫЙ НАБОР ЯДРА")
    print("==============================================================================")
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(TESTS_DIR), pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print("==============================================================================")
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
