# -*- coding: utf-8 -*-
"""
Origami Kernel — Unit Tests for Repository Standards Linter (lint_kernel.py).
Standard library unittest. OPCES-1.1 compliant.
"""

import sys
import unittest
import tempfile
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from lint_kernel import check_encodings, check_content


class TestLintKernel(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_ps1_requires_bom_and_header(self):
        # 1. ps1 without BOM -> violation
        bad_ps1 = self.dir_path / "bad.ps1"
        bad_ps1.write_bytes(b"Write-Host 'Hello'")
        v = check_encodings(bad_ps1)
        self.assertTrue(any(item.category == "ENCODING" for item in v))

        # 2. ps1 with BOM but without <# header -> violation
        bom_no_header = self.dir_path / "no_header.ps1"
        bom_no_header.write_bytes(b"\xef\xbb\xbfWrite-Host 'Hello'")
        v = check_encodings(bom_no_header)
        self.assertTrue(any(item.category == "PS1_SYNTAX" for item in v))

        # 3. ps1 with BOM and <# header -> clean
        valid_ps1 = self.dir_path / "valid.ps1"
        valid_ps1.write_bytes(b"\xef\xbb\xbf<#\n.SYNOPSIS\n#>\nWrite-Host 'Hello'")
        v = check_encodings(valid_ps1)
        self.assertEqual(len(v), 0)

    def test_py_and_json_must_not_have_bom(self):
        bad_py = self.dir_path / "bad.py"
        bad_py.write_bytes(b"\xef\xbb\xbfprint('hello')")
        v = check_encodings(bad_py)
        self.assertTrue(any("не должен содержать UTF-8 BOM" in item.message for item in v))

        valid_py = self.dir_path / "valid.py"
        valid_py.write_bytes(b"print('hello')")
        v = check_encodings(valid_py)
        self.assertEqual(len(v), 0)

    def test_double_bom_detected(self):
        double_bom = self.dir_path / "corrupt.txt"
        double_bom.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbfCorrupted content")
        v = check_encodings(double_bom)
        self.assertTrue(any("двойной UTF-8 BOM" in item.message for item in v))


if __name__ == "__main__":
    unittest.main()
