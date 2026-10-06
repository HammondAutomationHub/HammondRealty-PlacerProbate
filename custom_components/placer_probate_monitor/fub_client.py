"""Follow Up Boss Events API client for new probate petitioners."""

from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import re
from pathlib import Path

import requests

try:
    from .petition_parse import STATE_ALT as _STATE_ALT
except ImportError:
    from petition_parse import STATE_ALT as _STATE_ALT


def _progress_fub(summary: dict, action: str, key: str | None = None) -> None:
    try:
        from .job_progress import report_progress
    except ImportError:
        from job_progress import report_progress

    posted = int(summary.get("posted") or 0)
    updated = int(summary.get("updated") or 0)
    skipped = int(summary.get("skipped") or 0)
    case = key or ""
    detail = f"{action} {case}".strip() if action else "importing"
    report_progress(
        "fub",
        f"Follow Up Boss: {detail} · posted {posted}, updated {updated}, skipped {skipped}",
        fub_posted=posted,
        fub_updated=updated,
        fub_skipped=skipped,
        case_number=key,
    )

COURT_SEARCH_DEFAULT = "https://webportal.placerco.org/eCourtPublic/?q=node/48"
CASE_PORTAL_TEMPLATE = "https://webportal.placerco.org/eCourtPublic/?q=node/45/{nid}"
CASE_PORTAL_RE = re.compile(r"node/45/(\d+)", re.I)
DOWNLOAD_CASE_RE = re.compile(r"downloadFile/\d+/(\d+)", re.I)
MAPPING_PATH = Path(__file__).resolve().parent / "fub_mapping.yaml"
ADDR_RE = re.compile(
    rf"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*"
    rf"(?P<state>{_STATE_ALT})\b"
    rf"\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?$",
    re.I,
)
ADDR_FLEX_RE = re.compile(
    rf"^(?P<street>.+?),\s*(?P<city>[A-Za-z .'-]+?)(?:\s*,\s*|\s+)"
    rf"(?P<state>{_STATE_ALT})\b"
    rf"\s*(?P<zip>\d{{5}}(?:-\d{{4}})?)?\s*$",
    re.I,
)
COUNTY_NOISE_RE = re.compile(r",?\s*Placer(?:\s+County)?\b,?", re.I)
NOT_CITIES = {"placer", "placer county", "county", "california"}
ADDRESS_COMPONENT_KEYS = {
    "decedent_city",
    "decedent_zip",
    "mailing_city",
    "mailing_state",
    "mailing_zip",
}
ADDRESS1_TYPE = "home"
ADDRESS2_TYPE = "mailing"


def case_portal_url(row: dict) -> str:
    """Per-case eCourt Public page, e.g. ?q=node/45/1322377."""
    candidates = [
        row.get("court_url"),
        row.get("url"),
        row.get("portal_url"),
        row.get("court_search"),
    ]
    for doc in row.get("document_files") or []:
        if isinstance(doc, dict):
            candidates.append(doc.get("url"))
    for raw in candidates:
        text = str(raw or "").strip()
        if not text:
            continue
        match = CASE_PORTAL_RE.search(text)
        if match:
            return CASE_PORTAL_TEMPLATE.format(nid=match.group(1))
        match = DOWNLOAD_CASE_RE.search(text)
        if match:
            return CASE_PORTAL_TEMPLATE.format(nid=match.group(1))
    return ""


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def resolve_mapping_path(path: Path | None = None) -> Path:
    if path is not None:
        return Path(path)
    env = os.environ.get("FUB_MAPPING_PATH", "").strip()
    if env:
        return Path(env)
    return MAPPING_PATH


def writable_mapping_path(path: Path | None = None) -> Path:
    target = resolve_mapping_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _as_bool(value, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_mapping(data: dict) -> dict:
    mapping = dict(data or {})
    skip = mapping.get("skip_petitioner_contains") or []
    if isinstance(skip, str):
        skip = [part.strip() for part in skip.split(",") if part.strip()]
    mapping["skip_petitioner_contains"] = [str(x).strip() for x in skip if str(x).strip()]
    send = dict(mapping.get("send") or {})
    mapping["send"] = {str(k): _as_bool(v, False) for k, v in send.items()}
    fields = mapping.get("custom_fields") or {}
    mapping["custom_fields"] = {
        str(k): str(v).strip()
        for k, v in (fields.items() if isinstance(fields, dict) else [])
        if str(k).strip() and str(v).strip()
    }
    sources = mapping.get("source_mappings") or {}
    normalized_sources: dict = {}
    if isinstance(sources, dict):
        for source_id, block in sources.items():
            if not isinstance(block, dict):
                continue
            nested = block.get("custom_fields") or {}
            normalized_sources[str(source_id)] = {
                "custom_fields": {
                    str(k): str(v).strip()
                    for k, v in (nested.items() if isinstance(nested, dict) else [])
                    if str(k).strip() and str(v).strip()
                }
            }
    if "placer" not in normalized_sources and mapping["custom_fields"]:
        normalized_sources["placer"] = {"custom_fields": dict(mapping["custom_fields"])}
    mapping["source_mappings"] = normalized_sources
    mapping["custom_fields"] = _split_person_source_keys(mapping["custom_fields"])
    mapping["custom_fields"] = _rewrite_address2_keys(mapping["custom_fields"])
    for source_id, block in mapping["source_mappings"].items():
        block["custom_fields"] = _rewrite_address2_keys(
            _split_person_source_keys(block.get("custom_fields") or {})
        )
        mapping["source_mappings"][source_id] = block
    if "placer" in mapping["source_mappings"]:
        mapping["custom_fields"] = dict(
            mapping["source_mappings"]["placer"].get("custom_fields") or {}
        )
    else:
        mapping["source_mappings"]["placer"] = {
            "custom_fields": dict(mapping["custom_fields"])
        }
    return mapping


def _split_person_source_keys(fields: dict) -> dict:
    """Replace a full petitioner name mapped onto first/last with split source keys."""
    out = dict(fields or {})
    target = str(out.get("petitioner") or "").strip()
    if target in PERSON_NAME_KEYS:
        out.pop("petitioner", None)
        if target in {"firstName", "person.firstName"}:
            out.setdefault("petitioner_first", "firstName")
            out.setdefault("petitioner_last", "lastName")
        elif target in {"lastName", "person.lastName"}:
            out.setdefault("petitioner_last", "lastName")
            out.setdefault("petitioner_first", "firstName")
        else:
            out.setdefault("petitioner_first", "firstName")
            out.setdefault("petitioner_last", "lastName")
    if not out.get("petitioner_first"):
        out["petitioner_first"] = "firstName"
    if not out.get("petitioner_last"):
        out["petitioner_last"] = "lastName"
    if not out.get("petitioner_email"):
        out["petitioner_email"] = "emails"
    if not out.get("petitioner_phone"):
        out["petitioner_phone"] = "phones"
    return out


def _rewrite_address2_keys(fields: dict) -> dict:
    aliases = {
        "mailingaddress",
        "mailing",
        "addresses.mailing",
        "person.mailingaddress",
    }
    out: dict[str, str] = {}
    for key, value in (fields or {}).items():
        target = str(value or "").strip()
        low = target.lower()
        if low.startswith("person."):
            low = low.split(".", 1)[1]
        out[str(key)] = "address2" if low in aliases else target
    return out


def _read_mapping_file(target: Path) -> dict:
    text = target.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
        if isinstance(data, dict):
            return _normalize_mapping(data)
    except Exception:
        pass
    return _normalize_mapping(_parse_simple_mapping(text))


def load_mapping(path: Path | None = None) -> dict:
    candidates: list[Path] = []
    if path is not None:
        candidates.append(Path(path))
    env = os.environ.get("FUB_MAPPING_PATH", "").strip()
    if env:
        candidates.append(Path(env))
    candidates.append(MAPPING_PATH)
    seen: set[str] = set()
    for target in candidates:
        key = str(target)
        if key in seen:
            continue
        seen.add(key)
        if target.exists():
            return _read_mapping_file(target)
    return {}


def _parse_simple_mapping(text: str) -> dict:
    """Minimal YAML subset so the mapping file still loads without PyYAML."""
    mapping: dict = {
        "skip_petitioner_contains": [],
        "custom_fields": {},
        "send": {},
    }
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.startswith(" ") and ":" not in line.strip().lstrip("-"):
            value = line.strip().lstrip("- ").strip().strip('"')
            if section == "skip_petitioner_contains":
                mapping["skip_petitioner_contains"].append(value)
            continue
        if line.startswith(" ") and ":" in line:
            key, _, value = line.strip().partition(":")
            mapping.setdefault(section or "custom_fields", {})[key.strip()] = value.strip().strip('"')
            continue
        if line.endswith(":") and not line.startswith(" "):
            section = line[:-1].strip()
            if section in {"skip_petitioner_contains"}:
                mapping[section] = []
            elif section in {"custom_fields", "send"}:
                mapping[section] = {}
            continue
        if ":" in line and not line.startswith(" "):
            key, _, value = line.partition(":")
            mapping[key.strip()] = value.strip().strip('"')
            section = None
    return mapping


MAPPING_HEADER = """# Follow Up Boss field mapping for Placer Probate Monitor.
# Written by the mapping UI; hand-editing this file is still supported.
# Do not map attorney_phone onto person.phones.
# Decedent is not the FUB Person name (petitioner is).
"""

PERSON_PHONE_KEYS = {"phones", "person.phones"}
PERSON_NAME_KEYS = {"firstName", "lastName", "person.firstName", "person.lastName"}

PROBATE_SOURCE_FIELDS = [
    {
        "key": "petitioner_first",
        "label": "Petitioner first name",
        "group": "petitioner",
        "source": "eCourt petitioner, all tokens except last",
        "notes": "This is the source field for FUB firstName.",
        "person": "firstName",
        "custom": True,
    },
    {
        "key": "petitioner_last",
        "label": "Petitioner last name",
        "group": "petitioner",
        "source": "eCourt petitioner, last token (plus Jr/Sr/II/III)",
        "notes": "This is the source field for FUB lastName.",
        "person": "lastName",
        "custom": True,
    },
    {
        "key": "petitioner",
        "label": "Petitioner full name",
        "group": "petitioner",
        "source": "eCourt parties, else CNPA notice",
        "notes": "Raw extracted name. Map first/last above, not this row.",
        "person": None,
        "custom": False,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "mailing_address",
        "label": "Petitioner address",
        "group": "petitioner",
        "source": "DE-111 item 8 / 3h or DE-147 acknowledgment, whichever has it",
        "notes": "Map this source field to Address 1 or Address 2 in the mapping UI. Not item 1 (publication) and not the attorney caption.",
        "person": None,
        "custom": True,
    },
    {
        "key": "mailing_city",
        "label": "Petitioner city",
        "group": "petitioner",
        "source": "DE-111 or DE-147, whichever has it",
        "notes": "City for the petitioner mailing line. Map the street line, not this row, to Address 1 or 2.",
        "person": None,
        "custom": True,
    },
    {
        "key": "mailing_state",
        "label": "Petitioner state",
        "group": "petitioner",
        "source": "DE-111 or DE-147, whichever has it",
        "notes": "State for the petitioner mailing line. Map the street line, not this row, to Address 1 or 2.",
        "person": None,
        "custom": True,
    },
    {
        "key": "mailing_zip",
        "label": "Petitioner ZIP",
        "group": "petitioner",
        "source": "DE-111 or DE-147, whichever has it",
        "notes": "ZIP for the petitioner mailing line. Map the street line, not this row, to Address 1 or 2.",
        "person": None,
        "custom": True,
    },
    {
        "key": "petitioner_email",
        "label": "Petitioner email",
        "group": "petitioner",
        "source": "DE-111 or DE-147, whichever has it",
        "notes": "Never use attorney caption email.",
        "person": "emails",
        "custom": True,
    },
    {
        "key": "petitioner_phone",
        "label": "Petitioner phone",
        "group": "petitioner",
        "source": "DE-111 or DE-147, whichever has it",
        "notes": "Never map attorney_phone onto person.phones.",
        "person": "phones",
        "custom": True,
    },
    {
        "key": "decedent",
        "label": "Decedent name",
        "group": "decedent",
        "source": "CNPA notice / eCourt decedent party",
        "notes": "Never Person first/last name. Custom field only.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "decedent_first",
        "label": "Decedent first name",
        "group": "decedent",
        "source": "Split from decedent name",
        "notes": "Custom field only. Do not map onto Person firstName.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "decedent_last",
        "label": "Decedent last name",
        "group": "decedent",
        "source": "Split from decedent name",
        "notes": "Custom field only. Do not map onto Person lastName.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "decedent_residence",
        "label": "Estate location (DE-111 3.a.(2))",
        "group": "decedent",
        "source": "DE-111 item 3.a.(2) when that box is marked; otherwise item 3c",
        "notes": "The street in 3.a.(2) (estate in the county named above). Never the 'at (place)' death location.",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_city",
        "label": "Residence city",
        "group": "decedent",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_zip",
        "label": "Residence ZIP",
        "group": "decedent",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_died",
        "label": "Date of death",
        "group": "decedent",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "death_place",
        "label": "Place of death",
        "group": "decedent",
        "source": "DE-111 item 3 'at (place)'",
        "notes": "County/state of death only. Do not map this to Address 1 or 2.",
        "person": None,
        "custom": True,
    },
    {
        "key": "case_number",
        "label": "Case number",
        "group": "other",
        "notes_label": "Casenumber",
        "source": "CNPA notice / eCourt search",
        "notes": "S-PR number used as the lead key.",
        "person": None,
        "custom": True,
    },
    {
        "key": "estate_real",
        "label": "Real property GMV",
        "group": "other",
        "source": "Petition PDF",
        "notes": "Gross fair market value from DE-111, shown as $370,000.00. $0.00 is still a value.",
        "person": None,
        "custom": True,
    },
    {
        "key": "estate_personal",
        "label": "Personal property",
        "group": "other",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "hearing",
        "label": "Hearing",
        "group": "other",
        "source": "eCourt next event, else notice text",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "court_search",
        "label": "eCourt Public case URL",
        "group": "other",
        "source": "eCourt search hit (node/45/…)",
        "notes": "Per-case portal page. Posted to Follow Up Boss Notes.",
        "person": None,
        "custom": True,
        "notes_label": "Court",
    },
    {
        "key": "notice_url",
        "label": "Newspaper notice URL",
        "group": "other",
        "source": "CNPA",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "petition_pdf",
        "label": "Petition PDF filename",
        "group": "other",
        "source": "Downloaded DE-111",
        "notes": "Local filename only. Map DE-111 PDF URL below for the download link.",
        "person": None,
        "custom": True,
    },
    {
        "key": "de111_url",
        "label": "DE-111 PDF URL",
        "group": "other",
        "notes_label": "DE-111",
        "source": "Home Assistant API URL for the stored DE-111",
        "notes": "Signed download URL. Map to Notes to include DE-111: {url}.",
        "person": None,
        "custom": True,
    },
    {
        "key": "de147_url",
        "label": "DE-147 PDF URL",
        "group": "other",
        "notes_label": "DE-147",
        "source": "Home Assistant API URL for the stored DE-147",
        "notes": "Signed download URL. Map to Notes to include DE-147: {url}.",
        "person": None,
        "custom": True,
    },
    {
        "key": "filed",
        "label": "Filed date",
        "group": "other",
        "source": "eCourt search / docket",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "caption",
        "label": "Case caption",
        "group": "other",
        "source": "eCourt",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "attorney",
        "label": "Attorney (notice)",
        "group": "other",
        "source": "CNPA notice",
        "notes": "Counsel is not the Person. Custom field only.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "attorney_phone",
        "label": "Attorney phone",
        "group": "other",
        "source": "CNPA notice",
        "notes": "Never map onto person.phones.",
        "person": None,
        "custom": True,
        "block": ["phones"],
    },
    {
        "key": "newspaper",
        "label": "Newspaper",
        "group": "other",
        "source": "CNPA",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "will_offered",
        "label": "Will offered",
        "group": "other",
        "source": "CNPA notice",
        "notes": "Yes/No.",
        "person": None,
        "custom": True,
    },
    {
        "key": "iaea_requested",
        "label": "IAEA requested",
        "group": "other",
        "source": "CNPA notice",
        "notes": "Yes/No.",
        "person": None,
        "custom": True,
    },
    {
        "key": "parties",
        "label": "Parties",
        "group": "other",
        "source": "eCourt summary",
        "notes": "Petitioner, decedent, objector, administrator.",
        "person": None,
        "custom": True,
    },
]
FUB_DESTINATIONS = [
    {
        "id": "person.firstName",
        "label": "Person firstName",
        "group": "person",
        "locked_to": "petitioner_first",
    },
    {
        "id": "person.lastName",
        "label": "Person lastName",
        "group": "person",
        "locked_to": "petitioner_last",
    },
    {
        "id": "person.addresses",
        "label": "Person Address 1",
        "group": "person",
    },
    {
        "id": "person.address2",
        "label": "Person Address 2",
        "group": "person",
    },
    {
        "id": "person.emails",
        "label": "Person emails",
        "group": "person",
        "locked_to": "petitioner_email",
    },
    {
        "id": "person.phones",
        "label": "Person phones",
        "group": "person",
        "locked_to": "petitioner_phone",
    },
    {
        "id": "person.assignedTo",
        "label": "Person assignedTo",
        "group": "person",
        "from_config": "fub_assigned_to",
    },
    {
        "id": "person.stage",
        "label": "Person stage",
        "group": "person",
        "from_config": "fub_stage",
    },
    {
        "id": "event.source",
        "label": "Event source",
        "group": "event",
        "from_config": "fub_source",
    },
    {
        "id": "event.message",
        "label": "Event message + description",
        "group": "event",
    },
    {
        "id": "event.system",
        "label": "Event system name",
        "group": "event",
    },
    {
        "id": "custom",
        "label": "Custom field (API name, e.g. customCaseNumber)",
        "group": "custom",
    },
]

FUB_BUILTIN_FIELDS = [
    {"name": "firstName", "label": "First name", "group": "Person", "type": "person"},
    {"name": "lastName", "label": "Last name", "group": "Person", "type": "person"},
    {"name": "assignedTo", "label": "Assigned to", "group": "Person", "type": "person"},
    {"name": "addresses", "label": "Address 1", "group": "Person", "type": "person"},
    {"name": "address2", "label": "Address 2", "group": "Person", "type": "person"},
    {"name": "stage", "label": "Stage", "group": "Person", "type": "person"},
    {"name": "source", "label": "Lead source", "group": "Person", "type": "person"},
    {"name": "tags", "label": "Tags", "group": "Person", "type": "person"},
    {"name": "background", "label": "Background", "group": "Person", "type": "person"},
    {"name": "notes", "label": "Notes", "group": "Person", "type": "person"},
    {"name": "emails", "label": "Email", "group": "Person", "type": "person"},
    {"name": "phones", "label": "Phone", "group": "Person", "type": "person"},
]

PERSON_BUILTIN_TARGETS = {
    "firstName",
    "lastName",
    "assignedTo",
    "addresses",
    "stage",
    "source",
    "tags",
    "background",
    "emails",
    "phones",
}

ADDRESS_SLOT_TARGETS = {
    "addresses": 0,
    "address1": 0,
    "address 1": 0,
    "person.addresses": 0,
    "address2": 1,
    "address 2": 1,
    "mailingaddress": 1,
    "mailing": 1,
    "addresses.mailing": 1,
}

NOTES_TARGETS = {"notes", "note", "background"}

SEND_TOGGLES = [
    {"key": "firstName", "label": "Send petitioner firstName", "editable": True},
    {"key": "lastName", "label": "Send petitioner lastName", "editable": True},
    {"key": "emails", "label": "Send petitioner email", "editable": True},
    {"key": "phones", "label": "Send petitioner phone", "editable": True},
    {"key": "assignedTo", "label": "Send assignedTo from config", "editable": True},
    {"key": "stage", "label": "Send person stage from config", "editable": True},
    {"key": "source", "label": "Send event source from config", "editable": True},
    {"key": "message", "label": "Send event message/description", "editable": True},
    {"key": "custom_fields", "label": "Send custom fields below", "editable": True},
    {
        "key": "de111_file",
        "label": "Post DE-111 PDF link in Follow Up Boss Notes",
        "editable": True,
    },
    {
        "key": "de147_file",
        "label": "Post DE-147 duties PDF link in Follow Up Boss Notes",
        "editable": True,
    },
    {
        "key": "court_url_note",
        "label": "Post the per-case eCourt Public URL in Follow Up Boss Notes",
        "editable": True,
    },
]

GO_NO_GO = [
    "Petitioner is the FUB Person. Decedent is never firstName/lastName.",
    "No go-case without a petitioner mailing address on the extract. Map petitioner mailing and decedent last residence to Address 1 or Address 2 in the mapping UI. Item 1 is publication. Attorney caption is not petitioner mailing.",
    "Never map attorney_phone onto person.phones. Attorney caption address is not petitioner mailing.",
    "Last residence is DE-111 text, not a verified APN.",
    "Notes gets the per-case eCourt Public URL, a unique DE-111 PDF link, and a DE-147 duties link. Petitioner phone and email come from either form when present, never from the attorney caption.",
    "Only NEW cases are created on a full run. Verify can update a person ID you enter, reuse the last test person, or create one if none exist.",
]

SOURCE_GO_NO_GO = {
    "placer": {
        "required": [
            {
                "key": "case_number",
                "label": "Case number",
                "from": "CNPA notice / eCourt",
            },
            {
                "key": "petitioner_first",
                "label": "Petitioner first name",
                "from": "eCourt petitioner",
            },
            {
                "key": "petitioner_last",
                "label": "Petitioner last name",
                "from": "eCourt petitioner",
            },
            {
                "key": "mailing_address",
                "label": "Petitioner address",
                "from": "DE-111 item 8 / 3h or DE-147, whichever has it",
            },
        ],
        "optional": [
            {
                "key": "petitioner_email",
                "label": "Petitioner email",
                "from": "DE-111 or DE-147, whichever has it",
            },
            {
                "key": "petitioner_phone",
                "label": "Petitioner phone",
                "from": "DE-111 or DE-147, whichever has it",
            },
            {
                "key": "decedent_residence",
                "label": "Estate location (3.a.(2))",
                "from": "DE-111 item 3.a.(2) street; never 'at (place)'",
                "when": "Required only if “Require decedent residence” is on",
            },
            {
                "key": "court_url",
                "label": "eCourt Public case URL",
                "from": "Search hit ?q=node/45/…",
                "when": "Posted to Follow Up Boss Notes when present",
            },
        ],
        "rules": GO_NO_GO,
    },
    "sacramento": {
        "required": [],
        "optional": [],
        "rules": [
            "Sacramento import is not live. Go/no-go data requirements will be listed here when this county is wired.",
        ],
    },
    "nevada": {
        "required": [],
        "optional": [],
        "rules": [
            "Nevada County import is not live. Go/no-go data requirements will be listed here when this county is wired.",
        ],
    },
}


def go_no_go_for_source(source_id: str) -> dict:
    key = str(source_id or "placer")
    spec = SOURCE_GO_NO_GO.get(key) or {
        "required": [],
        "optional": [],
        "rules": ["Go/no-go is not defined for this source yet."],
    }
    return {
        "source_id": key,
        "required": list(spec.get("required") or []),
        "optional": list(spec.get("optional") or []),
        "rules": list(spec.get("rules") or []),
    }


DATA_SOURCES = [
    {
        "id": "placer",
        "name": "Placer County",
        "status": "live",
        "description": "California Newspaper Public Notices plus Placer eCourt Public and DE-111 petitions.",
        "extracts": "CNPA notice, eCourt docket, petition PDF",
    },
    {
        "id": "sacramento",
        "name": "Sacramento County",
        "status": "coming_soon",
        "description": "Next county source. Import settings and field catalog will live on this screen.",
        "extracts": "Not wired yet",
    },
    {
        "id": "nevada",
        "name": "Nevada County",
        "status": "coming_soon",
        "description": "Queued after Sacramento County.",
        "extracts": "Not wired yet",
    },
]

SOURCE_SETTING_KEYS = [
    "lookback_days",
    "lookahead_days",
    "county",
    "keywords",
    "skip_portal",
    "generate_pdf",
    "ecourt_pause_seconds",
    "max_search_pages",
]


def source_field_catalog(source_id: str) -> list[dict]:
    if str(source_id or "placer") == "placer":
        return PROBATE_SOURCE_FIELDS
    rows = []
    for item in PROBATE_SOURCE_FIELDS:
        row = dict(item)
        row["unavailable"] = True
        row["source"] = "Not extracted yet"
        rows.append(row)
    return rows


def custom_fields_for_source(mapping: dict, source_id: str) -> dict:
    source_id = str(source_id or "placer")
    sources = mapping.get("source_mappings") or {}
    block = sources.get(source_id) or {}
    fields = block.get("custom_fields") if isinstance(block, dict) else None
    if isinstance(fields, dict) and fields:
        return fields
    if source_id == "placer":
        return mapping.get("custom_fields") or {}
    return {}


def sources_payload(settings: dict | None = None) -> dict:
    placer = {}
    for key in SOURCE_SETTING_KEYS:
        placer[key] = (settings or {}).get(key)
    if not placer.get("county"):
        placer["county"] = "Placer"
    return {
        "sources": DATA_SOURCES,
        "active": "placer",
        "placer": placer,
        "fields": source_field_catalog("placer"),
        "source_fields": {item["id"]: source_field_catalog(item["id"]) for item in DATA_SOURCES},
        "source_go_no_go": {
            item["id"]: go_no_go_for_source(item["id"]) for item in DATA_SOURCES
        },
    }


def mapping_catalog() -> dict:
    return {
        "data_source": "placer",
        "data_source_name": "Placer County",
        "probate_fields": PROBATE_SOURCE_FIELDS,
        "fub_destinations": FUB_DESTINATIONS,
        "send_toggles": SEND_TOGGLES,
        "go_no_go": GO_NO_GO,
        "source_go_no_go": {
            item["id"]: go_no_go_for_source(item["id"]) for item in DATA_SOURCES
        },
        "default_custom_fields": {
            "petitioner_first": "firstName",
            "petitioner_last": "lastName",
            "petitioner_email": "emails",
            "petitioner_phone": "phones",
        },
    }


def mapping_errors(mapping: dict, *, source_id: str = "placer") -> list[str]:
    errors: list[str] = []
    send = mapping.get("send") or {}
    fields = mapping.get("custom_fields") or {}
    by_key = {item["key"]: item for item in source_field_catalog(source_id)}
    live = str(source_id or "placer") == "placer"
    for local_key, api_name in fields.items():
        api = str(api_name or "").strip()
        if not api:
            continue
        meta = by_key.get(local_key) or {}
        blocked = set(meta.get("block") or [])
        if api in PERSON_PHONE_KEYS or api in blocked and api in {"phones", "person.phones"}:
            if "phones" in blocked or local_key == "attorney_phone":
                errors.append(f"Never map {local_key} onto person.phones.")
        if api in PERSON_NAME_KEYS and local_key not in {
            "petitioner_first",
            "petitioner_last",
        }:
            errors.append(f"{local_key} cannot map onto Person first/last name.")
        if live and meta.get("unavailable"):
            errors.append(f"{local_key} is not extracted yet.")
        if api in {"phones", "emails", "person.phones", "person.emails"}:
            if local_key not in {"petitioner_phone", "petitioner_email"}:
                errors.append(f"{local_key} cannot map onto person emails/phones.")
    return errors


def _dump_simple_mapping(mapping: dict) -> str:
    lines = [
        f"system: {mapping.get('system') or 'PlacerProbateMonitor'}",
        f'court_search_url: "{mapping.get("court_search_url") or COURT_SEARCH_DEFAULT}"',
        f'subject_address_type: "{mapping.get("subject_address_type") or "subject property"}"',
        "",
        "skip_petitioner_contains:",
    ]
    skip = mapping.get("skip_petitioner_contains") or []
    if skip:
        lines.extend(f"  - {item}" for item in skip)
    else:
        lines.append("  []")
    lines.extend(["", "custom_fields:"])
    fields = mapping.get("custom_fields") or {}
    if fields:
        for key, value in fields.items():
            lines.append(f"  {key}: {value}")
    else:
        lines.append("  {}")
    lines.extend(["", "send:"])
    send = mapping.get("send") or {}
    for item in SEND_TOGGLES:
        key = item["key"]
        value = send.get(key, False if item.get("forced") is False else True)
        if item.get("forced") is False:
            value = False
        lines.append(f"  {key}: {'true' if value else 'false'}")
    return "\n".join(lines) + "\n"


def save_mapping(mapping: dict, path: Path | None = None) -> Path:
    incoming = _normalize_mapping(mapping)
    source_id = str(mapping.get("source_id") or "placer")
    existing = load_mapping(path)
    sources = dict(existing.get("source_mappings") or {})
    if existing.get("custom_fields") and "placer" not in sources:
        sources["placer"] = {"custom_fields": dict(existing.get("custom_fields") or {})}
    sources[source_id] = {"custom_fields": dict(incoming.get("custom_fields") or {})}
    send = dict(incoming.get("send") or existing.get("send") or {})
    incoming["send"] = send
    incoming["source_mappings"] = sources
    errors = mapping_errors(
        {**incoming, "custom_fields": sources[source_id]["custom_fields"]},
        source_id=source_id,
    )
    if errors:
        raise ValueError("; ".join(errors))
    incoming["custom_fields"] = dict(
        (sources.get("placer") or {}).get("custom_fields") or {}
    )
    if not incoming.get("system"):
        incoming["system"] = existing.get("system") or "PlacerProbateMonitor"
    if not incoming.get("court_search_url"):
        incoming["court_search_url"] = (
            existing.get("court_search_url") or COURT_SEARCH_DEFAULT
        )
    if not incoming.get("subject_address_type"):
        incoming["subject_address_type"] = (
            existing.get("subject_address_type") or "subject property"
        )
    incoming.pop("source_id", None)
    if "skip_petitioner_contains" not in mapping:
        incoming["skip_petitioner_contains"] = existing.get("skip_petitioner_contains") or []
    target = writable_mapping_path(path)
    try:
        import yaml  # type: ignore

        body = yaml.safe_dump(incoming, sort_keys=False, allow_unicode=True)
    except Exception:
        body = _dump_simple_mapping(incoming)
    target.write_text(MAPPING_HEADER + "\n" + body, encoding="utf-8")
    return target


def _stringify_field(value) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if isinstance(value, list):
        return "; ".join(str(x) for x in value if x)
    if value is None:
        return ""
    return str(value).strip()


def _money_field(value) -> str:
    raw = _stringify_field(value)
    if not raw:
        return ""
    cleaned = raw.replace("$", "").replace(",", "").strip()
    try:
        return f"${float(cleaned):,.2f}"
    except ValueError:
        return raw


def _row_contact(row: dict) -> dict:
    try:
        from .petition_parse import merge_petitioner_contact
    except ImportError:
        from petition_parse import merge_petitioner_contact

    return merge_petitioner_contact(
        row,
        row.get("contact_de111") or {},
        row.get("contact_de147") or {},
    )


def source_extract_rows(row: dict, mapping: dict) -> list[dict]:
    values = probate_export_values(row, mapping)
    seen: set[str] = set()
    out: list[dict] = []
    for field in PROBATE_SOURCE_FIELDS:
        key = str(field.get("key") or "")
        if not key:
            continue
        seen.add(key)
        if field.get("unavailable"):
            out.append(
                {
                    "key": key,
                    "label": field.get("label") or key,
                    "source": field.get("source") or "",
                    "value": "",
                    "empty": True,
                    "unavailable": True,
                    "notes": field.get("notes") or "",
                }
            )
            continue
        value = values.get(key) or ""
        out.append(
            {
                "key": key,
                "label": field.get("label") or key,
                "source": field.get("source") or "",
                "value": value,
                "empty": value in (None, ""),
                "unavailable": False,
                "notes": field.get("notes") or "",
            }
        )
    extra_labels = {
        "county_resident": "County resident",
        "case_type": "Case type",
        "court_status": "Court status",
    }
    for key, label in extra_labels.items():
        if key in seen:
            continue
        value = values.get(key) or ""
        if value in (None, ""):
            continue
        out.append(
            {
                "key": key,
                "label": label,
                "source": "eCourt",
                "value": value,
                "empty": False,
                "unavailable": False,
                "notes": "",
            }
        )
    return out


def mapped_look_payload(row: dict, person: dict, settings: dict, mapping: dict) -> dict:
    event = build_event(row, mapping, settings)
    addresses = person.get("addresses") or []
    person_rows = [
        {"label": "firstName", "value": person.get("firstName") or ""},
        {"label": "lastName", "value": person.get("lastName") or ""},
        {"label": "assignedTo", "value": person.get("assignedTo") or ""},
        {"label": "stage", "value": person.get("stage") or ""},
        {
            "label": "Address 1",
            "value": _format_fub_address(addresses[0] if addresses else None),
        },
        {
            "label": "Address 2",
            "value": _format_fub_address(addresses[1] if len(addresses) > 1 else None),
        },
        {
            "label": "emails",
            "value": _fub_display_value(person.get("emails")),
        },
        {
            "label": "phones",
            "value": _fub_display_value(person.get("phones")),
        },
    ]
    skip = {"id", "firstName", "lastName", "assignedTo", "stage", "addresses", "background", "emails", "phones"}
    for key, value in person.items():
        if key in skip or value in (None, "", []):
            continue
        person_rows.append({"label": str(key), "value": str(value)})
    notes = person.get("background") or combined_notes(row, mapping)
    if notes:
        person_rows.append({"label": "notes", "value": notes})
    send = mapping.get("send") or {}
    pdf_path = _petition_pdf_path(row)
    if send.get("de111_file", True):
        person_rows.append(
            {
                "label": "Files",
                "value": (
                    f"{pdf_path.name} → FUB Files (DE-111)"
                    if pdf_path
                    else "No DE-111 PDF downloaded yet"
                ),
            }
        )
    return {
        "person": person_rows,
        "event_type": event.get("type") or settings.get("event_type") or "",
        "lead_source": event.get("source") or settings.get("source") or "",
        "system": event.get("system") or "",
        "message": event.get("message") or "",
        "description": event.get("description") or "",
    }


def probate_export_values(row: dict, mapping: dict) -> dict:
    petitioner = portal_petitioner(row)
    first, last = split_person_name(petitioner)
    decedent = (
        str(row.get("decedent") or "").strip()
        or portal_party_name(row, "decedent")
        or str(row.get("decedent_name") or "").strip()
    )
    dec_first, dec_last = split_person_name(decedent.split(",")[0] if decedent else "")
    case = case_key(row)
    court_note = _court_search_note(row, mapping)
    petition_name = (
        Path(str(row.get("petition_pdf") or "")).name if row.get("petition_pdf") else ""
    )
    contact = _row_contact(row)
    return {
        "petitioner": petitioner,
        "petitioner_first": first,
        "petitioner_last": last,
        "decedent": decedent,
        "decedent_first": dec_first,
        "decedent_last": dec_last,
        "case_number": case,
        "decedent_residence": _stringify_field(row.get("decedent_residence")),
        "decedent_city": _stringify_field(row.get("decedent_city")),
        "decedent_state": _stringify_field(row.get("decedent_state")),
        "decedent_zip": _stringify_field(row.get("decedent_zip")),
        "mailing_address": _stringify_field(contact.get("mailing_address") or row.get("mailing_address")),
        "mailing_city": _stringify_field(contact.get("mailing_city") or row.get("mailing_city")),
        "mailing_state": _stringify_field(contact.get("mailing_state") or row.get("mailing_state")),
        "mailing_zip": _stringify_field(contact.get("mailing_zip") or row.get("mailing_zip")),
        "petitioner_email": _stringify_field(contact.get("petitioner_email") or row.get("petitioner_email")),
        "petitioner_phone": _stringify_field(contact.get("petitioner_phone") or row.get("petitioner_phone")),
        "decedent_died": _stringify_field(row.get("decedent_died")),
        "death_place": _stringify_field(row.get("death_place")),
        "estate_real": _money_field(row.get("estate_real")),
        "estate_personal": _money_field(row.get("estate_personal")),
        "hearing": _stringify_field(row.get("next_event") or row.get("hearing")),
        "court_search": court_note,
        "court_url": case_portal_url(row) or court_note,
        "notice_url": _stringify_field(row.get("notice_url")),
        "petition_pdf": petition_name,
        "de111_url": petition_public_uri(case) if case and _petition_pdf_path(row) else "",
        "de147_url": duties_public_uri(case) if case and _duties_pdf_path(row) else "",
        "filed": _stringify_field(row.get("filed") or row.get("filed_from_docket")),
        "caption": _stringify_field(row.get("caption")),
        "attorney": _stringify_field(row.get("attorney")),
        "attorney_phone": _stringify_field(row.get("attorney_phone")),
        "newspaper": _stringify_field(row.get("newspaper")),
        "will_offered": _stringify_field(row.get("will_offered")),
        "iaea_requested": _stringify_field(row.get("iaea_requested")),
        "parties": _stringify_field(row.get("parties")),
        "county_resident": _stringify_field(row.get("county_resident")),
        "case_type": _stringify_field(row.get("case_type")),
        "court_status": _stringify_field(row.get("court_status")),
    }


def _fub_target_name(api_name: str) -> str:
    target = str(api_name or "").strip()
    if target.lower().startswith("person."):
        return target.split(".", 1)[1]
    return target


def _is_notes_target(api_name: str) -> bool:
    return _fub_target_name(api_name).lower() in NOTES_TARGETS


def _source_mapped_to_notes(mapping: dict, key: str) -> bool:
    fields = mapping.get("custom_fields") or {}
    return _is_notes_target(str(fields.get(key) or ""))


def _notes_field_label(key: str) -> str:
    special = {
        "case_number": "Casenumber",
        "decedent": "Decedent",
        "decedent_first": "Decedent",
        "decedent_last": "Decedent",
        "petitioner": "Petitioner",
        "petitioner_first": "Petitioner",
        "petitioner_last": "Petitioner",
    }
    if key in special:
        return special[key]
    for item in PROBATE_SOURCE_FIELDS:
        if item.get("key") == key:
            return str(item.get("notes_label") or item.get("label") or key)
    return key


def combined_notes(row: dict, mapping: dict) -> str:
    values = probate_export_values(row, mapping)
    fields = mapping.get("custom_fields") or {}
    note_keys = {
        str(key)
        for key, api in fields.items()
        if _is_notes_target(str(api))
    }
    parts: list[str] = []
    seen: set[str] = set()

    def mapped(*keys: str) -> bool:
        return any(key in note_keys for key in keys)

    def name_line(label: str, first: str, last: str, full: str) -> str:
        first = str(first or "").strip()
        last = str(last or "").strip()
        if not first and not last and full:
            first, last = split_person_name(str(full))
        if first and last:
            return f"{label}: {first}, {last}"
        if first or last:
            return f"{label}: {first or last}"
        return ""

    if mapped("decedent", "decedent_first", "decedent_last"):
        line = name_line(
            "Decedent",
            values.get("decedent_first") or "",
            values.get("decedent_last") or "",
            values.get("decedent") or "",
        )
        if line:
            parts.append(line)
        seen.update({"decedent", "decedent_first", "decedent_last"})
    if mapped("petitioner", "petitioner_first", "petitioner_last"):
        line = name_line(
            "Petitioner",
            values.get("petitioner_first") or "",
            values.get("petitioner_last") or "",
            values.get("petitioner") or "",
        )
        if line:
            parts.append(line)
        seen.update({"petitioner", "petitioner_first", "petitioner_last"})
    for item in PROBATE_SOURCE_FIELDS:
        key = str(item.get("key") or "")
        if not key or key in seen or key not in note_keys:
            continue
        value = values.get(key)
        if value in (None, ""):
            continue
        parts.append(f"{_notes_field_label(key)}: {value}")
        seen.add(key)
    for key in note_keys:
        if key in seen:
            continue
        value = values.get(key)
        if value in (None, ""):
            continue
        parts.append(f"{_notes_field_label(key)}: {value}")
    portal = case_portal_url(row)
    if portal and not any(portal in part for part in parts):
        parts.append(f"Court: {portal}")
    return "\n".join(parts)


def list_fub_custom_fields(
    api_url: str | None = None,
    api_key: str | None = None,
) -> dict:
    key = (api_key or os.environ.get("FUB_API_KEY") or "").strip()
    url = api_url or os.environ.get("FUB_API_URL") or "https://api.followupboss.com/v1"
    if not key:
        return {"fields": [], "error": "No Follow Up Boss API key configured."}
    try:
        response = requests.get(
            f"{_api_root(url)}/customFields",
            auth=(key, ""),
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if response.status_code >= 400:
            return {
                "fields": [],
                "error": f"FUB HTTP {response.status_code}: {response.text[:300]}",
            }
        payload = response.json()
    except Exception as exc:  # noqa: BLE001
        return {"fields": [], "error": str(exc)[:300]}
    rows = payload
    if isinstance(payload, dict):
        rows = (
            payload.get("customfields")
            or payload.get("customFields")
            or payload.get("fields")
            or []
        )
    fields = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        fields.append(
            {
                "name": name,
                "label": str(item.get("label") or name),
                "type": str(item.get("type") or "text"),
                "choices": item.get("choices") or [],
            }
        )
    return {"fields": fields, "error": None}


def fub_custom_field_names() -> set[str]:
    catalog = list_fub_custom_fields()
    return {
        str(item.get("name") or "").strip()
        for item in (catalog.get("fields") or [])
        if str(item.get("name") or "").strip()
    }


def _can_send_custom_field(api_name: str, allowed: set[str] | None) -> bool:
    name = str(api_name or "").strip()
    if name.lower().startswith("person."):
        name = name.split(".", 1)[1]
    if not name:
        return False
    if (
        name in PERSON_BUILTIN_TARGETS
        or name.lower() in ADDRESS_SLOT_TARGETS
        or _is_notes_target(name)
    ):
        return True
    if allowed is None:
        return True
    if name in allowed:
        return True
    print(
        f"FUB omit {name} (not a custom field on this Follow Up Boss account)",
        flush=True,
    )
    return False


PERSON_CORE_KEYS = {
    "id",
    "created",
    "updated",
    "createdById",
    "createdBy",
    "lastActivity",
    "name",
    "firstName",
    "lastName",
    "stage",
    "source",
    "sourceUrl",
    "assignedTo",
    "assignedUserId",
    "assignedToId",
    "emails",
    "phones",
    "addresses",
    "tags",
    "background",
    "pictureId",
    "collaborators",
    "contacted",
    "price",
    "timeframe",
    "website",
    "timeZone",
}


def _fub_display_value(value) -> str:
    if value in (None, "", [], {}):
        return ""
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                bits = [
                    str(item.get(key) or "")
                    for key in (
                        "value",
                        "email",
                        "number",
                        "phone",
                        "street",
                        "city",
                        "state",
                        "code",
                        "type",
                    )
                    if item.get(key)
                ]
                parts.append(" ".join(bits) if bits else json.dumps(item, default=str))
            else:
                parts.append(str(item))
        return "; ".join(part for part in parts if part)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return str(value)


def inspect_fub_person(query: str) -> dict:
    key = (os.environ.get("FUB_API_KEY") or "").strip()
    url = os.environ.get("FUB_API_URL") or "https://api.followupboss.com/v1"
    text = (query or "").strip()
    if not key:
        return {"error": "No Follow Up Boss API key configured.", "person": None}
    if not text:
        return {"error": "Enter a FUB person id or a name to search.", "person": None}
    try:
        if text.isdigit():
            response = requests.get(
                f"{_api_root(url)}/people/{text}",
                auth=(key, ""),
                headers={"Accept": "application/json"},
                timeout=20,
            )
            payload = response.json() if response.content else {}
            if response.status_code >= 400:
                return {
                    "error": f"FUB HTTP {response.status_code}: {str(payload)[:300]}",
                    "person": None,
                }
            person = payload.get("person") if isinstance(payload.get("person"), dict) else payload
        else:
            response = requests.get(
                f"{_api_root(url)}/people",
                params={"query": text, "limit": 5},
                auth=(key, ""),
                headers={"Accept": "application/json"},
                timeout=20,
            )
            payload = response.json() if response.content else {}
            if response.status_code >= 400:
                return {
                    "error": f"FUB HTTP {response.status_code}: {str(payload)[:300]}",
                    "person": None,
                }
            rows = payload.get("people") if isinstance(payload, dict) else payload
            if not isinstance(rows, list) or not rows:
                return {"error": f"No people matched “{text}”.", "person": None}
            person = rows[0] if isinstance(rows[0], dict) else None
        if not isinstance(person, dict):
            return {"error": "Follow Up Boss returned no person object.", "person": None}
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:300], "person": None}

    catalog = list_fub_custom_fields()
    custom_meta = {item["name"]: item for item in (catalog.get("fields") or [])}
    core = []
    for name in (
        "id",
        "firstName",
        "lastName",
        "name",
        "stage",
        "source",
        "assignedTo",
        "emails",
        "phones",
        "addresses",
        "tags",
        "created",
        "updated",
        "background",
    ):
        value = _fub_display_value(person.get(name))
        core.append({"name": name, "value": value, "populated": bool(value)})
    mailing_line = ""
    addresses = person.get("addresses") or []
    if isinstance(addresses, list) and len(addresses) > 1 and isinstance(addresses[1], dict):
        mailing_line = _fub_display_value(addresses[1])
    else:
        for item in addresses:
            if isinstance(item, dict) and str(item.get("type") or "").lower() in {
                "mailing",
                "investment",
                "decedent",
                "address 2",
                "address2",
            }:
                mailing_line = _fub_display_value(item)
                break
    core.append(
        {
            "name": "address2",
            "value": mailing_line,
            "populated": bool(mailing_line),
        }
    )
    notes_text = _fetch_person_notes(person.get("id")) or _fub_display_value(
        person.get("background")
    )
    core.append(
        {
            "name": "notes",
            "value": notes_text,
            "populated": bool(notes_text),
        }
    )
    custom = []
    for name, meta in custom_meta.items():
        value = _fub_display_value(person.get(name))
        custom.append(
            {
                "name": name,
                "label": meta.get("label") or name,
                "type": meta.get("type") or "",
                "value": value,
                "populated": bool(value),
            }
        )
    extras = []
    known = PERSON_CORE_KEYS | set(custom_meta)
    for name, raw in person.items():
        if name in known:
            continue
        value = _fub_display_value(raw)
        if not value:
            continue
        extras.append({"name": str(name), "value": value, "populated": True})
    populated_custom = sum(1 for item in custom if item["populated"])
    return {
        "error": None,
        "custom_error": catalog.get("error"),
        "person_id": person.get("id"),
        "query": text,
        "core": core,
        "custom_fields": custom,
        "extra_fields": extras,
        "custom_populated": populated_custom,
        "custom_total": len(custom),
    }


def _fetch_person_notes(person_id) -> str:
    key = (os.environ.get("FUB_API_KEY") or "").strip()
    url = os.environ.get("FUB_API_URL") or "https://api.followupboss.com/v1"
    if not key or person_id in (None, "", 0, "0"):
        return ""
    try:
        response = requests.get(
            f"{_api_root(url)}/notes",
            params={"personId": int(person_id), "limit": 10},
            auth=(key, ""),
            headers={"Accept": "application/json"},
            timeout=20,
        )
        payload = response.json() if response.content else {}
        if response.status_code >= 400 or not isinstance(payload, dict):
            return ""
        rows = payload.get("notes")
        if not isinstance(rows, list):
            return ""
        parts = []
        for item in rows:
            if not isinstance(item, dict):
                continue
            body = str(item.get("body") or "").strip()
            subject = str(item.get("subject") or "").strip()
            if subject and body:
                parts.append(f"{subject}: {body}")
            elif body:
                parts.append(body)
        return "\n---\n".join(parts)
    except Exception:
        return ""


def mapping_payload(path: Path | None = None, *, fetch_fub: bool = True, source_id: str = "placer") -> dict:
    mapping = load_mapping(path)
    live = list_fub_custom_fields() if fetch_fub else {"fields": [], "error": None}
    written = resolve_mapping_path(path)
    source_id = str(source_id or "placer")
    source_fields = {item["id"]: source_field_catalog(item["id"]) for item in DATA_SOURCES}
    return {
        "mapping": mapping,
        "path": str(written),
        "exists": written.exists(),
        "catalog": mapping_catalog(),
        "data_sources": DATA_SOURCES,
        "source_id": source_id,
        "source_fields": source_fields,
        "source_go_no_go": {
            item["id"]: go_no_go_for_source(item["id"]) for item in DATA_SOURCES
        },
        "source_custom_fields": custom_fields_for_source(mapping, source_id),
        "fub_custom_fields": live.get("fields") or [],
        "fub_builtin_fields": FUB_BUILTIN_FIELDS,
        "fub_custom_error": live.get("error"),
    }


def split_person_name(name: str) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", (name or "").strip())
    text = text.replace('"', "").replace("'", "")
    if not text:
        return "", ""
    if "," in text:
        last, _, rest = text.partition(",")
        first = rest.strip()
        if first and last.strip():
            return first.title(), last.strip().title()
    parts = [part for part in text.split(" ") if part]
    if not parts:
        return "", ""
    suffixes = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "esq", "esq."}
    if len(parts) == 1:
        return parts[0].title(), ""
    if len(parts) >= 3 and parts[-1].rstrip(".").lower() in suffixes:
        return " ".join(parts[:-2]).title(), " ".join(parts[-2:]).title()
    return " ".join(parts[:-1]).title(), parts[-1].title()


def portal_party_name(row: dict, role: str) -> str:
    want = (role or "").strip().lower()
    for party in row.get("parties") or []:
        text = str(party)
        if "—" in text:
            listed, _, name = text.partition("—")
        elif " - " in text:
            listed, _, name = text.partition(" - ")
        else:
            continue
        if listed.strip().lower() == want:
            return name.strip()
    return ""


def portal_petitioner(row: dict) -> str:
    for role in ("petitioner", "administrator", "personal representative"):
        name = portal_party_name(row, role)
        if name:
            return name
    return str(row.get("petitioner") or row.get("petitioner_name") or "").strip()


def _strip_county_noise(text: str) -> str:
    text = COUNTY_NOISE_RE.sub(",", text)
    text = re.sub(r"\s*,\s*,+", ",", text)
    return re.sub(r"\s+", " ", text).strip(" ,")


def _usable_city(city: str) -> str:
    low = re.sub(r"\s+", " ", (city or "").strip().lower())
    if not low or low in NOT_CITIES or low.endswith(" county"):
        return ""
    return (city or "").strip()


def split_address(line: str) -> dict | None:
    try:
        from .petition_parse import split_de111_address, _state_code
    except ImportError:
        from petition_parse import split_de111_address, _state_code

    parsed = split_de111_address(line)
    if parsed:
        return {
            "street": parsed["street"],
            "city": parsed["city"],
            "state": parsed["state"],
            "code": parsed.get("zip") or "",
        }
    text = _strip_county_noise(re.sub(r"\s+", " ", (line or "").strip()))
    if not text:
        return None
    match = ADDR_RE.match(text) or ADDR_FLEX_RE.match(text)
    if not match:
        return {"street": text}
    return {
        "street": match.group("street").strip(" ,"),
        "city": _usable_city(match.group("city")),
        "state": _state_code(match.group("state")),
        "code": (match.group("zip") or "").strip(),
    }


def _fub_address(
    line: str,
    addr_type: str,
    *,
    city: str = "",
    state: str = "",
    code: str = "",
) -> dict | None:
    parsed = split_address(line) or {}
    street = str(parsed.get("street") or line or "").strip(" ,")
    city = _usable_city(parsed.get("city") or "") or _usable_city(city)
    state = str(parsed.get("state") or state or "").strip().upper()
    zip_code = str(parsed.get("code") or code or "").strip()
    if city and street.lower().endswith(city.lower()):
        street = street[: -len(city)].strip(" ,")
    if not street:
        return None
    addr = {
        "street": street,
        "type": addr_type,
        "country": "United States",
    }
    if city:
        addr["city"] = city
    if state:
        addr["state"] = state
    if zip_code:
        addr["code"] = zip_code
    return addr


def _format_fub_address(addr) -> str:
    if not isinstance(addr, dict):
        return ""
    bits = [
        f"address={addr.get('street') or ''}",
        "line2=",
        f"city={addr.get('city') or ''}",
        f"state={addr.get('state') or ''}",
        f"zip={addr.get('code') or ''}",
        f"type={addr.get('type') or ''}",
    ]
    return "; ".join(bits)


def _address_parts_from_source(local_key: str, values: dict) -> tuple[str, str, str]:
    if local_key in {
        "mailing_address",
        "mailing_city",
        "mailing_state",
        "mailing_zip",
    }:
        return (
            _usable_city(str(values.get("mailing_city") or "")),
            str(values.get("mailing_state") or "").strip(),
            str(values.get("mailing_zip") or "").strip(),
        )
    if local_key in {
        "decedent_residence",
        "decedent_city",
        "decedent_zip",
        "decedent",
    }:
        return (
            _usable_city(str(values.get("decedent_city") or "")),
            str(values.get("decedent_state") or "").strip(),
            str(values.get("decedent_zip") or "").strip(),
        )
    return "", "", ""


def _set_address_slot(
    person: dict,
    line: str,
    index: int,
    addr_type: str,
    *,
    city: str = "",
    state: str = "",
    code: str = "",
) -> None:
    addr = _fub_address(line, addr_type, city=city, state=state, code=code)
    if not addr:
        return
    slots = person.setdefault("_addr_slots", {})
    slots[max(0, int(index))] = addr
    person["addresses"] = [slots[i] for i in sorted(slots)]


def _flush_address_slots(person: dict) -> None:
    slots = person.pop("_addr_slots", None)
    if slots:
        person["addresses"] = [slots[i] for i in sorted(slots)]


def case_key(row: dict) -> str:
    return str(row.get("case_number") or row.get("advert_id") or "").strip()


def petition_safe_case(case: str) -> str:
    return re.sub(r"[^\w\-]+", "_", str(case or "").strip()) or "case"


def petition_file_token(case: str, secret: str | None = None, *, kind: str = "de111") -> str:
    raw = (secret or os.environ.get("FUB_PETITION_TOKEN_SECRET") or "placer-probate")
    return hmac.new(
        str(raw).encode(),
        f"{kind}:{petition_safe_case(case)}".encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def petition_public_uri(case: str) -> str:
    return form_public_uri(case, "de111")


def duties_public_uri(case: str) -> str:
    return form_public_uri(case, "de147")


def form_public_uri(case: str, kind: str) -> str:
    if kind == "de147":
        base = str(os.environ.get("FUB_DUTIES_BASE_URL") or "").rstrip("/")
    else:
        base = str(os.environ.get("FUB_PETITION_BASE_URL") or "").rstrip("/")
    if not base:
        return ""
    safe = petition_safe_case(case)
    return f"{base}/{petition_file_token(case, kind=kind)}/{safe}.pdf"


def _petition_pdf_path(row: dict) -> Path | None:
    raw = str(row.get("petition_pdf") or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file() and path.stat().st_size > 4:
            return path
    case = petition_safe_case(case_key(row))
    docs = Path(os.environ.get("FUB_PETITION_DOCS_DIR") or "")
    if not docs.is_dir() or not case:
        return None
    folder = docs / case
    named = folder / f"{case}_DE-111.pdf"
    if named.is_file():
        return named
    if folder.is_dir():
        for path in sorted(folder.glob("*_petition.pdf")):
            if path.is_file():
                return path
        for path in sorted(folder.glob("*.pdf")):
            if path.is_file() and "_DE-147" not in path.name.upper():
                return path
    return None


def _duties_pdf_path(row: dict) -> Path | None:
    raw = str(row.get("duties_pdf") or "").strip()
    if raw:
        path = Path(raw)
        if path.is_file() and path.stat().st_size > 4:
            return path
    case = petition_safe_case(case_key(row))
    docs = Path(os.environ.get("FUB_PETITION_DOCS_DIR") or "")
    if not docs.is_dir() or not case:
        return None
    named = docs / case / f"{case}_DE-147.pdf"
    return named if named.is_file() else None


def stored_person_id(state: dict, key: str) -> int | None:
    record = (state.get("cases") or {}).get(key) or {}
    raw = record.get("fub_person_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _rows_for_export(rows: list[dict], state: dict, *, verify: bool) -> list[dict]:
    if not verify:
        return list(rows)
    last = str(state.get("last_fub_verify_case") or "").strip()
    preferred: list[dict] = []
    existing: list[dict] = []
    fresh: list[dict] = []
    for row in rows:
        key = case_key(row)
        pid = stored_person_id(state, key) if key else None
        if last and key == last and pid is not None:
            preferred.append(row)
        elif pid is not None:
            existing.append(row)
        else:
            fresh.append(row)
    return preferred + existing + fresh


def _forced_verify_person_id() -> int | None:
    if not _env_bool("FUB_VERIFY_EXISTING"):
        return None
    raw = str(os.environ.get("FUB_VERIFY_PERSON_ID") or "").strip()
    if not raw.isdigit():
        return None
    pid = int(raw)
    return pid if pid > 0 else None


def is_new_row(row: dict) -> bool:
    return bool(row.get("first_seen") or str(row.get("status") or "").lower() == "new")


def gate_reason(
    row: dict,
    state: dict,
    mapping: dict,
    *,
    strict_property: bool,
    existing_id: int | None,
    allow_seen_without_fub: bool = False,
) -> str | None:
    key = case_key(row)
    if not key:
        return "missing_case_number"
    petitioner = portal_petitioner(row)
    first, last = split_person_name(petitioner)
    if not first or not last:
        return "petitioner_name_incomplete"
    skip_bits = [str(x).lower() for x in mapping.get("skip_petitioner_contains") or []]
    low = petitioner.lower()
    if any(bit in low for bit in skip_bits if bit):
        return "petitioner_skipped"
    if not str(_row_contact(row).get("mailing_address") or row.get("mailing_address") or "").strip():
        return "missing_petitioner_address"
    if (
        existing_id is None
        and strict_property
        and not str(row.get("decedent_residence") or "").strip()
    ):
        return "missing_decedent_residence"
    return None


def preview_one_record(
    rows: list[dict],
    *,
    mapping_path: Path | None = None,
) -> dict:
    mapping = load_mapping(mapping_path)
    settings = {
        "source": os.environ.get("FUB_SOURCE", "probate"),
        "assigned_to": os.environ.get("FUB_ASSIGNED_TO", "Blake Hammond"),
        "stage": (os.environ.get("FUB_STAGE") or "").strip(),
        "event_type": os.environ.get("FUB_EVENT_TYPE", "Seller Inquiry"),
    }
    strict = _env_bool("FUB_STRICT_PROPERTY")
    skips: list[dict] = []
    blank_state: dict = {"cases": {}}
    first_skip_record = None
    for row in rows:
        key = case_key(row)
        reason = gate_reason(
            row,
            blank_state,
            mapping,
            strict_property=strict,
            existing_id=None,
            allow_seen_without_fub=True,
        )
        if reason:
            print(
                f"FUB skip {key}: {reason} "
                f"mailing={row.get('mailing_address') or '(empty)'} "
                f"residence={row.get('decedent_residence') or '(empty)'} "
                f"pdf={Path(str(row.get('petition_pdf') or '')).name or 'none'}",
                flush=True,
            )
            skips.append({"case": key, "reason": reason})
            if first_skip_record is None:
                person = build_person(
                    row,
                    mapping,
                    settings,
                    person_id=None,
                    allowed_custom=fub_custom_field_names(),
                )
                record = verify_record_payload(row, person, None, settings, mapping)
                record["view_only"] = True
                record["posted"] = False
                record["gate"] = "no-go"
                record["gate_reason"] = reason
                record["skips"] = skips
                first_skip_record = record
            continue
        person = build_person(
            row,
            mapping,
            settings,
            person_id=None,
            allowed_custom=fub_custom_field_names(),
        )
        record = verify_record_payload(row, person, None, settings, mapping)
        record["view_only"] = True
        record["posted"] = False
        record["gate"] = "go"
        record["skips"] = skips
        print(f"FUB preview: {key} (view only, not posted)", flush=True)
        return {
            "ok": True,
            "verify_record": record,
            "verify_note": None,
            "skips": skips,
        }
    note = "No go-case in this window"
    if skips:
        sample = ", ".join(
            f"{item.get('case') or '?'}={item.get('reason')}" for item in skips[:5]
        )
        note = f"{note}. Skips: {sample}"
    print(f"FUB preview: {note}", flush=True)
    return {
        "ok": False,
        "verify_record": first_skip_record,
        "verify_note": note,
        "skips": skips,
    }


def _court_search_note(row: dict, mapping: dict) -> str:
    portal = case_portal_url(row)
    if portal:
        return portal
    url = mapping.get("court_search_url") or COURT_SEARCH_DEFAULT
    case = case_key(row)
    return f"{url} (paste {case} if the case page is missing)"


def build_person(
    row: dict,
    mapping: dict,
    settings: dict,
    *,
    person_id: int | None = None,
    allowed_custom: set[str] | None = None,
) -> dict:
    send = mapping.get("send") or {}
    petitioner = portal_petitioner(row)
    first, last = split_person_name(petitioner)
    person: dict = {}
    if person_id is not None:
        person["id"] = int(person_id)
    if send.get("firstName", True):
        person["firstName"] = first
    if send.get("lastName", True):
        person["lastName"] = last
    if send.get("assignedTo", True) and settings.get("assigned_to"):
        person["assignedTo"] = settings["assigned_to"]
    if send.get("stage", True) and settings.get("stage"):
        person["stage"] = str(settings["stage"]).strip()
    values = probate_export_values(row, mapping)
    if send.get("emails", True):
        email = str(values.get("petitioner_email") or "").strip()
        if email:
            person["emails"] = [{"value": email, "type": "home"}]
    if send.get("phones", True):
        phone = str(values.get("petitioner_phone") or "").strip()
        if phone:
            person["phones"] = [{"value": phone, "type": "home"}]
    if send.get("custom_fields", True):
        fields = mapping.get("custom_fields") or {}
        for local_key, api_name in fields.items():
            value = values.get(local_key)
            if not api_name or value in (None, ""):
                continue
            target = str(api_name).strip()
            if target.startswith("person."):
                target = target.split(".", 1)[1]
            if target in {"emails", "person.emails"}:
                if local_key == "attorney_phone":
                    continue
                person["emails"] = [{"value": str(value), "type": "home"}]
                continue
            if target in {"phones", "person.phones"}:
                if local_key == "attorney_phone":
                    continue
                person["phones"] = [{"value": str(value), "type": "home"}]
                continue
            if _is_notes_target(target):
                continue
            if local_key in ADDRESS_COMPONENT_KEYS and (
                target.lower() in ADDRESS_SLOT_TARGETS
            ):
                continue
            city, state, code = _address_parts_from_source(local_key, values)
            if target.lower() in ADDRESS_SLOT_TARGETS:
                slot = ADDRESS_SLOT_TARGETS[target.lower()]
                _set_address_slot(
                    person,
                    str(value),
                    slot,
                    ADDRESS2_TYPE if slot >= 1 else ADDRESS1_TYPE,
                    city=city,
                    state=state,
                    code=code,
                )
                continue
            if target == "tags":
                person["tags"] = [str(value)]
                continue
            if target in PERSON_BUILTIN_TARGETS:
                person[target] = str(value)
                continue
            if not _can_send_custom_field(api_name, allowed_custom):
                continue
            person[str(api_name)] = str(value)
    notes = combined_notes(row, mapping)
    if notes:
        person["background"] = notes
    _flush_address_slots(person)
    return person


def person_fingerprint(person: dict) -> str:
    payload = {k: v for k, v in person.items() if k not in {"id", "_addr_slots"}}
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def verify_record_payload(
    row: dict,
    person: dict,
    pid: int | None,
    settings: dict,
    mapping: dict,
) -> dict:
    values = probate_export_values(row, mapping)
    custom = []
    for local_key, api_name in (mapping.get("custom_fields") or {}).items():
        value = values.get(local_key)
        if api_name and value not in (None, ""):
            custom.append(
                {
                    "probate_field": local_key,
                    "fub_field": str(api_name),
                    "value": str(value),
                }
            )
    addr = {}
    addr2 = {}
    if person.get("addresses"):
        addr = person["addresses"][0] if isinstance(person["addresses"][0], dict) else {}
        if len(person["addresses"]) > 1 and isinstance(person["addresses"][1], dict):
            addr2 = person["addresses"][1]
    return {
        "data_source": "placer",
        "data_source_name": "Placer County",
        "gate": "go",
        "case_number": case_key(row),
        "fub_person_id": int(pid) if pid else None,
        "petitioner": portal_petitioner(row),
        "firstName": person.get("firstName"),
        "lastName": person.get("lastName"),
        "assignedTo": person.get("assignedTo"),
        "stage": person.get("stage"),
        "lead_source": settings.get("source"),
        "event_type": settings.get("event_type"),
        "decedent": row.get("decedent"),
        "decedent_residence": row.get("decedent_residence"),
        "address": addr,
        "address2": addr2,
        "hearing": values.get("hearing"),
        "notice_url": values.get("notice_url"),
        "court_search": values.get("court_search"),
        "court_url": values.get("court_url") or values.get("court_search"),
        "de111_url": values.get("de111_url") or "",
        "de147_url": values.get("de147_url") or "",
        "de111_file": (
            str(_petition_pdf_path(row) or "")
            if (mapping.get("send") or {}).get("de111_file", True)
            else ""
        ),
        "custom_fields": custom,
        "source_extract": source_extract_rows(row, mapping),
        "mapped": mapped_look_payload(row, person, settings, mapping),
    }


def build_event(
    row: dict,
    mapping: dict,
    settings: dict,
    *,
    person_id: int | None = None,
    allowed_custom: set[str] | None = None,
) -> dict:
    send = mapping.get("send") or {}
    decedent = str(row.get("decedent") or "").strip()
    case = case_key(row)
    court_note = _court_search_note(row, mapping)
    message = (
        f"Estate of {decedent or '(unknown)'}. Case {case}. "
        f"Search eCourt first: {court_note}."
    )
    if row.get("notice_url"):
        message += f" Notice: {row['notice_url']}"
    event: dict = {
        "system": mapping.get("system") or "PlacerProbateMonitor",
        "type": settings.get("event_type") or "Seller Inquiry",
        "person": build_person(
            row,
            mapping,
            settings,
            person_id=person_id,
            allowed_custom=allowed_custom,
        ),
    }
    if person_id is None and send.get("source", True):
        event["source"] = settings.get("source") or "probate"
    if send.get("message", True):
        event["message"] = message
        event["description"] = (
            f"Estate location (DE-111 3.a.(2), not place of death): "
            f"{row.get('decedent_residence') or '—'}. "
            f"Hearing: {row.get('next_event') or row.get('hearing') or '—'}. "
            f"eCourt: {case_portal_url(row) or court_note}."
        )
    return event


def _api_root(api_url: str) -> str:
    base = api_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _fub_headers(system: str) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-System": system,
    }
    key = str(os.environ.get("FUB_SYSTEM_KEY") or "").strip()
    if key:
        headers["X-System-Key"] = key
    return headers


def post_event(api_url: str, api_key: str, payload: dict, system: str) -> dict:
    url = f"{_api_root(api_url)}/events"
    response = requests.post(
        url,
        json=payload,
        auth=(api_key, ""),
        headers=_fub_headers(system),
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(f"FUB HTTP {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except ValueError:
        return {}


def put_person(api_url: str, api_key: str, person_id: int, payload: dict, system: str) -> dict | None:
    body = {k: v for k, v in payload.items() if k not in {"id", "_addr_slots"}}
    url = f"{_api_root(api_url)}/people/{int(person_id)}"
    response = requests.put(
        url,
        json=body,
        auth=(api_key, ""),
        headers=_fub_headers(system),
        timeout=30,
    )
    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise RuntimeError(f"FUB HTTP {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except ValueError:
        return {}


def post_note(
    api_url: str,
    api_key: str,
    person_id: int,
    body: str,
    system: str,
    *,
    subject: str = "Placer probate",
    is_html: bool = False,
) -> dict:
    text = (body or "").strip()
    if not text:
        return {}
    response = requests.post(
        f"{_api_root(api_url)}/notes",
        json={
            "personId": int(person_id),
            "subject": subject or "Placer probate",
            "body": text,
            "isHtml": bool(is_html),
        },
        auth=(api_key, ""),
        headers=_fub_headers(system),
        timeout=30,
    )
    if response.status_code >= 400:
        raise RuntimeError(
            f"FUB notes HTTP {response.status_code}: {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError:
        return {}


def _attachment_headers(system: str) -> dict:
    headers = _fub_headers(system)
    key = str(os.environ.get("FUB_SYSTEM_KEY") or "").strip()
    if key:
        headers["X-System-Key"] = key
    return headers


def post_person_attachment(
    api_url: str,
    api_key: str,
    person_id: int,
    path: Path,
    *,
    uri: str,
    file_name: str,
    system: str,
) -> dict:
    url = f"{_api_root(api_url)}/personAttachments"
    headers = _attachment_headers(system)
    errors: list[str] = []
    if uri:
        response = requests.post(
            url,
            json={
                "personId": int(person_id),
                "uri": uri,
                "fileName": file_name,
                "fileSize": int(path.stat().st_size),
            },
            auth=(api_key, ""),
            headers=headers,
            timeout=30,
        )
        if response.status_code < 400:
            try:
                return response.json()
            except ValueError:
                return {}
        errors.append(f"uri {response.status_code}: {response.text[:300]}")
    mp_headers = {key: value for key, value in headers.items() if key.lower() != "content-type"}
    with path.open("rb") as handle:
        response = requests.post(
            url,
            data={"personId": str(int(person_id)), "fileName": file_name},
            files={"file": (file_name, handle, "application/pdf")},
            auth=(api_key, ""),
            headers=mp_headers,
            timeout=60,
        )
    if response.status_code < 400:
        try:
            return response.json()
        except ValueError:
            return {}
    errors.append(f"upload {response.status_code}: {response.text[:300]}")
    raise RuntimeError("FUB files " + " | ".join(errors))


def _de111_note_payload(case: str, file_name: str, uri: str, path: Path) -> tuple[str, bool]:
    safe_case = html.escape(case or "")
    safe_name = html.escape(file_name or "DE-111.pdf")
    if uri:
        safe_uri = html.escape(uri, quote=True)
        body = (
            f"<p>DE-111 petition for {safe_case}</p>"
            f'<p><a href="{safe_uri}">{safe_name}</a></p>'
            f"<p>{safe_uri}</p>"
        )
        return body, True
    return (
        f"DE-111 petition for {case}: {file_name}\n"
        f"Saved on Home Assistant: {path}",
        False,
    )


def attach_de111_file(
    row: dict,
    person_id: int,
    *,
    mapping: dict,
    api_url: str,
    api_key: str,
    system: str,
    cases: dict,
    key: str,
    force: bool = False,
) -> dict:
    send = mapping.get("send") or {}
    if not send.get("de111_file", True):
        print(f"FUB files skip {key}: de111_file toggle off", flush=True)
        return {"ok": False, "reason": "disabled"}
    record = cases.get(key) or {}
    path = _petition_pdf_path(row)
    if not path:
        print(f"FUB files skip {key}: no DE-111 PDF", flush=True)
        return {"ok": False, "reason": "no_pdf"}
    case = case_key(row)
    file_name = f"{petition_safe_case(case)}_DE-111.pdf"
    uri = petition_public_uri(case)
    if key not in cases:
        cases[key] = {}
    if uri:
        print(f"FUB DE-111 URL {key}: {uri}", flush=True)
    else:
        print(
            f"FUB DE-111 URL {key}: missing Home Assistant external URL; "
            f"PDF is at {path}",
            flush=True,
        )
    if _source_mapped_to_notes(mapping, "de111_url"):
        print(f"FUB DE-111 notes skip {key}: URL mapped into Notes", flush=True)
        note_result = {"ok": True, "reason": "mapped_notes", "file": file_name, "uri": uri}
    elif record.get("fub_de111_note_uri") == uri and uri and not force:
        note_result = {"ok": True, "reason": "notes_link", "file": file_name, "uri": uri}
    else:
        body, is_html = _de111_note_payload(case, file_name, uri, path)
        post_note(
            api_url,
            api_key,
            person_id,
            body,
            system,
            subject="DE-111 petition",
            is_html=is_html,
        )
        cases[key]["fub_de111_note"] = True
        cases[key]["fub_de111_note_uri"] = uri
        print(f"FUB notes posted DE-111 link {key} person_id={person_id}", flush=True)
        note_result = {"ok": True, "reason": "notes_link", "file": file_name, "uri": uri}
    if not str(os.environ.get("FUB_SYSTEM_KEY") or "").strip():
        return note_result
    if record.get("fub_attachment_id") and not force:
        note_result["id"] = record.get("fub_attachment_id")
        return note_result
    try:
        attached = post_person_attachment(
            api_url,
            api_key,
            person_id,
            path,
            uri=uri,
            file_name=file_name,
            system=system,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FUB Files API skipped for {key}: {exc}", flush=True)
        note_result["error"] = str(exc)[:200]
        return note_result
    attachment_id = attached.get("id")
    if attachment_id:
        cases[key]["fub_attachment_id"] = attachment_id
        note_result["id"] = attachment_id
        note_result["reason"] = "attached"
        print(
            f"FUB files attached DE-111 {key} person_id={person_id} "
            f"attachment_id={attachment_id}",
            flush=True,
        )
    return note_result


def _de147_note_payload(case: str, file_name: str, uri: str, court_url: str, phone: str) -> tuple[str, bool]:
    safe_case = html.escape(case or "")
    safe_name = html.escape(file_name or "DE-147.pdf")
    bits = [f"<p>DE-147 duties / acknowledgment for {safe_case}</p>"]
    if uri:
        safe_uri = html.escape(uri, quote=True)
        bits.append(f'<p><a href="{safe_uri}">{safe_name}</a></p>')
        bits.append(f"<p>{safe_uri}</p>")
    if court_url:
        safe_court = html.escape(court_url, quote=True)
        bits.append(
            f'<p>eCourt file: <a href="{safe_court}">{html.escape(court_url)}</a></p>'
        )
    if phone:
        bits.append(f"<p>Petitioner phone: {html.escape(phone)}</p>")
    if len(bits) == 1:
        return f"DE-147 duties for {case}: {file_name}", False
    return "".join(bits), True


def attach_de147_file(
    row: dict,
    person_id: int,
    *,
    mapping: dict,
    api_url: str,
    api_key: str,
    system: str,
    cases: dict,
    key: str,
    force: bool = False,
) -> dict:
    send = mapping.get("send") or {}
    if not send.get("de147_file", True):
        print(f"FUB DE-147 skip {key}: de147_file toggle off", flush=True)
        return {"ok": False, "reason": "disabled"}
    if _source_mapped_to_notes(mapping, "de147_url"):
        print(f"FUB DE-147 notes skip {key}: URL mapped into Notes", flush=True)
        return {
            "ok": True,
            "reason": "mapped_notes",
            "uri": duties_public_uri(case_key(row)),
            "file": f"{petition_safe_case(case_key(row))}_DE-147.pdf",
        }
    path = _duties_pdf_path(row)
    if not path:
        print(f"FUB DE-147 skip {key}: no DE-147 PDF", flush=True)
        return {"ok": False, "reason": "no_pdf"}
    case = case_key(row)
    file_name = f"{petition_safe_case(case)}_DE-147.pdf"
    uri = duties_public_uri(case)
    court_url = str(row.get("duties_url") or "").strip()
    phone = str(_row_contact(row).get("petitioner_phone") or row.get("petitioner_phone") or "").strip()
    record = cases.get(key) or {}
    if key not in cases:
        cases[key] = {}
    fingerprint = f"{uri}|{court_url}|{phone}"
    if record.get("fub_de147_note_fp") == fingerprint and not force:
        return {"ok": True, "reason": "already", "uri": uri or court_url, "file": file_name}
    body, is_html = _de147_note_payload(case, file_name, uri, court_url, phone)
    post_note(
        api_url,
        api_key,
        person_id,
        body,
        system,
        subject="DE-147 duties",
        is_html=is_html,
    )
    cases[key]["fub_de147_note_fp"] = fingerprint
    print(f"FUB notes posted DE-147 {key} person_id={person_id} {uri or court_url}", flush=True)
    return {"ok": True, "reason": "notes_link", "uri": uri or court_url, "file": file_name}


def _court_portal_note_payload(case: str, url: str) -> str:
    safe_case = html.escape(case or "")
    safe_url = html.escape(url, quote=True)
    return (
        f"<p>Placer eCourt Public case {safe_case}</p>"
        f'<p><a href="{safe_url}">Open case in eCourt Public</a></p>'
        f"<p>{html.escape(url)}</p>"
    )


def post_court_portal_note(
    row: dict,
    person_id: int,
    *,
    mapping: dict,
    api_url: str,
    api_key: str,
    system: str,
    cases: dict,
    key: str,
    force: bool = False,
) -> dict:
    send = mapping.get("send") or {}
    if not send.get("court_url_note", True):
        print(f"FUB court URL skip {key}: court_url_note toggle off", flush=True)
        return {"ok": False, "reason": "disabled"}
    url = case_portal_url(row)
    if not url:
        print(f"FUB court URL skip {key}: no eCourt case page", flush=True)
        return {"ok": False, "reason": "no_court_url"}
    record = cases.get(key) or {}
    if key not in cases:
        cases[key] = {}
    if record.get("fub_court_note_url") == url and not force:
        print(f"FUB court URL already noted {key}: {url}", flush=True)
        return {"ok": True, "reason": "already", "uri": url}
    post_note(
        api_url,
        api_key,
        person_id,
        _court_portal_note_payload(case_key(row), url),
        system,
        subject="eCourt Public case",
        is_html=True,
    )
    cases[key]["fub_court_note_url"] = url
    print(f"FUB notes posted court URL {key} person_id={person_id} {url}", flush=True)
    return {"ok": True, "reason": "notes_link", "uri": url}


def person_id_from_response(body: dict) -> int | None:
    if not isinstance(body, dict):
        return None
    for key in ("personId", "person_id"):
        if body.get(key):
            return int(body[key])
    person = body.get("person")
    if isinstance(person, dict) and person.get("id"):
        return int(person["id"])
    if body.get("id") and (body.get("firstName") or body.get("lastName")):
        return int(body["id"])
    return None


def _remember_person(cases: dict, key: str, person_id: int, fingerprint: str) -> None:
    if key not in cases:
        cases[key] = {}
    cases[key]["fub_person_id"] = int(person_id)
    cases[key]["fub_fingerprint"] = fingerprint
    cases[key]["fub_skip"] = None


def _clear_fub_person(cases: dict, key: str) -> None:
    if not key:
        return
    record = cases.setdefault(key, {})
    for field in (
        "fub_person_id",
        "fub_fingerprint",
        "fub_attachment_id",
        "fub_de111_note",
        "fub_de111_note_uri",
        "fub_de147_note_fp",
        "fub_court_note_url",
        "fub_skip",
    ):
        record.pop(field, None)


def export_new_leads(
    rows: list[dict],
    state: dict,
    *,
    mapping_path: Path | None = None,
) -> dict:
    summary = {
        "posted": 0,
        "updated": 0,
        "skipped": 0,
        "error": None,
        "skips": [],
        "verify_record": None,
        "verify_note": None,
    }
    if not _env_bool("FUB_ENABLED"):
        try:
            from .job_progress import report_progress
        except ImportError:
            from job_progress import report_progress

        report_progress(
            "fub",
            "Follow Up Boss import is off.",
            fub_posted=0,
            fub_updated=0,
            fub_skipped=0,
        )
        return summary
    api_key = os.environ.get("FUB_API_KEY", "").strip()
    if not api_key:
        summary["error"] = "FUB enabled but API key is empty"
        print(summary["error"], flush=True)
        print("FUB: posted=0 updated=0 skipped=0", flush=True)
        return summary
    mapping = load_mapping(mapping_path)
    settings = {
        "api_url": os.environ.get("FUB_API_URL", "https://api.followupboss.com/v1"),
        "source": os.environ.get("FUB_SOURCE", "probate"),
        "assigned_to": os.environ.get("FUB_ASSIGNED_TO", "Blake Hammond"),
        "stage": (os.environ.get("FUB_STAGE") or "").strip(),
        "event_type": os.environ.get("FUB_EVENT_TYPE", "Seller Inquiry"),
    }
    strict = _env_bool("FUB_STRICT_PROPERTY")
    verify = _env_bool("FUB_VERIFY_ONLY")
    update_existing = _env_bool("FUB_UPDATE_EXISTING")
    refresh = verify or update_existing
    forced_id = _forced_verify_person_id() if verify else None
    if verify and _env_bool("FUB_VERIFY_EXISTING") and forced_id is None:
        summary["error"] = "Use existing is on but Follow Up Boss person ID is empty"
        print(summary["error"], flush=True)
        print("FUB: posted=0 updated=0 skipped=0", flush=True)
        return summary
    system = str(mapping.get("system") or "PlacerProbateMonitor")
    allowed_custom = fub_custom_field_names()
    cases = state.setdefault("cases", {})
    posted_case = None
    posted_pid = None
    work_rows = list(rows) if forced_id else _rows_for_export(rows, state, verify=verify)
    if forced_id:
        print(f"FUB verify: updating existing person_id={forced_id}", flush=True)
    for row in work_rows:
        key = case_key(row)
        existing_id = stored_person_id(state, key) if key else None
        if forced_id is not None:
            existing_id = forced_id
        reason = gate_reason(
            row,
            state,
            mapping,
            strict_property=strict,
            existing_id=existing_id,
            allow_seen_without_fub=verify,
        )
        if reason:
            summary["skipped"] += 1
            summary["skips"].append({"case": key, "reason": reason})
            if key and key in cases:
                cases[key]["fub_skip"] = reason
            print(f"FUB skip {key or '(no case)'}: {reason}")
            _progress_fub(summary, "skipped", key)
            continue
        person = build_person(
            row,
            mapping,
            settings,
            person_id=existing_id,
            allowed_custom=allowed_custom,
        )
        fingerprint = person_fingerprint(person)
        record = cases.get(key) or {}
        try:
            if existing_id is not None:
                if verify and (summary["posted"] >= 1 or summary["updated"] >= 1):
                    summary["skipped"] += 1
                    summary["skips"].append({"case": key, "reason": "verify_only_limit"})
                    print(f"FUB skip {key}: verify_only_limit")
                    _progress_fub(summary, "verify-only skip", key)
                    continue
                if not verify and not update_existing and record.get("fub_fingerprint") == fingerprint:
                    summary["skipped"] += 1
                    summary["skips"].append({"case": key, "reason": "unchanged"})
                    print(f"FUB skip {key}: unchanged person_id={existing_id}")
                    _progress_fub(summary, "unchanged", key)
                    continue
                record_view = verify_record_payload(
                    row, person, existing_id, settings, mapping
                )
                record_view["view_only"] = False
                record_view["posted"] = False
                record_view["updated"] = False
                summary["verify_record"] = record_view
                print(
                    f"FUB petitioner address {key}: "
                    f"{row.get('mailing_address') or '(empty)'}",
                    flush=True,
                )
                print(
                    f"FUB last residence {key}: "
                    f"{row.get('decedent_residence') or '(empty)'}",
                    flush=True,
                )
                print(
                    f"FUB sending {len(person.get('addresses') or [])} "
                    f"address(es) {key}: {person.get('addresses')}",
                    flush=True,
                )
                body = put_person(
                    settings["api_url"], api_key, existing_id, person, system
                )
                if body is None:
                    print(
                        f"FUB person_id={existing_id} was deleted; "
                        f"creating a new person for {key}",
                        flush=True,
                    )
                    _clear_fub_person(cases, key)
                    existing_id = None
                    person = build_person(
                        row,
                        mapping,
                        settings,
                        person_id=None,
                        allowed_custom=allowed_custom,
                    )
                else:
                    pid = person_id_from_response(body) or existing_id
                    _remember_person(cases, key, pid, fingerprint)
                    summary["updated"] += 1
                    posted_case = key
                    posted_pid = pid
                    record_view["posted"] = True
                    record_view["updated"] = True
                    record_view["fub_person_id"] = int(pid)
                    record_view["fub_error"] = None
                    summary["verify_record"] = record_view
                    print(f"FUB updated {key} person_id={pid}")
                    _progress_fub(summary, "updated", key)
                    if refresh:
                        if verify:
                            state["last_fub_verify_case"] = key
                        try:
                            post_note(
                                settings["api_url"],
                                api_key,
                                pid,
                                combined_notes(row, mapping),
                                system,
                            )
                        except Exception as note_exc:  # noqa: BLE001
                            print(f"FUB notes error {key}: {note_exc}", flush=True)
                    try:
                        court_note = post_court_portal_note(
                            row,
                            pid,
                            mapping=mapping,
                            api_url=settings["api_url"],
                            api_key=api_key,
                            system=system,
                            cases=cases,
                            key=key,
                            force=refresh,
                        )
                        record_view["court_url_note"] = court_note
                    except Exception as court_exc:  # noqa: BLE001
                        record_view["court_url_note"] = {
                            "ok": False,
                            "reason": str(court_exc)[:300],
                        }
                        print(f"FUB court URL notes error {key}: {court_exc}", flush=True)
                    try:
                        attached = attach_de111_file(
                            row,
                            pid,
                            mapping=mapping,
                            api_url=settings["api_url"],
                            api_key=api_key,
                            system=system,
                            cases=cases,
                            key=key,
                            force=refresh,
                        )
                        record_view["de111_attach"] = attached
                        summary["verify_record"] = record_view
                    except Exception as file_exc:  # noqa: BLE001
                        record_view["de111_attach"] = {"ok": False, "reason": str(file_exc)[:300]}
                        summary["verify_record"] = record_view
                        print(f"FUB files error {key}: {file_exc}", flush=True)
                    try:
                        duties = attach_de147_file(
                            row,
                            pid,
                            mapping=mapping,
                            api_url=settings["api_url"],
                            api_key=api_key,
                            system=system,
                            cases=cases,
                            key=key,
                            force=refresh,
                        )
                        record_view["de147_attach"] = duties
                        summary["verify_record"] = record_view
                    except Exception as duties_exc:  # noqa: BLE001
                        record_view["de147_attach"] = {"ok": False, "reason": str(duties_exc)[:300]}
                        summary["verify_record"] = record_view
                        print(f"FUB DE-147 notes error {key}: {duties_exc}", flush=True)
                    if verify:
                        break
                    continue
            if verify and (summary["posted"] >= 1 or summary["updated"] >= 1):
                summary["skipped"] += 1
                summary["skips"].append({"case": key, "reason": "verify_only_limit"})
                print(f"FUB skip {key}: verify_only_limit")
                _progress_fub(summary, "verify-only skip", key)
                continue
            record_view = verify_record_payload(row, person, existing_id, settings, mapping)
            record_view["view_only"] = False
            record_view["posted"] = False
            summary["verify_record"] = record_view
            payload = build_event(
                row,
                mapping,
                settings,
                allowed_custom=allowed_custom,
            )
            body = post_event(settings["api_url"], api_key, payload, system)
            pid = person_id_from_response(body)
            if pid is None:
                raise RuntimeError(
                    "FUB create returned no person id; refusing to continue without a trackable ID"
                )
            _remember_person(cases, key, pid, fingerprint)
            try:
                post_note(
                    settings["api_url"],
                    api_key,
                    pid,
                    combined_notes(row, mapping),
                    system,
                )
            except Exception as note_exc:  # noqa: BLE001
                print(f"FUB notes error {key}: {note_exc}", flush=True)
            try:
                court_note = post_court_portal_note(
                    row,
                    pid,
                    mapping=mapping,
                    api_url=settings["api_url"],
                    api_key=api_key,
                    system=system,
                    cases=cases,
                    key=key,
                    force=refresh,
                )
                record_view["court_url_note"] = court_note
            except Exception as court_exc:  # noqa: BLE001
                record_view["court_url_note"] = {
                    "ok": False,
                    "reason": str(court_exc)[:300],
                }
                print(f"FUB court URL notes error {key}: {court_exc}", flush=True)
            try:
                attached = attach_de111_file(
                    row,
                    pid,
                    mapping=mapping,
                    api_url=settings["api_url"],
                    api_key=api_key,
                    system=system,
                    cases=cases,
                    key=key,
                    force=refresh,
                )
                record_view["de111_attach"] = attached
            except Exception as file_exc:  # noqa: BLE001
                record_view["de111_attach"] = {"ok": False, "reason": str(file_exc)[:300]}
                print(f"FUB files error {key}: {file_exc}", flush=True)
            try:
                duties = attach_de147_file(
                    row,
                    pid,
                    mapping=mapping,
                    api_url=settings["api_url"],
                    api_key=api_key,
                    system=system,
                    cases=cases,
                    key=key,
                    force=refresh,
                )
                record_view["de147_attach"] = duties
            except Exception as duties_exc:  # noqa: BLE001
                record_view["de147_attach"] = {"ok": False, "reason": str(duties_exc)[:300]}
                print(f"FUB DE-147 notes error {key}: {duties_exc}", flush=True)
            summary["posted"] += 1
            posted_case = key
            posted_pid = pid
            record_view["posted"] = True
            record_view["fub_person_id"] = int(pid)
            record_view["fub_error"] = None
            summary["verify_record"] = record_view
            print(f"FUB posted {key} person_id={pid}")
            _progress_fub(summary, "posted", key)
            if verify:
                state["last_fub_verify_case"] = key
                break
        except Exception as exc:  # noqa: BLE001
            summary["skipped"] += 1
            err = str(exc)
            summary["error"] = err[:500]
            summary["skips"].append({"case": key, "reason": "fub_http_error"})
            if key and key in cases:
                cases[key]["fub_skip"] = "post_failed"
            if summary.get("verify_record"):
                summary["verify_record"]["posted"] = False
                summary["verify_record"]["fub_error"] = err[:500]
            print(f"FUB error {key}: {err}", flush=True)
            break
    summary["verify_case"] = posted_case
    summary["verify_person_id"] = posted_pid
    if verify:
        if posted_case:
            action = "updated" if summary.get("updated") else "posted"
            print(
                f"FUB verify: {action} {posted_case} person_id={posted_pid}",
                flush=True,
            )
        else:
            rec = summary.get("verify_record") or {}
            err = summary.get("error")
            skips = summary.get("skips") or []
            if rec.get("case_number") and err:
                note = (
                    f"Mapped {rec.get('case_number')} but Follow Up Boss rejected it: {err}"
                )
            else:
                note = "No new go-case imported"
                if skips:
                    sample = ", ".join(
                        f"{item.get('case') or '?'}={item.get('reason')}"
                        for item in skips[:5]
                    )
                    note = f"{note}. Skips: {sample}"
            summary["verify_note"] = note
            print(f"FUB verify: {note}", flush=True)
    print(
        f"FUB: posted={summary['posted']} updated={summary['updated']} "
        f"skipped={summary['skipped']}",
        flush=True,
    )
    return summary
