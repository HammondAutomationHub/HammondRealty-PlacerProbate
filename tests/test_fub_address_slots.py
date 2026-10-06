#!/usr/bin/env python3
"""Address 1/2 must both survive mapping order (catalog lists mailing first)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from fub_client import build_event, build_person  # noqa: E402


ROW = {
    "case_number": "S-PR-0014448",
    "petitioner": "John Henderson",
    "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
    "mailing_city": "Henderson",
    "mailing_state": "NV",
    "mailing_zip": "89012",
    "decedent_residence": "1728 6th Street, Lincoln, CA 95648",
    "decedent_city": "Lincoln",
    "decedent_state": "CA",
    "decedent_zip": "95648",
}

SETTINGS = {"assigned_to": "", "stage": ""}


def _mapping(fields: dict) -> dict:
    return {
        "send": {
            "firstName": True,
            "lastName": True,
            "emails": False,
            "phones": False,
            "assignedTo": False,
            "stage": False,
            "custom_fields": True,
        },
        "custom_fields": fields,
        "skip_petitioner_contains": [],
    }


class AddressSlotTests(unittest.TestCase):
    def test_mailing_mapped_before_home_keeps_both(self):
        person = build_person(
            ROW,
            _mapping(
                {
                    "mailing_address": "address2",
                    "decedent_residence": "addresses",
                }
            ),
            SETTINGS,
        )
        addrs = person.get("addresses") or []
        self.assertEqual(len(addrs), 2)
        self.assertEqual(addrs[0]["street"], "1728 6th Street")
        self.assertEqual(addrs[0]["type"], "home")
        self.assertEqual(addrs[1]["street"], "51 Ashby Hills Ct")
        self.assertEqual(addrs[1]["type"], "mailing")
        self.assertNotIn("_addr_slots", person)

    def test_verify_event_reuses_the_same_person_addresses(self):
        mapping = _mapping(
            {
                "mailing_address": "address2",
                "decedent_residence": "addresses",
            }
        )
        person = build_person(ROW, mapping, SETTINGS)
        event = build_event(ROW, mapping, SETTINGS, person=person)
        self.assertEqual(event["person"]["addresses"], person["addresses"])
        self.assertEqual(len(event["person"]["addresses"]), 2)

    def test_home_mapped_before_mailing_keeps_both(self):
        person = build_person(
            ROW,
            _mapping(
                {
                    "decedent_residence": "addresses",
                    "mailing_address": "address2",
                }
            ),
            SETTINGS,
        )
        addrs = person.get("addresses") or []
        self.assertEqual(len(addrs), 2)
        self.assertEqual(addrs[0]["type"], "home")
        self.assertEqual(addrs[1]["type"], "mailing")


if __name__ == "__main__":
    unittest.main()
