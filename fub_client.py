"""Follow Up Boss Events API client for new probate petitioners."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

import requests

COURT_SEARCH_DEFAULT = "https://webportal.placerco.org/eCourtPublic/?q=node/48"
MAPPING_PATH = Path(__file__).resolve().parent / "fub_mapping.yaml"
ADDR_RE = re.compile(
    r"^(?P<street>.+?),\s*(?P<city>[^,]+),\s*(?P<state>[A-Z]{2})\s*(?P<zip>\d{5}(?:-\d{4})?)?$",
    re.I,
)


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
    return mapping


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
        "key": "petitioner",
        "label": "Petitioner name",
        "source": "eCourt parties, else CNPA notice",
        "notes": "This is the FUB Person. Split into firstName / lastName.",
        "person": "firstName+lastName",
        "custom": True,
    },
    {
        "key": "petitioner_first",
        "label": "Petitioner first name",
        "source": "Split from petitioner (all tokens except last)",
        "notes": "Maps to FUB firstName. Last token is last name.",
        "person": "firstName",
        "custom": True,
    },
    {
        "key": "petitioner_last",
        "label": "Petitioner last name",
        "source": "Split from petitioner (last token, plus Jr/Sr/II/III)",
        "notes": "Maps to FUB lastName.",
        "person": "lastName",
        "custom": True,
    },
    {
        "key": "decedent",
        "label": "Decedent name",
        "source": "CNPA notice / eCourt decedent party",
        "notes": "Never Person first/last name. Custom field only.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "decedent_first",
        "label": "Decedent first name",
        "source": "Split from decedent name",
        "notes": "Custom field only. Do not map onto Person firstName.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "decedent_last",
        "label": "Decedent last name",
        "source": "Split from decedent name",
        "notes": "Custom field only. Do not map onto Person lastName.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "case_number",
        "label": "Case number",
        "source": "CNPA notice / eCourt search",
        "notes": "S-PR number used as the lead key.",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_residence",
        "label": "Last residence (DE-111)",
        "source": "Petition PDF",
        "notes": "Sent as person.addresses type “subject property”. Not a verified APN.",
        "person": "addresses",
        "custom": True,
    },
    {
        "key": "decedent_city",
        "label": "Residence city",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_zip",
        "label": "Residence ZIP",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "decedent_died",
        "label": "Date of death",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "death_place",
        "label": "Place of death",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "estate_real",
        "label": "Real property GMV",
        "source": "Petition PDF",
        "notes": "Gross fair market value from DE-111. $0 is still a value.",
        "person": None,
        "custom": True,
    },
    {
        "key": "estate_personal",
        "label": "Personal property",
        "source": "Petition PDF",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "hearing",
        "label": "Hearing",
        "source": "eCourt next event, else notice text",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "court_search",
        "label": "Court search URL + paste hint",
        "source": "Derived",
        "notes": "Case Summary deep links 404 unless you search first.",
        "person": None,
        "custom": True,
    },
    {
        "key": "notice_url",
        "label": "Newspaper notice URL",
        "source": "CNPA",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "petition_pdf",
        "label": "Petition PDF filename",
        "source": "Downloaded DE-111",
        "notes": "Basename only; not uploaded to FUB.",
        "person": None,
        "custom": True,
    },
    {
        "key": "filed",
        "label": "Filed date",
        "source": "eCourt search / docket",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "caption",
        "label": "Case caption",
        "source": "eCourt",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "attorney",
        "label": "Attorney (notice)",
        "source": "CNPA notice",
        "notes": "Counsel is not the Person. Custom field only.",
        "person": None,
        "custom": True,
        "block": ["firstName", "lastName", "phones", "emails"],
    },
    {
        "key": "attorney_phone",
        "label": "Attorney phone",
        "source": "CNPA notice",
        "notes": "Never map onto person.phones.",
        "person": None,
        "custom": True,
        "block": ["phones"],
    },
    {
        "key": "newspaper",
        "label": "Newspaper",
        "source": "CNPA",
        "notes": "",
        "person": None,
        "custom": True,
    },
    {
        "key": "will_offered",
        "label": "Will offered",
        "source": "CNPA notice",
        "notes": "Yes/No.",
        "person": None,
        "custom": True,
    },
    {
        "key": "iaea_requested",
        "label": "IAEA requested",
        "source": "CNPA notice",
        "notes": "Yes/No.",
        "person": None,
        "custom": True,
    },
    {
        "key": "parties",
        "label": "Parties",
        "source": "eCourt summary",
        "notes": "Petitioner, decedent, objector, administrator.",
        "person": None,
        "custom": True,
    },
    {
        "key": "petitioner_email",
        "label": "Petitioner email",
        "source": "Not extracted",
        "notes": "No petitioner email yet. Do not enable person.emails.",
        "person": None,
        "custom": False,
        "unavailable": True,
    },
    {
        "key": "petitioner_phone",
        "label": "Petitioner phone",
        "source": "Not extracted",
        "notes": "No petitioner phone yet. Do not enable person.phones.",
        "person": None,
        "custom": False,
        "unavailable": True,
    },
    {
        "key": "mailing_address",
        "label": "Petitioner mailing address",
        "source": "Not extracted",
        "notes": "DE-111 mailing address is not parsed yet.",
        "person": None,
        "custom": False,
        "unavailable": True,
    },
]

FUB_DESTINATIONS = [
    {
        "id": "person.firstName",
        "label": "Person firstName",
        "group": "person",
        "locked_to": "petitioner",
    },
    {
        "id": "person.lastName",
        "label": "Person lastName",
        "group": "person",
        "locked_to": "petitioner",
    },
    {
        "id": "person.addresses",
        "label": "Person addresses (subject property)",
        "group": "person",
        "locked_to": "decedent_residence",
    },
    {
        "id": "person.emails",
        "label": "Person emails",
        "group": "person",
        "available": False,
        "reason": "No petitioner email is extracted yet.",
    },
    {
        "id": "person.phones",
        "label": "Person phones",
        "group": "person",
        "available": False,
        "reason": "No petitioner phone is extracted yet. Never use attorney_phone here.",
    },
    {
        "id": "person.assignedTo",
        "label": "Person assignedTo",
        "group": "person",
        "from_config": "fub_assigned_to",
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
    {"name": "addresses", "label": "Addresses", "group": "Person", "type": "person"},
    {"name": "stage", "label": "Stage", "group": "Person", "type": "person"},
    {"name": "source", "label": "Lead source", "group": "Person", "type": "person"},
    {"name": "tags", "label": "Tags", "group": "Person", "type": "person"},
    {"name": "background", "label": "Background", "group": "Person", "type": "person"},
    {
        "name": "emails",
        "label": "Emails (not extracted yet)",
        "group": "Person",
        "type": "person",
        "disabled": True,
    },
    {
        "name": "phones",
        "label": "Phones (not extracted yet)",
        "group": "Person",
        "type": "person",
        "disabled": True,
    },
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

SEND_TOGGLES = [
    {"key": "firstName", "label": "Send petitioner firstName", "editable": True},
    {"key": "lastName", "label": "Send petitioner lastName", "editable": True},
    {
        "key": "emails",
        "label": "Send person.emails",
        "editable": False,
        "forced": False,
        "reason": "No petitioner email yet.",
    },
    {
        "key": "phones",
        "label": "Send person.phones",
        "editable": False,
        "forced": False,
        "reason": "No petitioner phone yet.",
    },
    {
        "key": "subject_property_address",
        "label": "Send last residence as subject-property address",
        "editable": True,
    },
    {
        "key": "mailing_address",
        "label": "Send mailing address",
        "editable": False,
        "forced": False,
        "reason": "Mailing address is not parsed yet.",
    },
    {"key": "assignedTo", "label": "Send assignedTo from config", "editable": True},
    {"key": "source", "label": "Send event source from config", "editable": True},
    {"key": "message", "label": "Send event message/description", "editable": True},
    {"key": "custom_fields", "label": "Send custom fields below", "editable": True},
]

GO_NO_GO = [
    "Petitioner is the FUB Person. Decedent is never firstName/lastName.",
    "No petitioner phone or email is extracted yet — leave person.phones and person.emails off.",
    "Never map attorney_phone onto person.phones. Attorney stays a custom field at most.",
    "Last residence is DE-111 text, not a verified APN. Case Summary URLs 404 unless you search first.",
    "Only NEW cases are created on a full run. Verify one FUB import may use an already-seen case that has never been sent to Follow Up Boss.",
]


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
    }


def mapping_catalog() -> dict:
    return {
        "data_source": "placer",
        "data_source_name": "Placer County",
        "probate_fields": PROBATE_SOURCE_FIELDS,
        "fub_destinations": FUB_DESTINATIONS,
        "send_toggles": SEND_TOGGLES,
        "go_no_go": GO_NO_GO,
        "default_custom_fields": {
            "petitioner_first": "firstName",
            "petitioner_last": "lastName",
            "case_number": "customCaseNumber",
            "decedent": "customDecedent",
            "hearing": "customHearing",
            "court_search": "customCourtSearch",
            "notice_url": "customNoticeUrl",
            "estate_real": "customEstateReal",
            "petition_pdf": "customPetitionPdf",
        },
    }


def mapping_errors(mapping: dict, *, source_id: str = "placer") -> list[str]:
    errors: list[str] = []
    send = mapping.get("send") or {}
    if send.get("phones"):
        errors.append("Petitioner phone is not extracted; leave person.phones off.")
    if send.get("emails"):
        errors.append("Petitioner email is not extracted; leave person.emails off.")
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
            "petitioner",
            "petitioner_first",
            "petitioner_last",
        }:
            errors.append(f"{local_key} cannot map onto Person first/last name.")
        if live and meta.get("unavailable"):
            errors.append(f"{local_key} is not extracted yet.")
        if api in {"phones", "emails", "person.phones", "person.emails"}:
            errors.append(f"{local_key} cannot map onto person emails/phones yet.")
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
    send["phones"] = False
    send["emails"] = False
    send["mailing_address"] = False
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
    addr = {}
    if person.get("addresses"):
        first = person["addresses"][0]
        if isinstance(first, dict):
            addr = first
    person_rows = [
        {"label": "firstName", "value": person.get("firstName") or ""},
        {"label": "lastName", "value": person.get("lastName") or ""},
        {"label": "assignedTo", "value": person.get("assignedTo") or ""},
        {
            "label": "addresses",
            "value": ", ".join(
                str(addr.get(k) or "")
                for k in ("street", "city", "state", "code", "type")
                if addr.get(k)
            ),
        },
    ]
    skip = {"id", "firstName", "lastName", "assignedTo", "addresses"}
    for key, value in person.items():
        if key in skip or value in (None, "", []):
            continue
        person_rows.append({"label": str(key), "value": str(value)})
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
    decedent = str(row.get("decedent") or "").strip()
    dec_first, dec_last = split_person_name(decedent.split(",")[0] if decedent else "")
    case = case_key(row)
    court_note = _court_search_note(row, mapping)
    petition_name = (
        Path(str(row.get("petition_pdf") or "")).name if row.get("petition_pdf") else ""
    )
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
        "decedent_zip": _stringify_field(row.get("decedent_zip")),
        "decedent_died": _stringify_field(row.get("decedent_died")),
        "death_place": _stringify_field(row.get("death_place")),
        "estate_real": _stringify_field(row.get("estate_real")),
        "estate_personal": _stringify_field(row.get("estate_personal")),
        "hearing": _stringify_field(row.get("next_event") or row.get("hearing")),
        "court_search": court_note,
        "notice_url": _stringify_field(row.get("notice_url")),
        "petition_pdf": petition_name,
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
    ):
        value = _fub_display_value(person.get(name))
        core.append({"name": name, "value": value, "populated": bool(value)})
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


def portal_petitioner(row: dict) -> str:
    for party in row.get("parties") or []:
        text = str(party)
        if "—" in text:
            role, _, name = text.partition("—")
        elif " - " in text:
            role, _, name = text.partition(" - ")
        else:
            continue
        if role.strip().lower() == "petitioner":
            return name.strip()
    return str(row.get("petitioner") or "").strip()


def split_address(line: str) -> dict | None:
    text = re.sub(r"\s+", " ", (line or "").strip())
    if not text:
        return None
    match = ADDR_RE.match(text)
    if not match:
        return {"street": text}
    return {
        "street": match.group("street").strip(),
        "city": match.group("city").strip(),
        "state": match.group("state").upper(),
        "code": (match.group("zip") or "").strip(),
    }


def case_key(row: dict) -> str:
    return str(row.get("case_number") or row.get("advert_id") or "").strip()


def stored_person_id(state: dict, key: str) -> int | None:
    record = (state.get("cases") or {}).get(key) or {}
    raw = record.get("fub_person_id")
    if raw in (None, "", 0, "0"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


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
    if existing_id is None and not is_new_row(row) and not allow_seen_without_fub:
        return "not_new"
    petitioner = portal_petitioner(row)
    first, last = split_person_name(petitioner)
    if not first or not last:
        return "petitioner_name_incomplete"
    skip_bits = [str(x).lower() for x in mapping.get("skip_petitioner_contains") or []]
    low = petitioner.lower()
    if any(bit in low for bit in skip_bits if bit):
        return "petitioner_skipped"
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
        "event_type": os.environ.get("FUB_EVENT_TYPE", "Seller Inquiry"),
    }
    strict = _env_bool("FUB_STRICT_PROPERTY")
    skips: list[dict] = []
    blank_state: dict = {"cases": {}}
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
            skips.append({"case": key, "reason": reason})
            continue
        person = build_person(row, mapping, settings, person_id=None)
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
        "verify_record": None,
        "verify_note": note,
        "skips": skips,
    }


def _court_search_note(row: dict, mapping: dict) -> str:
    url = mapping.get("court_search_url") or COURT_SEARCH_DEFAULT
    case = case_key(row)
    return f"{url} (paste {case} — Case Summary URLs 404 unless you search first)"


def build_person(
    row: dict,
    mapping: dict,
    settings: dict,
    *,
    person_id: int | None = None,
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
    if send.get("subject_property_address", True):
        addr = split_address(str(row.get("decedent_residence") or ""))
        if addr:
            addr["type"] = mapping.get("subject_address_type") or "subject property"
            person["addresses"] = [addr]
    if send.get("custom_fields", True):
        fields = mapping.get("custom_fields") or {}
        values = probate_export_values(row, mapping)
        for local_key, api_name in fields.items():
            value = values.get(local_key)
            if not api_name or value in (None, ""):
                continue
            target = str(api_name).strip()
            if target.startswith("person."):
                target = target.split(".", 1)[1]
            if target in {"emails", "phones"}:
                continue
            if target == "addresses":
                addr = split_address(str(value))
                if addr:
                    addr["type"] = mapping.get("subject_address_type") or "subject property"
                    person["addresses"] = [addr]
                continue
            if target == "tags":
                person["tags"] = [str(value)]
                continue
            if target in PERSON_BUILTIN_TARGETS:
                person[target] = str(value)
                continue
            person[str(api_name)] = str(value)
    return person


def person_fingerprint(person: dict) -> str:
    payload = {k: v for k, v in person.items() if k != "id"}
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
    if person.get("addresses"):
        addr = person["addresses"][0] if isinstance(person["addresses"][0], dict) else {}
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
        "lead_source": settings.get("source"),
        "event_type": settings.get("event_type"),
        "decedent": row.get("decedent"),
        "decedent_residence": row.get("decedent_residence"),
        "address": addr,
        "hearing": values.get("hearing"),
        "notice_url": values.get("notice_url"),
        "court_search": values.get("court_search"),
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
        "person": build_person(row, mapping, settings, person_id=person_id),
    }
    if person_id is None and send.get("source", True):
        event["source"] = settings.get("source") or "probate"
    if send.get("message", True):
        event["message"] = message
        event["description"] = (
            f"Last residence (DE-111, not verified APN): "
            f"{row.get('decedent_residence') or '—'}. "
            f"Hearing: {row.get('next_event') or row.get('hearing') or '—'}. "
            f"Do not use Case Summary deep links without searching first."
        )
    return event


def _api_root(api_url: str) -> str:
    base = api_url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _fub_headers(system: str) -> dict:
    return {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-System": system,
    }


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


def put_person(api_url: str, api_key: str, person_id: int, payload: dict, system: str) -> dict:
    body = {k: v for k, v in payload.items() if k != "id"}
    url = f"{_api_root(api_url)}/people/{int(person_id)}"
    response = requests.put(
        url,
        json=body,
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
        "event_type": os.environ.get("FUB_EVENT_TYPE", "Seller Inquiry"),
    }
    strict = _env_bool("FUB_STRICT_PROPERTY")
    verify = _env_bool("FUB_VERIFY_ONLY")
    system = str(mapping.get("system") or "PlacerProbateMonitor")
    cases = state.setdefault("cases", {})
    posted_case = None
    posted_pid = None
    for row in rows:
        key = case_key(row)
        existing_id = stored_person_id(state, key) if key else None
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
            continue
        person = build_person(row, mapping, settings, person_id=existing_id)
        fingerprint = person_fingerprint(person)
        record = cases.get(key) or {}
        try:
            if existing_id is not None:
                if verify:
                    summary["skipped"] += 1
                    summary["skips"].append({"case": key, "reason": "verify_skip_update"})
                    print(f"FUB skip {key}: verify_skip_update person_id={existing_id}")
                    continue
                if record.get("fub_fingerprint") == fingerprint:
                    summary["skipped"] += 1
                    summary["skips"].append({"case": key, "reason": "unchanged"})
                    print(f"FUB skip {key}: unchanged person_id={existing_id}")
                    continue
                body = put_person(
                    settings["api_url"], api_key, existing_id, person, system
                )
                pid = person_id_from_response(body) or existing_id
                _remember_person(cases, key, pid, fingerprint)
                summary["updated"] += 1
                print(f"FUB updated {key} person_id={pid}")
                continue
            if verify and summary["posted"] >= 1:
                summary["skipped"] += 1
                summary["skips"].append({"case": key, "reason": "verify_only_limit"})
                print(f"FUB skip {key}: verify_only_limit")
                continue
            record_view = verify_record_payload(row, person, existing_id, settings, mapping)
            record_view["view_only"] = False
            record_view["posted"] = False
            summary["verify_record"] = record_view
            payload = build_event(row, mapping, settings)
            body = post_event(settings["api_url"], api_key, payload, system)
            pid = person_id_from_response(body)
            if pid is None:
                raise RuntimeError(
                    "FUB create returned no person id; refusing to continue without a trackable ID"
                )
            _remember_person(cases, key, pid, fingerprint)
            summary["posted"] += 1
            posted_case = key
            posted_pid = pid
            record_view["posted"] = True
            record_view["fub_person_id"] = int(pid)
            record_view["fub_error"] = None
            summary["verify_record"] = record_view
            print(f"FUB posted {key} person_id={pid}")
            if verify:
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
            print(
                f"FUB verify: posted {posted_case} person_id={posted_pid}",
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
