#!/usr/bin/env python3
"""Golden cases for DE-111 decedent street vs place of death.

Run: python -m unittest tests.test_de111_address
If a live PDF in _debug_de111 starts failing, fix the parser against these
text fixtures first so 3.a.(2) cannot be overwritten by 3c or at-(place).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from petition_parse import parse_de111_pdf, parse_de111_text, split_de111_address  # noqa: E402


CHRISTENSEN_3A2 = """
3. Decedent died on (date): January 22, 2026
at (place): Flathead County, Montana
(1)   a resident of the county named above.
(2) X a nonresident of California and left an estate in the county named above located at (specify location permitting
publication in the newspaper named in item 1 ):
856 Boulder Lane
Lincoln, CA 95678
c. Street address, city, and county of decedent's residence at time of death (specify):
150 Adams Street, Unit 7, Lakeside, Flathead County, Montana 59922
"""

NOVAK_3A2 = """
3. Decedent died on (date): 03/01/2026
at (place): Planesboro, NJ
(1)   a resident of the county named above.
(2) X a nonresident of California and left an estate in the county named above located at (specify):
324 B Street
Roseville, CA 95678
c. Street address, city, and county of decedent's residence at time of death (specify):
324 B Street, Roseville, Placer County, California 95678
"""

KIM_3C = """
3. Decedent died on (date): 06/15/2026
at (place): Lincoln, California
(1) X a resident of the county named above.
(2)   a nonresident of California and left an estate in the county named above located at (specify):
c. Street address, city, and county of decedent's residence at time of death (specify):
1728 6th Street, Lincoln, Placer County, California 95648
"""

BRAFFORD_3C = """
3. Decedent died on (date): 8/3/2025
at (place): Roseville, California
(1) X a resident of the county named above.
(2)   a nonresident of California and left an estate in the county named above located at (specify location permitting
publication in the newspaper named in item 1):
c. Street address, city, and county of decedent's residence at time of death (specify):
1206 Donahue Way, Roseville, Placer
Form Adopted for Mandatory Use PETITION FOR PROBATE
"""


class De111AddressContract(unittest.TestCase):
    def test_3a2_beats_place_of_death_and_3c(self):
        out = parse_de111_text(CHRISTENSEN_3A2)
        self.assertEqual(out.get("death_place"), "Flathead County, Montana")
        self.assertEqual(out.get("decedent_residence"), "856 Boulder Lane, Lincoln, CA 95678")
        self.assertEqual(out.get("decedent_address_source"), "3a2")
        self.assertNotIn("Flathead", out.get("decedent_residence") or "")
        self.assertNotIn("Adams", out.get("decedent_residence") or "")

    def test_3a2_roseville_estate(self):
        out = parse_de111_text(NOVAK_3A2)
        self.assertEqual(out.get("death_place"), "Planesboro, NJ")
        self.assertEqual(out.get("decedent_residence"), "324 B Street, Roseville, CA 95678")
        self.assertEqual(out.get("decedent_address_source"), "3a2")

    def test_3c_when_3a2_empty(self):
        out = parse_de111_text(KIM_3C)
        self.assertEqual(out.get("decedent_residence"), "1728 6th Street, Lincoln, CA 95648")
        self.assertEqual(out.get("decedent_address_source"), "3c")

    def test_3c_city_placer_without_state_or_zip(self):
        out = parse_de111_text(BRAFFORD_3C)
        self.assertEqual(out.get("death_place"), "Roseville, California")
        self.assertEqual(out.get("decedent_residence"), "1206 Donahue Way, Roseville, CA")
        self.assertEqual(out.get("decedent_city"), "Roseville")
        self.assertEqual(out.get("decedent_address_source"), "3c")

    def test_flathead_is_not_florida(self):
        parsed = split_de111_address(
            "150 Adams Street, Unit 7, Lakeside, Flathead County, Montana 59922"
        )
        self.assertEqual(parsed.get("state"), "MT")
        self.assertEqual(parsed.get("city"), "Lakeside")
        self.assertEqual(parsed.get("zip"), "59922")

    def test_placer_is_not_pennsylvania(self):
        parsed = split_de111_address(
            "1206 Donahue Way, Roseville, Placer County, California 95661"
        )
        self.assertEqual(parsed.get("state"), "CA")
        self.assertEqual(parsed.get("city"), "Roseville")


class De111PdfGoldens(unittest.TestCase):
    """Optional: real PDFs in _debug_de111. Skipped when those files are absent."""

    def _pdf(self, name: str) -> Path | None:
        path = ROOT / "_debug_de111" / name
        return path if path.is_file() else None

    def test_14446_uses_3a2(self):
        path = self._pdf("S-PR-0014446_DE-111.pdf")
        if not path:
            self.skipTest("debug PDF not present")
        out = parse_de111_pdf(path)
        self.assertIn("324 B Street", out.get("decedent_residence") or "")
        self.assertEqual(out.get("decedent_address_source"), "3a2")
        self.assertEqual(out.get("death_place"), "Planesboro, NJ")

    def test_14448_uses_3c_lincoln_not_henderson(self):
        path = self._pdf("S-PR-0014448_DE-111.pdf")
        if not path:
            self.skipTest("debug PDF not present")
        out = parse_de111_pdf(path)
        self.assertIn("1728 6th Street", out.get("decedent_residence") or "")
        self.assertIn("Lincoln", out.get("decedent_residence") or "")
        self.assertNotIn("Henderson", out.get("decedent_residence") or "")

    def test_14195_uses_3a2_not_garbled_place(self):
        path = self._pdf("S-PR-0014195_DE-111.pdf")
        if not path:
            self.skipTest("debug PDF not present")
        out = parse_de111_pdf(path)
        self.assertIn("8300 Country Club Lane", out.get("decedent_residence") or "")
        self.assertEqual(out.get("decedent_address_source"), "3a2")

    def test_14204_3c_donahue_way(self):
        path = self._pdf("S-PR-0014204_DE-111.pdf")
        if not path:
            self.skipTest("debug PDF not present")
        out = parse_de111_pdf(path)
        self.assertIn("1206 Donahue Way", out.get("decedent_residence") or "")
        self.assertIn("Roseville", out.get("decedent_residence") or "")
        self.assertEqual(out.get("decedent_address_source"), "3c")
        self.assertEqual(out.get("death_place"), "Roseville, California")


if __name__ == "__main__":
    unittest.main()
