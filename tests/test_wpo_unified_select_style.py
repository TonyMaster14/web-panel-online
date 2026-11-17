"""Visual-only dropdown consistency checks for WPO (no VPN behavior changes)."""
import importlib.util
from pathlib import Path
import re
import sys
import types
import unittest

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT / "src" / "wpp_ui.py"
# The module contains several optional integrations; these source-level tests
# verify selectors rather than requiring live server services.

class UnifiedSelectStyleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=SRC.read_text(encoding="utf-8")
        cls.block=cls.source.split("# wpo-reality-picker-unified-select-v1:")[-1]

    def test_four_requested_surfaces_are_styled(self):
        for selector in (
            "#connectionProtocol",
            "#clientFilter", "#protocolFilter", "#clientSort",
            "dialog select",  # Covers node template selector even if modal ID changes.
            "#panelRelease", "#xrayRelease", "#openfluxRelease",
        ):
            with self.subTest(selector=selector):
                self.assertIn(selector,self.block)

    def test_matches_reality_picker_single_border(self):
        self.assertIn("height:41px",self.block)
        self.assertIn("border:1px solid var(--line)",self.block)
        self.assertIn("border-radius:10px",self.block)
        self.assertIn("background-color:var(--input)",self.block)
        self.assertIn("appearance:none",self.block)
        self.assertIn("background-repeat:no-repeat",self.block)

    def test_no_edit_of_protocol_and_subscription_behavior(self):
        self.assertEqual(self.source.count("# wpo-reality-picker-unified-select-v1"),1)
        self.assertNotIn("addEventListener(",self.block)
        self.assertNotIn("fetch(",self.block)
        self.assertNotIn("systemctl",self.block)
        self.assertNotIn("xray",self.block.lower().replace("#xrayrelease",""))
        self.assertIn("option",self.block)

    def test_current_ui_has_matching_native_selects(self):
        for tag in (
            'id="connectionProtocol"',
            'id="clientFilter"', 'id="protocolFilter"', 'id="clientSort"',
            'id="panelRelease"', 'id="xrayRelease"', 'id="openfluxRelease"',
        ):
            with self.subTest(tag=tag):
                self.assertIn(tag,self.source)

if __name__=="__main__":
    unittest.main()
