# -*- coding: utf-8 -*-
"""
Origami Kernel — Unit Tests for Configuration Access Layer (origami_config.py).
Standard library unittest. OPCES-1.1 compliant.
"""

import os
import sys
import unittest
import tempfile
import json
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from origami_config import OrigamiConfig, load_env_file


class TestOrigamiConfig(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_default_fallback_without_config_file(self):
        cfg = OrigamiConfig(self.root_path / "non_existent.json")
        self.assertEqual(cfg.get("origami.name"), "Origami Kernel")
        self.assertEqual(cfg.get("project.prefix"), "ext_")
        self.assertEqual(cfg.get("non.existent.path", "default_val"), "default_val")

    def test_dot_notation_retrieval(self):
        cfg_file = self.root_path / "origami.config.json"
        data = {
            "origami": {"version": "1.2.0"},
            "project": {"prefix": "ext_", "extensionName": "MyExtension"},
            "infobase": {"type": "file", "path": "D:\\test"}
        }
        cfg_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        cfg = OrigamiConfig(cfg_file)
        self.assertEqual(cfg.get("origami.version"), "1.2.0")
        self.assertEqual(cfg.get("project.extensionName"), "MyExtension")
        self.assertEqual(cfg.get("infobase.path"), "D:\\test")

    def test_load_env_file_zero_leak(self):
        env_file = self.root_path / ".env"
        env_file.write_text("TEST_ORIGAMI_VAR=test_value_123\n# Comment\nANOTHER_VAR='quoted'\n", encoding="utf-8")

        # Ensure env is loaded
        load_env_file([self.root_path])
        self.assertEqual(os.environ.get("TEST_ORIGAMI_VAR"), "test_value_123")
        self.assertEqual(os.environ.get("ANOTHER_VAR"), "quoted")

        # Clean up process env
        os.environ.pop("TEST_ORIGAMI_VAR", None)
        os.environ.pop("ANOTHER_VAR", None)


if __name__ == "__main__":
    unittest.main()
