"""Sacramento notice and portal parsers, plus Placer regressions on shared regexes."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "custom_components" / "placer_probate_monitor"))

from bs4 import BeautifulSoup  # noqa: E402

from placer_probate_monitor import (  # noqa: E402
    Notice,
    cnpa_page_sequence,
    extract_case,
    notice_fields,
    parse_cnpa_max_pages,
    search_url,
)
from sacramento_portal import (  # noqa: E402
    document_is_blocked,
    login_form_payload,
    parse_document_files,
    parse_summary,
    session_is_logged_in,
    solve_math_captcha,
    _parse_search,
    _pane_rows,
)
from sacramento_probate_monitor import (  # noqa: E402
    extract_sacramento_case,
    is_sacramento_court_notice,
    keep_sacramento_notices,
)

FOLSOM = """
L0010608
26PR002037
NOTICE OF PETITION TO ADMINISTER ESTATE OF
SUZANNE GAIL MAGTALAS
CASE NO. 26PR002037
1. To all heirs, beneficiaries, creditors, contingent creditors, and persons who may otherwise be interested in the will or estate, or both, of: SUZANNE GAIL MAGTALAS,
2. A PETITION FOR PROBATE has been filed by: GERMANE SMITH in the Superior Court of California, County of SACRAMENTO
3. The Petition for Probate requests that: GERMANE SMITH be appointed as personal representative to administer the estate of the decedent.
5. THE PETITION requests authority to administer the estate under the Independent Administration of Estates Act.
6. A HEARING on the petition will be held in this court as follows: August 26, 2026 at 1:30 PM in Dept. 126 located at Superior Court of California, County of Sacramento, William R. Ridgeway Family Relations Courthouse, 3341 Power Inn Road, Sacramento, CA 95826
7. IF YOU OBJECT to the granting of the petition, you should appear at the hearing.
10. Attorney for Petitioner:HEATHER S. MAYER, SBN 272665, MAYER & YOUNG, PC, 400 PLAZA DRIVE, SUITE 145, FOLSOM, CA, 95630
Phone No.: 916-631-1996
PUBLISHED IN FOLSOM TELEGRAPH ON JULY 31, AUGUST 7, 14, 2026
"""

BEE = """
NOTICE OF PETITION TO ADMINISTER ESTATE OF:
Helen Row
CASE NUMBER
26PR001581
To all heirs, beneficiaries, creditors, contingent creditors, and persons who may otherwise be interested in the will or estate, or both, of, Helen Row
A PETITION FOR PROBATE has been filed by Wayne Row in the Superior Court of California, County of Sacramento.
THE PETITION requests the decedent's will and codicils, if any, be admitted to probate.
THE PETITION requests authority to administer the estate under the Independent Administration of Estates Act.
A HEARING on the petition will be held in this court as follows:
Date: September 08 2026 Time: 9:00am Dept: 126
Address of the Court:
3341 Power Inn Rd, #214
Sacramento, CA, 95826
IF YOU OBJECT to the granting of the petition, you should appear at the hearing.
Attorney for Petitioner: Wayne Row
13950 N Point Ct
Pine Grove, CA, 95665
Telephone: 916-335-3753
IPL0360651
Aug 5,12,19 2026
"""

PLACER = """
NOTICE OF PETITION TO ADMINISTER ESTATE OF
JANE Q DOE
CASE NO. S-PR-0014250
1. To all heirs, beneficiaries, creditors, and persons who may otherwise be interested in the will or estate, or both, of: JANE Q DOE
2. A PETITION FOR PROBATE has been filed by: JOHN DOE in the Superior Court of California, County of PLACER
6. A HEARING on the petition will be held in this court as follows: October 1, 2026 at 8:30 AM in Dept. 40
7. IF YOU OBJECT to the granting of the petition, you should appear at the hearing.
The petition requests the decedent's will and codicils, if any, be admitted to probate.
Attorney for Petitioner: ANN LAWYER, SBN 1, EXAMPLE FIRM
Phone No.: (916) 555-0100
PUBLISHED IN PLACER HERALD ON OCTOBER 1, 2026
"""

SUMMARY = """
<table class="caseHeader" style="width:100%;">
 <tr><td class="caseheaderXLtext" colspan="3"><b>26PR001581</b> ESTATE OF: HELEN ROW</td></tr>
 <tr>
  <td><b>Probate</b> (<span title="Probate of Will &amp; Letters Testamentary">Probate of Will...</span>)</td>
  <td><span title="William R. Ridgeway Family Relations Courthouse">William R...</span> / DEPT 126 - HON. Heath T. Langle</td>
 </tr>
 <tr>
  <td><span title="Date Filed">Filed: 06/04/2026</span></td>
  <td><span title="Next Event 11/18/2026 9:00 AM General Probate Amended Petition in Department 126">Next Hearing: 11/18/2026</span></td>
 </tr>
</table>
<div class="tabpane" id="pane.form.1">
 <table class="table"><tr><td></td><td>Filed / Status Date</td><td>Name</td><td>Filed By</td></tr>
  <tr><td></td><td>10/06/2026</td><td>Amended Petition</td><td>Wayne L Row (Petitioner)</td><td>9</td></tr>
  <tr><td></td><td>06/04/2026</td><td>Petition for Probate of Will &amp; Letters Testamentary</td><td>Wayne L Row (Petitioner)</td><td>10</td></tr>
 </table>
</div>
<div class="tabpane" id="pane.form.2"><table class="table"><tr><td>Date</td><td>Message</td></tr></table></div>
<div class="tabpane" id="pane.form.3">
 <table class="table"><tr><td></td><td>Name</td><td>AKA/DBA</td><td>Role</td></tr>
  <tr><td></td><td>Wayne L Row (Petitioner)</td><td></td><td>Petitioner</td></tr>
  <tr><td></td><td>Helen Row (Decedent)</td><td></td><td>Decedent</td></tr>
</table>
</div>
<div class="tabpane" id="pane.form.4">
 <table class="table">
  <tr><td></td><td>Name</td><td>Date/Time</td><td>Status</td><td>Department</td></tr>
  <tr><td></td><td>General Probate Amended Petition</td><td>11/18/2026 09:00 AM</td><td>Scheduled</td><td>Dept 126 / William R. Ridgeway Family Relations</td></tr>
  <tr><td></td><td>General Probate</td><td>09/08/2026 09:00 AM</td><td>Rescheduled</td><td>Dept 126 / William R. Ridgeway Family Relations</td></tr>
 </table>
</div>
"""

SEARCH = """
<a href="?q=node/430/2506537">26PR001581</a>
<a href="?q=node/430/2506537">ESTATE OF: HELEN ROW</a>
<a href="/public-portal/?q=node/429/1/82309/ASCEND">Case Number</a>
"""


OBSERVER = """
NOTICE OF PETITION TOADMINISTER ESTATE OFROBERT EUGENE HANLEYCASE NO. 26PR002445Superior Court of California
To all heirs, beneficiaries, creditors, and contingent creditors and persons who may be otherwise interested in the will or estate, or both of: ROBERT EUGENE HANLEY
A Petition for Probate has been filed by MICHAEL G. LEE in the Superior Court of California, County of SACRAMENTO.
The petition requests the decedent's will and codicils, if any, be admitted to probate.
The petition requests authority to administer the estate under the Independent Administration of Estates Act.
A hearing on the petition will be held in this court as follows:SEPTEMBER 29 2026 at 9:00 AMin Dept. No. 1263341 Power Inn Road Sacramento, CA 95826
IF YOU OBJECT to the granting of the petition, you should appear at the hearing.
Petitioner or Attorney for PetitionerMichael G. Lee109 Flint Rock CtRoseville, CA 95747
"""


class NoticeParseTests(unittest.TestCase):
    def test_sacramento_numbered_notice(self):
        fields = notice_fields(FOLSOM, extract_sacramento_case)
        self.assertEqual(fields["case_number"], "26PR002037")
        self.assertEqual(fields["decedent"], "SUZANNE GAIL MAGTALAS")
        self.assertEqual(fields["petitioner"], "GERMANE SMITH")
        self.assertEqual(fields["court_county"], "SACRAMENTO")
        self.assertIn("August 26, 2026", fields["hearing"])
        self.assertNotIn("IF YOU OBJECT", fields["hearing"])
        self.assertIn("HEATHER S. MAYER", fields["attorney"])
        self.assertIn("916-631-1996", fields["attorney_phone"])
        self.assertTrue(fields["iaea_requested"])
        self.assertFalse(fields["will_offered"])
        self.assertIn("FOLSOM TELEGRAPH", fields["publication_line"])

    def test_sacramento_bee_layout(self):
        fields = notice_fields(BEE, extract_sacramento_case)
        self.assertEqual(fields["case_number"], "26PR001581")
        self.assertEqual(fields["decedent"], "Helen Row")
        self.assertEqual(fields["petitioner"], "Wayne Row")
        self.assertEqual(fields["court_county"], "Sacramento")
        self.assertIn("September 08 2026", fields["hearing"])
        self.assertIn("3341 Power Inn", fields["hearing"])
        self.assertNotIn("IF YOU OBJECT", fields["hearing"])
        self.assertIn("Wayne Row", fields["attorney"])
        self.assertIn("Pine Grove", fields["attorney"])
        self.assertIn("916-335-3753", fields["attorney_phone"])
        self.assertTrue(fields["will_offered"])
        self.assertTrue(fields["iaea_requested"])
        self.assertIn("2026", fields["publication_line"])

    def test_observer_glued_words(self):
        fields = notice_fields(OBSERVER, extract_sacramento_case)
        self.assertEqual(fields["case_number"], "26PR002445")
        self.assertEqual(fields["decedent"], "ROBERT EUGENE HANLEY")
        self.assertEqual(fields["petitioner"], "MICHAEL G. LEE")
        self.assertIn("SEPTEMBER 29 2026", fields["hearing"])
        self.assertIn("3341 Power Inn", fields["hearing"])
        self.assertIn("Michael G. Lee", fields["attorney"])
        self.assertIn("Roseville", fields["attorney"])
        self.assertTrue(fields["will_offered"])
        self.assertTrue(fields["iaea_requested"])

    def test_spacing_does_not_split_ordinary_words(self):
        from placer_probate_monitor import normalize_notice_text

        text = normalize_notice_text(
            "LAW OFFICE OF THERESA at 9:00 a.m. in Dept. 129. Esq.1960 stays a phone (916) 572-1998."
        )
        self.assertIn("LAW OFFICE OF THERESA", text)
        self.assertIn("9:00 a.m.", text)
        self.assertIn("Esq. 1960", text)
        self.assertIn("(916) 572-1998", text)

    def test_case_padding(self):
        self.assertEqual(extract_sacramento_case("case 26PR1581 and 26PR001581"), "26PR001581")

    def test_placer_notice_still_parses(self):
        fields = notice_fields(PLACER, extract_case)
        self.assertEqual(fields["case_number"], "S-PR-0014250")
        self.assertEqual(fields["decedent"], "JANE Q DOE")
        self.assertEqual(fields["petitioner"], "JOHN DOE")
        self.assertEqual(fields["court_county"], "PLACER")
        self.assertIn("October 1, 2026", fields["hearing"])
        self.assertIn("ANN LAWYER", fields["attorney"])
        self.assertIn("916", fields["attorney_phone"])
        self.assertTrue(fields["will_offered"])
        self.assertIn("PLACER HERALD", fields["publication_line"])

    def test_drops_non_estate_notice_of_petition(self):
        fields = notice_fields("NOTICE OF PETITION for something else CASE NO. 26PR000001")
        self.assertEqual(fields, {})


class FubTagTests(unittest.TestCase):
    def test_sacramento_adds_tag_beside_probate(self):
        from datasources import fub_tags, stamp_fub_tags

        self.assertEqual(fub_tags("Placer"), ["probate", "placer"])
        self.assertEqual(fub_tags("sacramento"), ["probate", "sacramento"])
        self.assertEqual(fub_tags("nevada"), ["probate", "nevada"])
        rows = stamp_fub_tags([{"case_number": "26PR002445"}], "Sacramento")
        self.assertEqual(rows[0]["tags"], ["probate", "sacramento"])
        self.assertIn("probate", rows[0]["tags"])
        self.assertEqual(rows[0]["lead_source"], "probate")
        self.assertEqual(rows[0]["source_id"], "sacramento")
        placer = stamp_fub_tags([{"case_number": "S-PR-0014448"}], "placer")
        self.assertEqual(placer[0]["tags"], ["probate", "placer"])
        self.assertEqual(placer[0]["lead_source"], "probate")
        nevada = stamp_fub_tags([{"case_number": "PR26-00001"}], "nevada")
        self.assertEqual(nevada[0]["tags"], ["probate", "nevada"])
        self.assertEqual(nevada[0]["lead_source"], "probate")
        self.assertEqual(nevada[0]["source_id"], "nevada")

    def test_person_tags_and_merge_query(self):
        from fub_client import build_event, build_person, mapping_for_export, put_person
        import inspect

        person = build_person(
            {"petitioner": "Wayne Row", "tags": ["probate", "sacramento"], "source_id": "sacramento"},
            {"send": {"firstName": True, "lastName": True}, "custom_fields": {}},
            {"assigned_to": "", "stage": "", "source": "probate"},
        )
        self.assertEqual(person["tags"], ["probate", "sacramento"])
        self.assertEqual(person["source"], "probate")
        placer = build_person(
            {"petitioner": "Jane Doe", "source_id": "placer"},
            {"send": {"firstName": True, "lastName": True}, "custom_fields": {}},
            {"assigned_to": "", "stage": "", "source": "probate"},
        )
        self.assertEqual(placer["tags"], ["probate", "placer"])
        self.assertEqual(placer["source"], "probate")
        event = build_event(
            {"petitioner": "Wayne Row", "source_id": "sacramento", "case_number": "26PR002445"},
            {"send": {"firstName": True, "lastName": True, "source": True}, "custom_fields": {}},
            {"assigned_to": "", "stage": "", "source": "probate", "event_type": "Seller Inquiry"},
        )
        self.assertEqual(event["source"], "probate")
        self.assertEqual(event["person"]["source"], "probate")
        self.assertEqual(mapping_for_export({}, "placer")["lead_source"], "probate")
        self.assertEqual(
            mapping_for_export({}, "sacramento")["lead_source"], "probate"
        )
        self.assertEqual(mapping_for_export({}, "nevada")["lead_source"], "probate")
        self.assertIn("mergeTags=true", inspect.getsource(put_person))

    def test_sacramento_url_is_not_rewritten_to_placer(self):
        from fub_client import case_portal_url

        url = (
            "https://prod-portal-sacramento-ca.journaltech.com/public-portal/"
            "?q=node/397/2506537"
        )
        self.assertEqual(case_portal_url({"court_url": url}), url)
        node430 = url.replace("node/397", "node/430")
        self.assertIn("node/397/2506537", case_portal_url({"court_url": node430}))
        self.assertNotIn("node/45", case_portal_url({"court_url": url}))

    def test_sacramento_off_by_default(self):
        from fub_client import DATA_SOURCES, enabled_live_sources, normalize_source_enabled

        statuses = {item["id"]: item["status"] for item in DATA_SOURCES}
        names = {item["id"]: item.get("lead_source") for item in DATA_SOURCES}
        self.assertEqual(statuses["placer"], "live")
        self.assertEqual(statuses["sacramento"], "live")
        self.assertEqual(statuses["nevada"], "coming_soon")
        self.assertEqual(names["placer"], "probate")
        self.assertEqual(names["sacramento"], "probate")
        self.assertEqual(names["nevada"], "probate")
        flags = normalize_source_enabled({})
        self.assertTrue(flags["placer"])
        self.assertFalse(flags["sacramento"])
        self.assertEqual(enabled_live_sources({}), ["placer"])
        self.assertEqual(
            enabled_live_sources({"source_enabled": {"placer": True, "sacramento": True}}),
            ["placer", "sacramento"],
        )
        self.assertEqual(
            enabled_live_sources({"source_enabled": {"placer": False, "sacramento": True}}),
            ["sacramento"],
        )

    def test_sacramento_window_independent_of_placer(self):
        from fub_client import (
            apply_sacramento_source_settings,
            source_window_settings,
            sources_payload,
        )
        from sacramento_probate_monitor import portal_pause_seconds

        placer_only = {
            "lookback_days": 7,
            "lookahead_days": 3,
            "ecourt_pause_seconds": 2.5,
        }
        payload = sources_payload(placer_only)
        self.assertEqual(payload["placer"]["lookback_days"], 7)
        self.assertEqual(payload["placer"]["ecourt_pause_seconds"], 2.5)
        self.assertEqual(payload["sacramento"]["lookback_days"], 21)
        self.assertEqual(payload["sacramento"]["lookahead_days"], 21)
        self.assertEqual(payload["sacramento"]["ecourt_pause_seconds"], 1.2)

        saved = apply_sacramento_source_settings(
            placer_only,
            {
                "lookback_days": 30,
                "lookahead_days": 10,
                "ecourt_pause_seconds": 0.8,
            },
        )
        self.assertEqual(saved["lookback_days"], 7)
        self.assertEqual(saved["lookahead_days"], 3)
        self.assertEqual(saved["ecourt_pause_seconds"], 2.5)
        self.assertEqual(saved["sacramento_lookback_days"], 30)
        self.assertEqual(saved["sacramento_lookahead_days"], 10)
        self.assertEqual(saved["sacramento_ecourt_pause_seconds"], 0.8)

        sac = source_window_settings(saved, "sacramento")
        placer = source_window_settings(saved, "placer")
        self.assertEqual(sac["lookback_days"], 30)
        self.assertEqual(sac["lookahead_days"], 10)
        self.assertEqual(sac["ecourt_pause_seconds"], 0.8)
        self.assertEqual(placer["lookback_days"], 7)
        self.assertEqual(placer["ecourt_pause_seconds"], 2.5)

        shown = sources_payload(saved)["sacramento"]
        self.assertEqual(shown["lookback_days"], 30)
        self.assertEqual(shown["ecourt_pause_seconds"], 0.8)

        with self.assertRaises(ValueError):
            apply_sacramento_source_settings({}, {"lookback_days": 0})
        with self.assertRaises(ValueError):
            apply_sacramento_source_settings({}, {"lookahead_days": 121})
        with self.assertRaises(ValueError):
            apply_sacramento_source_settings({}, {"ecourt_pause_seconds": 0.1})

        flags_only = apply_sacramento_source_settings(saved, {"enabled": True})
        self.assertEqual(flags_only["sacramento_lookback_days"], 30)

        previous = {
            "SACRAMENTO_PORTAL_PAUSE": os.environ.get("SACRAMENTO_PORTAL_PAUSE"),
            "ECOURT_PAUSE": os.environ.get("ECOURT_PAUSE"),
        }
        try:
            os.environ["SACRAMENTO_PORTAL_PAUSE"] = "0.8"
            os.environ.pop("ECOURT_PAUSE", None)
            self.assertEqual(portal_pause_seconds(), 0.8)
            os.environ.pop("SACRAMENTO_PORTAL_PAUSE", None)
            os.environ["ECOURT_PAUSE"] = "2.5"
            self.assertEqual(portal_pause_seconds(), 2.5)
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


class PortalParseTests(unittest.TestCase):
    def test_search_hit(self):
        hit = _parse_search(SEARCH, "26PR001581")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["summary_id"], "2506537")
        self.assertEqual(hit["caption"], "ESTATE OF: HELEN ROW")
        self.assertIn("node/397/2506537", hit["court_url"])
        self.assertIn("prod-portal-sacramento-ca.journaltech.com", hit["court_url"])

    def test_summary_maps_to_placer_fields(self):
        parsed = parse_summary(SUMMARY)
        self.assertEqual(parsed["caption"], "ESTATE OF: HELEN ROW")
        self.assertEqual(parsed["case_type"], "Probate")
        self.assertIn("Letters Testamentary", parsed["category"])
        self.assertEqual(parsed["filed"], "06/04/2026")
        self.assertIn("11/18/2026", parsed["next_event"])
        self.assertIn("Department 126", parsed["next_event"])
        self.assertIn("Wayne L Row — Petitioner", parsed["parties"])
        self.assertIn("Helen Row — Decedent", parsed["parties"])
        self.assertTrue(any("Amended Petition" in line for line in parsed["hearings"]))
        self.assertTrue(parsed["hearing_history"])
        self.assertTrue(any(line.startswith("06/04/2026 Petition for Probate") for line in parsed["documents"]))
        self.assertEqual(parsed["fees"], [])

    def test_math_captcha_from_login_html(self):
        html = """
        <form id="user-login" action="/public-portal/?q=user/login" method="post">
          <input type="text" name="name" />
          <input type="password" name="pass" />
          <input type="hidden" name="form_build_id" value="form-abc" />
          <input type="hidden" name="form_id" value="user_login" />
          <input type="hidden" name="captcha_sid" value="27530157" />
          <input type="hidden" name="captcha_token" value="token" />
          6 + 11 = <input type="text" name="captcha_response" />
        </form>
        """
        self.assertEqual(solve_math_captcha(html), 17)
        action, data = login_form_payload(html, "user@example.com", "secret")
        self.assertIn("user/login", action)
        self.assertEqual(data["name"], "user@example.com")
        self.assertEqual(data["captcha_response"], "17")
        self.assertEqual(data["captcha_sid"], "27530157")
        self.assertEqual(data["form_id"], "user_login")
        self.assertNotIn("secret", action)

    def test_logged_in_html(self):
        self.assertTrue(session_is_logged_in('<body class="logged-in"><a href="?q=user/logout">Logout</a></body>'))
        self.assertFalse(session_is_logged_in('<body class="not-logged-in"><a href="?q=user/login">Login</a></body>'))

    def test_document_files_skip_confidential(self):
        html = """
        <div class="tabpane"><table class="table">
          <tr>
            <td></td><td>06/04/2026</td>
            <td>Confidential Supplemental to Duties and Liabilities of Personal Representation (DE147S)</td>
            <td>Wayne L Row (Petitioner)</td><td></td><td>Not Viewable</td>
          </tr>
          <tr>
            <td></td><td>06/04/2026</td>
            <td>Duties and Liabilities of Personal Representative</td>
            <td>Wayne L Row (Petitioner)</td><td>2</td>
            <td><button data-target="#doc_view_20399894">View Document</button></td>
          </tr>
          <tr>
            <td></td><td>06/04/2026</td>
            <td>Petition for Probate of Will &amp; Letters Testamentary</td>
            <td>Wayne L Row (Petitioner)</td><td>10</td>
            <td><button data-target="#doc_view_20399893">View Document</button></td>
          </tr>
        </table></div>
        """
        files = parse_document_files(html, "2506537")
        by_name = {item["name"]: item for item in files}
        self.assertTrue(document_is_blocked("Confidential Supplemental (DE-147S)", "Not Viewable"))
        confidential = [item for item in files if "DE147S" in item["name"] or "DE-147S" in item["name"]]
        self.assertTrue(confidential)
        self.assertFalse(confidential[0]["available"])
        self.assertFalse(confidential[0]["url"])
        petition = by_name["Petition for Probate of Will & Letters Testamentary"]
        self.assertTrue(petition["available"])
        self.assertIn("downloadFile/20399893/2506537", petition["url"])
        self.assertNotIn("node/45", petition["url"])
        duties = by_name["Duties and Liabilities of Personal Representative"]
        self.assertTrue(duties["available"])
        self.assertIn("downloadFile/20399894/2506537", duties["url"])

    def test_sacramento_mailing_required_and_fields_available(self):
        from fub_client import gate_reason, go_no_go_for_source, source_field_catalog

        spec = go_no_go_for_source("sacramento")
        required = {item["key"] for item in spec["required"]}
        self.assertIn("mailing_address", required)
        catalog = {item["key"]: item for item in source_field_catalog("sacramento")}
        self.assertFalse(catalog["de111_url"].get("unavailable"))
        self.assertFalse(catalog["mailing_address"].get("unavailable"))
        row = {
            "source_id": "sacramento",
            "case_number": "26PR001581",
            "petitioner": "Wayne Row",
        }
        self.assertEqual(
            gate_reason(row, {"cases": {}}, {}, strict_property=False, existing_id=None),
            "missing_petitioner_address",
        )
        row["mailing_address"] = "13950 N Point CT, Pine Grove, CA 95665"
        self.assertIsNone(
            gate_reason(row, {"cases": {}}, {}, strict_property=False, existing_id=None)
        )

    def test_skips_not_viewable_rows(self):
        html = """
        <div class="tabpane"><table class="table">
          <tr><td>06/04/2026</td><td>Petition for Probate</td></tr>
          <tr><td>06/04/2026</td><td>Confidential — Not Viewable</td></tr>
          <tr><td>06/05/2026</td><td>Letters Testamentary</td></tr>
        </table></div>
        """
        soup = BeautifulSoup(html, "html.parser")
        rows = _pane_rows(soup, 0)
        blob = " | ".join(" ".join(r) for r in rows)
        self.assertIn("Petition for Probate", blob)
        self.assertIn("Letters Testamentary", blob)
        self.assertNotIn("Not Viewable", blob)

    def test_pdf_accepts_sacramento_rows(self):
        from datetime import date
        from pdf_report import build_pdf

        row = {
            "case_number": "26PR001581",
            "decedent": "Helen Row",
            "caption": "ESTATE OF: HELEN ROW",
            "found": True,
            "filed": "06/04/2026",
            "case_type": "Probate",
            "parties": ["Wayne L Row — Petitioner", "Helen Row — Decedent"],
            "hearings": ["11/18/2026 09:00 AM — General Probate Amended Petition"],
            "hearing_history": ["09/08/2026 09:00 AM — General Probate — Rescheduled"],
            "documents": ["06/04/2026 Petition for Probate of Will & Letters Testamentary"],
            "will_offered": True,
            "iaea_requested": True,
            "petition_guess": "06/04/2026 Petition for Probate of Will & Letters Testamentary",
            "attorney": "Wayne Row, 13950 N Point Ct, Pine Grove, CA, 95665",
            "newspaper": "Sacramento Bee",
            "publication_line": "Aug 5,12,19 2026",
            "notice_url": "https://www.capublicnotice.com/advert/-Notices_999493",
            "court_url": "https://prod-portal-sacramento-ca.journaltech.com/public-portal/?q=node/397/2506537",
            "first_seen": True,
            "extra_flag": "Search card was shortened; full notice text was read from the CNPA advert page.",
        }
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "sacramento-dossier-test.pdf"
            build_pdf(
                [row],
                out,
                date(2026, 10, 9),
                date(2026, 9, 18),
                date(2026, 10, 30),
                county="Sacramento",
                source_note="test source",
                intro="test intro",
            )
            self.assertGreater(out.stat().st_size, 1000)


class PetitionDocsAndPreviewTests(unittest.TestCase):
    def setUp(self):
        self._env = {
            key: os.environ.get(key)
            for key in (
                "FUB_PETITION_DOCS_DIR",
                "FUB_SACRAMENTO_PETITION_DOCS_DIR",
                "FUB_DATA_SOURCE",
                "FUB_SOURCE",
            )
        }
        for key in self._env:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_petition_docs_dir_by_source_id(self):
        from datasources import petition_docs_dir
        from sacramento_probate_monitor import _petition_docs_dir

        data = Path(tempfile.mkdtemp())
        placer = petition_docs_dir("placer", data_dir=data)
        sac = petition_docs_dir("sacramento", data_dir=data)
        self.assertEqual(placer, data / "reports" / "docs")
        self.assertEqual(sac, data / "reports" / "sacramento" / "docs")
        self.assertNotEqual(placer, sac)
        os.environ["FUB_PETITION_DOCS_DIR"] = str(data / "reports" / "docs")
        hijack = petition_docs_dir("sacramento", out_dir=data / "reports" / "sacramento")
        self.assertEqual(hijack, data / "reports" / "sacramento" / "docs")
        self.assertEqual(
            _petition_docs_dir(data / "reports" / "sacramento"),
            data / "reports" / "sacramento" / "docs",
        )
        derived = petition_docs_dir("sacramento")
        self.assertTrue(str(derived).replace("\\", "/").endswith("sacramento/docs"))

    def test_preview_lead_source_sacramento(self):
        from datasources import stamp_fub_tags
        from fub_client import mapping_for_export, preview_one_record

        os.environ["FUB_SOURCE"] = "probate"
        row = stamp_fub_tags(
            [
                {
                    "case_number": "26PR002736",
                    "petitioner": "Grace Boeger-Balubar",
                    "mailing_address": "123 Main St, Sacramento, CA 95814",
                    "court_url": (
                        "https://prod-portal-sacramento-ca.journaltech.com/"
                        "public-portal/?q=node/397/2506537"
                    ),
                }
            ],
            "sacramento",
        )[0]
        self.assertEqual(row["lead_source"], "probate")
        self.assertEqual(
            mapping_for_export({}, "sacramento")["lead_source"],
            "probate",
        )
        preview = preview_one_record([row])
        rec = preview["verify_record"]
        self.assertEqual(rec["lead_source"], "probate")
        self.assertEqual(rec["mapped"]["lead_source"], "probate")
        self.assertEqual(rec["source_id"], "sacramento")
        blob = " ".join(item.get("source") or "" for item in rec["source_extract"])
        self.assertNotIn("node/45", blob)
        self.assertNotIn("eCourt Public", blob)
        self.assertIn("node/397", blob)


def _notice(**overrides) -> Notice:
    fields = dict(
        case_number="26PR002736",
        decedent="Grace",
        petitioner="Sam",
        court_county="",
        hearing="",
        attorney="",
        attorney_phone="",
        newspaper="Folsom Telegraph",
        post_date="2026-10-16",
        publication_line="",
        will_offered=False,
        iaea_requested=False,
        refcode="",
        advert_id="Notices_1",
        notice_url="https://www.capublicnotice.com/advert/-x",
        snippet="",
        raw_text="",
    )
    fields.update(overrides)
    return Notice(**fields)


class CnpaPaginationTests(unittest.TestCase):
    def test_page_sequence_skips_duplicate_first_page(self):
        self.assertEqual(cnpa_page_sequence(1), [0])
        self.assertEqual(cnpa_page_sequence(2), [0, 2])
        self.assertEqual(cnpa_page_sequence(5), [0, 2, 3, 4, 5])

    def test_parse_cnpa_max_pages_from_loadmore_js(self):
        html = "var maxPages = '1' || '1';\nconsole.log(nextPage+ \" of 1\");"
        self.assertEqual(parse_cnpa_max_pages(html), 1)
        self.assertEqual(parse_cnpa_max_pages("var maxPages = '89' || '1';"), 89)
        self.assertIsNone(parse_cnpa_max_pages("<html></html>"))

    def test_empty_county_omits_newspaper_filter(self):
        from datetime import date

        start, end = date(2026, 7, 12), date(2026, 12, 9)
        bare = search_url(start, end, county="", keywords='"NOTICE OF PETITION"')
        self.assertNotIn("county=", bare)
        tagged = search_url(
            start, end, county="Sacramento", keywords='"NOTICE OF PETITION"'
        )
        self.assertIn("county=Sacramento", tagged)

    def test_keep_sacramento_court_after_unscoped_search(self):
        scoped = _notice(case_number="26PR002736", advert_id="a")
        placer = _notice(
            case_number="",
            advert_id="b",
            court_county="PLACER",
            raw_text="Superior Court of California, County of PLACER",
        )
        sac = _notice(
            case_number="26PR001104",
            advert_id="c",
            court_county="SACRAMENTO",
            raw_text="Superior Court of California, County of SACRAMENTO",
        )
        self.assertTrue(is_sacramento_court_notice(sac))
        self.assertFalse(is_sacramento_court_notice(placer))
        kept = keep_sacramento_notices(
            [scoped, placer, sac], {scoped.case_number}
        )
        keys = {item.case_number or item.advert_id for item in kept}
        self.assertEqual(keys, {"26PR002736", "26PR001104"})


if __name__ == "__main__":
    unittest.main()
