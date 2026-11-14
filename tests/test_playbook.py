# -*- coding: utf-8 -*-
"""
Origami Kernel — Unit Tests for Playbook Manager (playbook.py).
Standard library unittest. OPCES-1.1 compliant.
"""

import sys
import unittest
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from playbook import get_playbooks_dir, list_playbooks, find_playbooks


class TestPlaybookManager(unittest.TestCase):

    def test_playbooks_directory_exists(self):
        pb_dir = get_playbooks_dir()
        self.assertTrue(pb_dir.exists())

    def test_registered_playbooks_discovered(self):
        pb_dir = get_playbooks_dir()
        pbs = list_playbooks(pb_dir)
        self.assertGreater(len(pbs), 0, "Должен быть зарегистрирован как минимум один плейбук")
        for pb in pbs:
            self.assertIn("id", pb)
            self.assertIn("title", pb)
            self.assertIn("purpose", pb)
            self.assertIn("invariants", pb)

    def test_find_playbooks_by_keyword(self):
        pb_dir = get_playbooks_dir()
        results = find_playbooks("1C", pb_dir)
        # Should return playbooks or empty list without exceptions
        self.assertIsInstance(results, list)


if __name__ == "__main__":
    unittest.main()
