"""DE-111 item 2.b professional fiduciary skips Go/FUB export."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from fub_client import gate_reason  # noqa: E402
from petition_parse import parse_de111_text  # noqa: E402

MAPPING = {"skip_petitioner_contains": [], "custom_fields": {}, "send": {}}

# Snippet from a live DE-111 extract (item 2 only). Do not check in the court PDF.
BALLESTEROS_ITEM2 = """
2. Petitioner (name each): Anna Ballesteros
requests that
a. decedent's will and codicils, if any, be admitted to probate.
b. (name): Anna Ballesteros, Professional Fiduciary be appointed
(1) executor
(2) administrator with will annexed
(3) x administrator
and Letters issue upon qualification.
3. a. Decedent died on (date): 05/31/2026 at (place): Residence
"""

NORMAL_ITEM2 = """
2. Petitioner (name each): John Henderson
requests that
a. decedent's will and codicils, if any, be admitted to probate.
b. (name): John Henderson be appointed
(1) executor
(2) administrator with will annexed
(3) x administrator
and Letters issue upon qualification.
3. a. Decedent died on (date): 05/31/2026 at (place): Residence
"""

CAPTION_ONLY = """
ATTORNEY OR PARTY WITHOUT ATTORNEY
Anna Ballesteros, Professional Fiduciary
STREET ADDRESS: 123 Main St
ATTORNEY FOR (name): Petitioner
2. Petitioner (name each): John Henderson
requests that
a. decedent's will and codicils, if any, be admitted to probate.
b. (name): John Henderson be appointed
(3) x administrator
and Letters issue upon qualification.
3. a. Decedent died on (date): 05/31/2026 at (place): Residence
"""

PETITIONER_LINE_SAME_PERSON = """
2. Petitioner (name each): Anna Ballesteros, Professional Fiduciary
requests that
a. decedent's will and codicils, if any, be admitted to probate.
b. (name): Anna Ballesteros be appointed
(3) x administrator
and Letters issue upon qualification.
3. a. Decedent died on (date): 05/31/2026 at (place): Residence
"""


def _row(**extra):
    row = {
        "source_id": "sacramento",
        "case_number": "26PR001581",
        "petitioner": "Anna Ballesteros",
        "mailing_address": "123 Main St, Sacramento, CA 95814",
        "decedent_residence": "6728 Flaming Arrow Dr, Citrus Heights, CA 95621",
    }
    row.update(extra)
    return row


class ProfessionalFiduciaryParseTests(unittest.TestCase):
    def test_item2b_professional_fiduciary(self):
        out = parse_de111_text(BALLESTEROS_ITEM2)
        self.assertEqual(out.get("item2b_name"), "Anna Ballesteros, Professional Fiduciary")
        self.assertTrue(out.get("professional_fiduciary"))
        self.assertEqual(out.get("petitioner_name"), "Anna Ballesteros")

    def test_normal_item2b_is_not_fiduciary(self):
        out = parse_de111_text(NORMAL_ITEM2)
        self.assertEqual(out.get("item2b_name"), "John Henderson")
        self.assertFalse(out.get("professional_fiduciary"))
        self.assertEqual(out.get("petitioner_name"), "John Henderson")

    def test_caption_professional_fiduciary_is_not_skip(self):
        out = parse_de111_text(CAPTION_ONLY)
        self.assertEqual(out.get("item2b_name"), "John Henderson")
        self.assertFalse(out.get("professional_fiduciary"))

    def test_petitioner_line_same_person_as_2b(self):
        out = parse_de111_text(PETITIONER_LINE_SAME_PERSON)
        self.assertTrue(out.get("professional_fiduciary"))


class ProfessionalFiduciaryGateTests(unittest.TestCase):
    def test_gate_skips_professional_fiduciary(self):
        parsed = parse_de111_text(BALLESTEROS_ITEM2)
        self.assertEqual(
            gate_reason(
                _row(**parsed),
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            ),
            "professional_fiduciary",
        )

    def test_gate_allows_normal_petitioner(self):
        parsed = parse_de111_text(NORMAL_ITEM2)
        self.assertIsNone(
            gate_reason(
                _row(
                    petitioner=parsed.get("petitioner_name") or "John Henderson",
                    **{k: v for k, v in parsed.items() if k != "petitioner_name"},
                ),
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )

    def test_placer_and_sacramento_rows_skip(self):
        parsed = parse_de111_text(BALLESTEROS_ITEM2)
        for source in ("placer", "sacramento"):
            self.assertEqual(
                gate_reason(
                    _row(source_id=source, **parsed),
                    {"cases": {}},
                    MAPPING,
                    strict_property=False,
                    existing_id=None,
                ),
                "professional_fiduciary",
            )


if __name__ == "__main__":
    unittest.main()
