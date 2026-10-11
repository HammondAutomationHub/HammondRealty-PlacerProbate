"""Listings without a FUB person id must always POST/create."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from fub_client import (  # noqa: E402
    build_person,
    export_new_leads,
    fub_custom_field_names,
    gate_reason,
    load_mapping,
    mapping_for_export,
    needs_fub_create,
    person_fingerprint,
    should_skip_unchanged_person,
)
from placer_probate_monitor import load_state, save_state  # noqa: E402

PLACER_ROW = {
    "source_id": "placer",
    "case_number": "S-PR-0014448",
    "petitioner": "John Henderson",
    "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
    "decedent": "Jane Henderson",
    "decedent_residence": "1728 6th Street, Lincoln, CA 95648",
    "first_seen": False,
    "status": "repeat",
}

SACRAMENTO_ROW = {
    "source_id": "sacramento",
    "case_number": "26PR001581",
    "petitioner": "Wayne Row",
    "mailing_address": "13950 N Point CT, Pine Grove, CA 95665",
    "decedent": "Helen Row",
    "decedent_residence": "123 Main St, Sacramento, CA 95814",
    "first_seen": False,
    "status": "repeat",
}

MAPPING = {"skip_petitioner_contains": [], "custom_fields": {}, "send": {}}


def _export_fingerprint(row: dict, person_id: int | None = None) -> str:
    mapping = mapping_for_export(load_mapping(None), row.get("source_id"))
    settings = {
        "source": mapping.get("lead_source") or os.environ.get("FUB_SOURCE", "probate"),
        "assigned_to": os.environ.get("FUB_ASSIGNED_TO", "Blake Hammond"),
        "stage": (os.environ.get("FUB_STAGE") or "").strip(),
    }
    person = build_person(
        row,
        mapping,
        settings,
        person_id=person_id,
        allowed_custom=fub_custom_field_names(),
    )
    return person_fingerprint(person)


class FubCreateGateTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            key: os.environ.get(key)
            for key in (
                "FUB_ENABLED",
                "FUB_API_KEY",
                "FUB_VERIFY_ONLY",
                "FUB_UPDATE_EXISTING",
                "FUB_VERIFY_EXISTING",
                "FUB_STRICT_PROPERTY",
                "FUB_GO_REQUIRED_FIELDS",
                "FUB_DATA_SOURCE",
                "PPM_PROGRESS_PATH",
            )
        }
        os.environ["FUB_ENABLED"] = "1"
        os.environ["FUB_API_KEY"] = "test-key"
        os.environ["FUB_VERIFY_ONLY"] = "0"
        os.environ["FUB_UPDATE_EXISTING"] = "0"
        os.environ["FUB_VERIFY_EXISTING"] = "0"
        os.environ["FUB_STRICT_PROPERTY"] = "0"
        os.environ.pop("FUB_GO_REQUIRED_FIELDS", None)
        os.environ["PPM_PROGRESS_PATH"] = str(ROOT / "tests" / "_progress_gate.json")

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        path = ROOT / "tests" / "_progress_gate.json"
        if path.exists():
            path.unlink()

    def test_needs_create_when_seen_without_person_id(self):
        state = {
            "cases": {
                "S-PR-0014448": {
                    "first_seen": "2026-09-01",
                    "fub_fingerprint": "deadbeef",
                }
            }
        }
        self.assertTrue(needs_fub_create(state, "S-PR-0014448"))
        self.assertFalse(
            needs_fub_create(
                {"cases": {"S-PR-0014448": {"fub_person_id": 42}}},
                "S-PR-0014448",
            )
        )

    def test_gate_does_not_skip_seen_listings_without_fub_id(self):
        for row in (PLACER_ROW, SACRAMENTO_ROW):
            key = row["case_number"]
            state = {"cases": {key: {"first_seen": "2026-09-01"}}}
            self.assertIsNone(
                gate_reason(
                    row,
                    state,
                    MAPPING,
                    strict_property=False,
                    existing_id=None,
                    allow_seen_without_fub=False,
                )
            )

    def test_fingerprint_without_person_id_does_not_skip(self):
        fingerprint = _export_fingerprint(PLACER_ROW)
        self.assertFalse(
            should_skip_unchanged_person(
                existing_id=None,
                record={"fub_fingerprint": fingerprint},
                fingerprint=fingerprint,
                verify=False,
                update_existing=False,
            )
        )
        self.assertTrue(
            should_skip_unchanged_person(
                existing_id=88,
                record={"fub_fingerprint": fingerprint},
                fingerprint=fingerprint,
                verify=False,
                update_existing=False,
            )
        )
        self.assertFalse(
            should_skip_unchanged_person(
                existing_id=88,
                record={"fub_fingerprint": fingerprint},
                fingerprint=fingerprint,
                verify=False,
                update_existing=True,
            )
        )

    def _export_with_http(
        self,
        rows,
        state,
        *,
        posted_id=501,
        live_ok=True,
        put_ok=True,
    ):
        live = {"id": posted_id} if live_ok else None
        put_body = {"id": posted_id} if put_ok else None
        with (
            patch("fub_client.post_event", return_value={"personId": posted_id}) as posted,
            patch("fub_client.get_person", return_value=live) as loaded,
            patch("fub_client.put_person", return_value=put_body) as updated,
            patch("fub_client.post_note"),
            patch("fub_client.post_court_portal_note", return_value={}),
            patch("fub_client.attach_de111_file", return_value={}),
            patch("fub_client.attach_de147_file", return_value={}),
        ):
            summary = export_new_leads(rows, state)
        return summary, posted, updated, loaded

    def test_local_seen_placer_posts_when_export_enabled(self):
        key = PLACER_ROW["case_number"]
        state = {"cases": {key: {"first_seen": "2026-09-01", "last_seen": "2026-10-01"}}}
        summary, posted, updated, loaded = self._export_with_http(
            [PLACER_ROW], state, posted_id=701
        )
        self.assertEqual(summary["posted"], 1)
        self.assertEqual(summary["updated"], 0)
        posted.assert_called_once()
        loaded.assert_not_called()
        self.assertEqual(state["cases"][key]["fub_person_id"], 701)
        self.assertTrue(updated.called)

    def test_local_seen_sacramento_posts_when_export_enabled(self):
        os.environ["FUB_DATA_SOURCE"] = "sacramento"
        key = SACRAMENTO_ROW["case_number"]
        state = {
            "cases": {
                key: {
                    "first_seen": "2026-09-01",
                    "fub_fingerprint": "leftover-local-fp",
                }
            }
        }
        summary, posted, _updated, loaded = self._export_with_http(
            [SACRAMENTO_ROW], state, posted_id=802
        )
        self.assertEqual(summary["posted"], 1)
        self.assertEqual(summary.get("skips"), [])
        posted.assert_called_once()
        loaded.assert_not_called()
        self.assertEqual(state["cases"][key]["fub_person_id"], 802)

    def test_exported_placer_skips_unchanged_without_update_all(self):
        fingerprint = _export_fingerprint(PLACER_ROW, person_id=44)
        key = PLACER_ROW["case_number"]
        state = {
            "cases": {
                key: {"fub_person_id": 44, "fub_fingerprint": fingerprint}
            }
        }
        summary, posted, updated, loaded = self._export_with_http([PLACER_ROW], state)
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["skips"][0]["reason"], "unchanged")
        posted.assert_not_called()
        updated.assert_not_called()
        loaded.assert_called_once()
        self.assertNotIn("fub_removed", state["cases"][key])

    def test_exported_sacramento_updates_when_update_all(self):
        os.environ["FUB_DATA_SOURCE"] = "sacramento"
        os.environ["FUB_UPDATE_EXISTING"] = "1"
        fingerprint = _export_fingerprint(SACRAMENTO_ROW, person_id=55)
        key = SACRAMENTO_ROW["case_number"]
        state = {
            "cases": {
                key: {"fub_person_id": 55, "fub_fingerprint": fingerprint}
            }
        }
        summary, posted, updated, loaded = self._export_with_http(
            [SACRAMENTO_ROW], state, posted_id=55
        )
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["updated"], 1)
        posted.assert_not_called()
        updated.assert_called_once()
        loaded.assert_called_once()

    def test_deleted_person_id_marked_removed_without_post(self):
        for row in (PLACER_ROW, SACRAMENTO_ROW):
            with self.subTest(source_id=row["source_id"]):
                os.environ["FUB_DATA_SOURCE"] = row["source_id"]
                key = row["case_number"]
                state = {
                    "cases": {
                        key: {"fub_person_id": 5120, "fub_fingerprint": "stale-fp"}
                    }
                }
                summary, posted, updated, loaded = self._export_with_http(
                    [row],
                    state,
                    posted_id=5120,
                    live_ok=False,
                )
                self.assertEqual(summary["posted"], 0)
                self.assertEqual(summary["updated"], 0)
                self.assertEqual(summary["skipped"], 1)
                self.assertEqual(summary["skips"][0]["reason"], "fub_removed")
                posted.assert_not_called()
                updated.assert_not_called()
                loaded.assert_called_once()
                rec = state["cases"][key]
                self.assertTrue(rec["fub_removed"])
                self.assertEqual(rec["fub_person_id"], 5120)
                self.assertFalse(needs_fub_create(state, key))

    def test_put_404_marks_removed_without_post(self):
        for row in (PLACER_ROW, SACRAMENTO_ROW):
            with self.subTest(source_id=row["source_id"]):
                os.environ["FUB_DATA_SOURCE"] = row["source_id"]
                key = row["case_number"]
                state = {
                    "cases": {
                        key: {"fub_person_id": 5120, "fub_fingerprint": "stale-fp"}
                    }
                }
                summary, posted, updated, loaded = self._export_with_http(
                    [row],
                    state,
                    posted_id=5120,
                    live_ok=True,
                    put_ok=False,
                )
                self.assertEqual(summary["posted"], 0)
                self.assertEqual(summary["skips"][0]["reason"], "fub_removed")
                posted.assert_not_called()
                updated.assert_called_once()
                loaded.assert_called_once()
                self.assertTrue(state["cases"][key]["fub_removed"])
                self.assertFalse(needs_fub_create(state, key))

    def test_already_removed_skips_without_http(self):
        for row in (PLACER_ROW, SACRAMENTO_ROW):
            with self.subTest(source_id=row["source_id"]):
                os.environ["FUB_DATA_SOURCE"] = row["source_id"]
                key = row["case_number"]
                state = {
                    "cases": {
                        key: {
                            "fub_person_id": 5120,
                            "fub_removed": True,
                            "fub_fingerprint": "stale-fp",
                        }
                    }
                }
                summary, posted, updated, loaded = self._export_with_http(
                    [row], state, posted_id=5120
                )
                self.assertEqual(summary["posted"], 0)
                self.assertEqual(summary["skips"][0]["reason"], "fub_removed")
                posted.assert_not_called()
                updated.assert_not_called()
                loaded.assert_not_called()
                self.assertTrue(state["cases"][key]["fub_removed"])
                self.assertFalse(needs_fub_create(state, key))

    def test_seen_cases_files_persist_fub_removed(self):
        import tempfile

        for filename in ("seen_cases.json", "seen_cases_sacramento.json"):
            with self.subTest(filename=filename):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / filename
                    save_state(
                        path,
                        {
                            "cases": {
                                "S-PR-0014448": {
                                    "fub_person_id": 5120,
                                    "fub_removed": True,
                                    "fub_skip": "fub_removed",
                                }
                            }
                        },
                    )
                    loaded = load_state(path)
                    rec = loaded["cases"]["S-PR-0014448"]
                    self.assertTrue(rec["fub_removed"])
                    self.assertEqual(rec["fub_person_id"], 5120)

    def test_default_gate_still_requires_mailing(self):
        row = {
            "source_id": "placer",
            "case_number": "S-PR-0014448",
            "petitioner": "John Henderson",
        }
        self.assertEqual(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            ),
            "missing_petitioner_address",
        )
        row["mailing_address"] = "51 Ashby Hills Ct, Henderson, NV 89012"
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )

    def test_custom_required_skips_mailing_when_unchecked(self):
        row = {
            "source_id": "sacramento",
            "case_number": "26PR001581",
            "petitioner": "Wayne Row",
        }
        custom = ["case_number", "petitioner_first", "petitioner_last"]
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
                required_fields=custom,
            )
        )
        self.assertEqual(
            gate_reason(
                dict(row, petitioner="Wayne"),
                {"cases": {}},
                MAPPING,
                strict_property=True,
                existing_id=None,
                required_fields=custom,
            ),
            "petitioner_name_incomplete",
        )


if __name__ == "__main__":
    unittest.main()
