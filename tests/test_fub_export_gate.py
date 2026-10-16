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
    DEFAULT_FUB_GO_REQUIRED_FIELDS,
    FUB_GO_GATE_FIELD_KEYS,
    build_person,
    export_new_leads,
    fub_custom_field_names,
    gate_reason,
    go_no_go_for_source,
    load_mapping,
    mapping_for_export,
    needs_fub_create,
    normalize_fub_go_required_fields,
    person_fingerprint,
    should_skip_unchanged_person,
    stored_person_id,
)
from placer_probate_monitor import (  # noqa: E402
    Notice,
    build_html,
    build_text,
    load_state,
    save_state,
)

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

    def test_seen_with_id_puts_not_posts(self):
        key = PLACER_ROW["case_number"]
        state = {
            "cases": {
                key: {"fub_person_id": 44, "fub_fingerprint": "stale-fp"}
            }
        }
        summary, posted, updated, loaded = self._export_with_http(
            [PLACER_ROW], state, posted_id=44
        )
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["updated"], 1)
        posted.assert_not_called()
        updated.assert_called_once()
        loaded.assert_called_once()
        self.assertEqual(state["cases"][key]["fub_person_id"], 44)

    def test_missing_mailing_skips_and_leaves_id_empty(self):
        key = PLACER_ROW["case_number"]
        row = dict(PLACER_ROW)
        row.pop("mailing_address")
        state = {"cases": {key: {"first_seen": "2026-09-01", "last_seen": "2026-10-01"}}}
        summary, posted, updated, loaded = self._export_with_http([row], state)
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skips"][0]["reason"], "missing_petitioner_address")
        posted.assert_not_called()
        updated.assert_not_called()
        loaded.assert_not_called()
        rec = state["cases"][key]
        self.assertIsNone(stored_person_id(state, key))
        self.assertNotIn("fub_person_id", rec)
        self.assertEqual(rec["fub_skip"], "missing_petitioner_address")
        self.assertTrue(needs_fub_create(state, key))

    def test_email_new_is_cnpa_and_includes_fub_line(self):
        from datetime import date

        notices = [
            Notice(
                case_number="S-PR-0014448",
                decedent="Jane Henderson",
                petitioner="John Henderson",
                court_county="Placer",
                hearing="",
                attorney="",
                attorney_phone="",
                newspaper="",
                post_date="",
                publication_line="",
                will_offered=False,
                iaea_requested=False,
                refcode="",
                advert_id="",
                notice_url="",
                snippet="",
                raw_text="",
                first_seen=False,
            )
        ]
        html = build_html(
            notices,
            date(2026, 10, 1),
            date(2026, 10, 14),
            ["https://example.test"],
            fub_posted=2,
            fub_updated=1,
            fub_skipped=3,
        )
        text = build_text(
            notices,
            date(2026, 10, 1),
            date(2026, 10, 14),
            ["https://example.test"],
            fub_posted=2,
            fub_updated=1,
            fub_skipped=3,
        )
        self.assertIn("New since last run: <strong>0</strong>", html)
        self.assertIn(
            "Follow Up Boss: posted <strong>2</strong>, updated <strong>1</strong>, skipped <strong>3</strong>",
            html,
        )
        self.assertIn("New today: 0", text)
        self.assertIn("Follow Up Boss: posted 2, updated 1, skipped 3", text)

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

    def test_classic_case_and_mailing_go_without_phone(self):
        row = {
            "source_id": "placer",
            "case_number": "S-PR-0014448",
            "petitioner": "John Henderson",
            "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
        }
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )

    def test_notices_path_b_go_without_mailing(self):
        row = {
            "source_id": "placer",
            "case_number": "Notices_995995",
            "petitioner": "Kristopher Gibson",
            "decedent": "Allen Gibson",
            "decedent_residence": "100 Main St, Lincoln, CA 95648",
            "petitioner_phone": "916-555-0100",
        }
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )
        self.assertTrue(needs_fub_create({"cases": {}}, "Notices_995995"))

    def test_notices_path_b_missing_phone_is_nogo(self):
        row = {
            "source_id": "placer",
            "case_number": "Notices_995995",
            "petitioner": "Kristopher Gibson",
            "decedent": "Allen Gibson",
            "decedent_residence": "100 Main St, Lincoln, CA 95648",
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

    def test_path_b_full_petitioner_and_decedent_address_alias(self):
        row = {
            "source_id": "sacramento",
            "case_number": "",
            "advert_id": "Notices_981504",
            "petitioner": "Madonna",
            "decedent": "Gregory Alan Tarter",
            "decedent_address": "200 Alpine Dr, Truckee, CA 96161",
            "petitioner_phone": "(530) 555-0199",
        }
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )

    def test_path_b_respects_fub_removed(self):
        row = {
            "source_id": "placer",
            "case_number": "Notices_995995",
            "petitioner": "Kristopher Gibson",
            "decedent": "Allen Gibson",
            "decedent_residence": "100 Main St, Lincoln, CA 95648",
            "petitioner_phone": "916-555-0100",
        }
        state = {
            "cases": {
                "Notices_995995": {
                    "fub_person_id": 88,
                    "fub_removed": True,
                }
            }
        }
        self.assertEqual(
            gate_reason(
                row,
                state,
                MAPPING,
                strict_property=False,
                existing_id=None,
            ),
            "fub_removed",
        )
        self.assertFalse(needs_fub_create(state, "Notices_995995"))

    def test_path_b_export_skips_when_fub_removed(self):
        row = {
            "source_id": "placer",
            "case_number": "Notices_995995",
            "petitioner": "Kristopher Gibson",
            "decedent": "Allen Gibson",
            "decedent_residence": "100 Main St, Lincoln, CA 95648",
            "petitioner_phone": "916-555-0100",
            "first_seen": True,
            "status": "new",
        }
        state = {
            "cases": {
                "Notices_995995": {
                    "fub_person_id": 88,
                    "fub_removed": True,
                }
            }
        }
        summary, posted, updated, loaded = self._export_with_http([row], state)
        self.assertEqual(summary["posted"], 0)
        self.assertEqual(summary["updated"], 0)
        self.assertEqual(summary["skips"][0]["reason"], "fub_removed")
        posted.assert_not_called()
        updated.assert_not_called()
        loaded.assert_not_called()
        self.assertFalse(needs_fub_create(state, "Notices_995995"))

    def test_case_number_is_never_required_for_go(self):
        self.assertNotIn("case_number", DEFAULT_FUB_GO_REQUIRED_FIELDS)
        self.assertNotIn("case_number", FUB_GO_GATE_FIELD_KEYS)
        self.assertEqual(
            normalize_fub_go_required_fields(
                ["case_number", "petitioner_first", "petitioner_last", "mailing_address"]
            ),
            ["petitioner_first", "petitioner_last", "mailing_address"],
        )
        for source_id in ("placer", "sacramento"):
            required = {item["key"] for item in go_no_go_for_source(source_id)["required"]}
            self.assertNotIn("case_number", required)
        row = {
            "source_id": "placer",
            "case_number": "",
            "petitioner": "John Henderson",
            "mailing_address": "51 Ashby Hills Ct, Henderson, NV 89012",
        }
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
                required_fields=["case_number", "petitioner_first", "petitioner_last", "mailing_address"],
            )
        )

    def test_path_b_go_with_court_case_and_no_mailing(self):
        row = {
            "source_id": "placer",
            "case_number": "S-PR-0014228",
            "petitioner": "Dewan Petitioner",
            "decedent": "Estate Decedent",
            "decedent_residence": "100 Main St, Lincoln, CA 95648",
            "petitioner_phone": "916-555-0100",
        }
        self.assertIsNone(
            gate_reason(
                row,
                {"cases": {}},
                MAPPING,
                strict_property=False,
                existing_id=None,
            )
        )

    def test_fub_removed_empty_id_does_not_recreate(self):
        row = dict(PLACER_ROW)
        state = {"cases": {row["case_number"]: {"fub_removed": True}}}
        self.assertEqual(
            gate_reason(
                row,
                state,
                MAPPING,
                strict_property=False,
                existing_id=None,
            ),
            "fub_removed",
        )
        self.assertFalse(needs_fub_create(state, row["case_number"]))
        summary, posted, updated, loaded = self._export_with_http([row], state)
        self.assertEqual(summary["skips"][0]["reason"], "fub_removed")
        posted.assert_not_called()
        updated.assert_not_called()
        loaded.assert_not_called()

    def test_http_error_does_not_abort_remaining_creates(self):
        first = dict(PLACER_ROW, case_number="S-PR-0014001")
        second = dict(PLACER_ROW, case_number="S-PR-0014002")
        state = {"cases": {}}
        calls = {"n": 0}

        def post_event(*_args, **_kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("503 from Follow Up Boss")
            return {"personId": 900 + calls["n"]}

        with (
            patch("fub_client.post_event", side_effect=post_event) as posted,
            patch("fub_client.get_person", return_value={"id": 1}),
            patch("fub_client.put_person", return_value={"id": 1}),
            patch("fub_client.post_note"),
            patch("fub_client.post_court_portal_note", return_value={}),
            patch("fub_client.attach_de111_file", return_value={}),
            patch("fub_client.attach_de147_file", return_value={}),
        ):
            summary = export_new_leads([first, second], state)
        self.assertEqual(posted.call_count, 2)
        self.assertEqual(summary["posted"], 1)
        self.assertEqual(summary["skips"][0]["reason"], "fub_http_error")
        self.assertEqual(state["cases"]["S-PR-0014002"]["fub_person_id"], 902)


if __name__ == "__main__":
    unittest.main()
