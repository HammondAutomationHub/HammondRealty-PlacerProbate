#!/usr/bin/env python3
"""Build the Hammond / Blake Hammond Realty daily probate PDF."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

NAVY = colors.HexColor("#1B2A4A")
STEEL = colors.HexColor("#2F4F6F")
GOLD = colors.HexColor("#C4A35A")
CREAM = colors.HexColor("#F6F1E6")
PALE = colors.HexColor("#EEF3F8")
GRAY = colors.HexColor("#5C6570")
LINE = colors.HexColor("#D5D0C6")
ALERT = colors.HexColor("#8B2E2E")
ECOURT_SEARCH = "https://webportal.placerco.org/eCourtPublic/?q=node/48"


def _esc(val) -> str:
    if val is None:
        return "—"
    if isinstance(val, list):
        return "<br/>".join(_esc(x) for x in val if x) or "—"
    text = str(val).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return text.replace("\n", "<br/>")


def _money(val) -> str:
    if val in (None, "", "—"):
        return "—"
    try:
        return f"${float(str(val).replace(',', '')):,.2f}"
    except ValueError:
        return str(val)


def _yes_no(val) -> str:
    if val is True:
        return "Yes"
    if val is False:
        return "No"
    return "—"


def _petition_fact_pairs(row: dict) -> list[tuple[str, object]]:
    return [
        ("Last residence", row.get("decedent_residence") or "—"),
        ("City", row.get("decedent_city") or "—"),
        ("ZIP", row.get("decedent_zip") or "—"),
        ("Date of death", row.get("decedent_died") or "—"),
        ("Place of death", row.get("death_place") or "—"),
        ("County resident", _yes_no(row.get("county_resident"))),
        ("Personal property", _money(row.get("estate_personal"))),
        ("Real property GMV", _money(row.get("estate_real"))),
    ]


def safe_href(url: object) -> str:
    """Allow only http(s) URLs in ReportLab link markup."""
    text = str(url or "").strip()
    if not re.match(r"^https?://", text, re.I):
        return ""
    return re.sub(r'[<>"\s]', "", text)


def _rl_link(url: object, label: object) -> str:
    href = safe_href(url)
    if not href:
        return _esc(label)
    return f'<link href="{href}" color="#1A4F8B"><u>{_esc(label)}</u></link>'


def _format_run_date(run_date: date) -> str:
    return f"{run_date.strftime('%A, %B')} {run_date.day}, {run_date.year}"


def _styles():
    base = getSampleStyleSheet()
    return {
        "kicker": ParagraphStyle("kicker", parent=base["Normal"], fontName="Times-Bold", fontSize=8, textColor=GOLD, spaceAfter=2),
        "title": ParagraphStyle("title", parent=base["Normal"], fontName="Times-Bold", fontSize=18, textColor=NAVY, leading=22, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=base["Normal"], fontName="Times-Italic", fontSize=9.5, textColor=STEEL, spaceAfter=8),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Times-Roman", fontSize=9, leading=12, textColor=NAVY),
        "small": ParagraphStyle("small", parent=base["Normal"], fontName="Times-Roman", fontSize=8, leading=10.5, textColor=GRAY),
        "h": ParagraphStyle("h", parent=base["Normal"], fontName="Times-Bold", fontSize=12, textColor=NAVY, spaceBefore=8, spaceAfter=4),
        "case": ParagraphStyle("case", parent=base["Normal"], fontName="Times-Bold", fontSize=11, textColor=NAVY, leading=14),
        "label": ParagraphStyle("label", parent=base["Normal"], fontName="Times-Bold", fontSize=8, textColor=STEEL, leading=10),
        "td": ParagraphStyle("td", parent=base["Normal"], fontName="Times-Roman", fontSize=8, leading=10.5, textColor=NAVY),
        "th": ParagraphStyle("th", parent=base["Normal"], fontName="Times-Bold", fontSize=7.5, leading=10, textColor=colors.white),
        "flag": ParagraphStyle("flag", parent=base["Normal"], fontName="Times-Italic", fontSize=8.5, leading=11, textColor=ALERT),
        "foot": ParagraphStyle("foot", parent=base["Normal"], fontName="Times-Italic", fontSize=8, textColor=GRAY, leading=11),
        "kpi_n": ParagraphStyle("kpi_n", parent=base["Normal"], alignment=1, fontName="Times-Bold", fontSize=14, textColor=NAVY),
        "kpi_l": ParagraphStyle("kpi_l", parent=base["Normal"], alignment=1, fontName="Times-Roman", fontSize=7, textColor=STEEL, leading=9),
    }


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, letter[1] - 16, letter[0], 16, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont("Times-Roman", 8)
    canvas.drawString(36, letter[1] - 11, "Hammond IT Consulting — Blake Hammond Realty  ·  Placer probate feed")
    canvas.drawRightString(letter[0] - 36, letter[1] - 11, "CONFIDENTIAL")
    canvas.setFillColor(GOLD)
    canvas.rect(0, 0, letter[0], 20, fill=1, stroke=0)
    canvas.setFillColor(NAVY)
    canvas.setFont("Times-Roman", 7.5)
    canvas.drawString(36, 7, "Public notices + eCourt public index. Documents are not downloadable. Not a title search.")
    canvas.drawRightString(letter[0] - 36, 7, f"Page {doc.page}")
    canvas.restoreState()


def _cap_word(word: str) -> str:
    if re.match(r"^[A-Za-z]\.$", word):
        return word.upper()
    if word.lower() in {"a.k.a.", "aka"}:
        return "a.k.a."
    if word.lower() in {"iaea", "sbn", "pa"}:
        return word.upper()
    if "-" in word:
        return "-".join(_cap_word(p) if p else p for p in word.split("-"))
    if "'" in word:
        return "'".join(_cap_word(p) if p else p for p in word.split("'"))
    if not word:
        return word
    return word[:1].upper() + word[1:].lower()


def _title_name(value: object) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,")
    text = re.sub(r"\s+AND\s+", ", ", text, flags=re.I)
    words = []
    for raw in text.replace(",", ", ").split():
        word = raw.strip()
        if not word:
            continue
        if word == ",":
            words.append(",")
            continue
        comma = word.endswith(",")
        core = word.strip(",")
        words.append(_cap_word(core) + ("," if comma else ""))
    return re.sub(r"\s+,", ",", " ".join(words))


def _aka_decedent(row: dict) -> str:
    notice = _title_name(row.get("decedent") or "")
    portal = ""
    for party in row.get("parties") or []:
        if party.lower().startswith("decedent"):
            portal = _title_name(party.split("—", 1)[-1])
            break
    if notice and portal and notice.lower() != portal.lower():
        if portal.lower() in notice.lower():
            return notice
        return f"{portal} / {notice}"
    return notice or portal


def _venue(row: dict) -> str:
    blob = " ".join(str(x) for x in (row.get("hearings") or []))
    if re.search(r"101\s+Maple|AUBURN", blob, re.I):
        return "Dept. 2, 101 Maple St, Auburn"
    return ""


def _fmt_hearing(line: str, row: dict) -> str:
    text = str(line or "")
    text = re.sub(r"\s+", " ", text)
    text = text.replace(" — - ", " — ")
    text = text.replace("Estate Hearing — - ", "Estate Hearing — ")
    text = re.sub(r"Department\s+2", "Dept. 2", text)
    text = re.sub(r"Department\s+40", "Dept. 40", text)
    text = re.sub(r"08:30 AM", "8:30 AM", text)
    text = re.sub(r"\s+—\s+101 Maple Street\s+—\s+AUBURN, CA \d+", "", text, flags=re.I)
    if "Glenn M. Holley" in text and "Hon." not in text:
        text = text.replace("Glenn M. Holley", "Hon. Glenn M. Holley")
    venue = _venue(row)
    if venue and "Dept. 2" in text and "Maple" not in text and "Auburn" not in text:
        text = re.sub(r"Dept\. 2\b", venue, text)
    return text.strip(" —")


def _notice_venue_note(row: dict) -> str:
    notice = str(row.get("hearing") or "")
    low = notice.lower()
    if "gibson" in low:
        return "Notice listed Gibson Courthouse, Roseville; portal lists Dept. 2 / Maple St, Auburn"
    if "justice center" in low or "10820" in notice:
        return "Published notice listed 10820 Justice Center Dr, Roseville"
    return ""


def _short_doc(item: str) -> str:
    text = str(item)
    text = text.replace(
        "with Authorization to Administer Under the Independent Administration of Estates Act",
        "+ IAEA",
    )
    text = text.replace(
        "with Authorization to Administer Under the Independent Administration Act",
        "+ IAEA",
    )
    text = text.replace("Letters of Testamentary", "Letters Testamentary")
    text = text.replace("Duties: Liabilites of Personal Representative", "Duties / Liabilities of Personal Representative")
    text = text.replace("Duties: Liabilities of Personal Representative", "Duties / Liabilities of Personal Representative")
    text = re.sub(r"Petition: Probate of Will and Letters of Administration with Will Annexed \+ IAEA", "Petition: Probate of Will / Letters w/ Will Annexed + IAEA", text)
    return text


def _documents_for_display(row: dict) -> list[str]:
    docs = [_short_doc(d) for d in (row.get("documents") or [])]
    return docs or ["None listed on the public register"]


def _caption_for_display(row: dict) -> str:
    cap = str(row.get("caption") or "")
    cap = re.sub(r"^In\s+[Rr]e\s+the\s+", "", cap).strip()
    return cap or f"Estate of {_aka_decedent(row)}"


def _blob(row: dict) -> str:
    parts = [
        " ".join(row.get("parties") or []),
        " ".join(row.get("documents") or []),
        " ".join(row.get("hearing_history") or []),
        " ".join(row.get("hearings") or []),
        row.get("caption") or "",
        row.get("case_type") or "",
    ]
    return " ".join(parts).lower()


def _parse_mdy(text: str) -> date | None:
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", text or "")
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2}),\s+(\d{4})", text or "")
    if not m:
        return None
    try:
        return datetime.strptime(m.group(0), "%B %d, %Y").date()
    except ValueError:
        try:
            return datetime.strptime(m.group(0), "%b %d, %Y").date()
        except ValueError:
            return None


def _hearing_dates(row: dict) -> list[date]:
    found = []
    for line in list(row.get("hearing_history") or []) + list(row.get("hearings") or []):
        d = _parse_mdy(str(line))
        if d:
            found.append(d)
    return found


def _next_hearing_line(row: dict) -> str:
    hist = row.get("hearing_history") or []
    if hist:
        return _fmt_hearing(str(hist[0]), row)
    hearings = row.get("hearings") or []
    if hearings:
        return _fmt_hearing(str(hearings[0]), row)
    return _fmt_hearing(str(row.get("next_event") or row.get("hearing") or "—"), row)


def _is_contested(row: dict) -> bool:
    blob = _blob(row)
    return "objector" in blob or "objection" in blob


def _has_public_admin(row: dict) -> bool:
    return "public administrator" in _blob(row)


def _is_continued(row: dict) -> bool:
    return "continued" in _blob(row)


def _parties_for_display(row: dict) -> list[str]:
    out = []
    notice_pet = _title_name(row.get("petitioner") or "")
    portal_pets = []
    decedent_portal = ""
    objectors = []
    admins = []
    for party in row.get("parties") or []:
        role, _, name = party.partition(" — ")
        name = _title_name(name)
        role_l = role.strip().lower()
        if role_l == "decedent":
            decedent_portal = name
        elif role_l == "petitioner":
            portal_pets.append(name)
        elif role_l == "objector":
            objectors.append(name)
        elif role_l == "administrator":
            admins.append(name)
        else:
            out.append(f"{role.strip()} — {name}")

    if admins:
        out.append(f"Administrator (portal) — {admins[0]}")
    if notice_pet and portal_pets:
        portal = portal_pets[0]
        if notice_pet.lower() == portal.lower():
            out.append(f"Petitioner — {notice_pet}")
        elif notice_pet.split()[-1].lower() == portal.split()[-1].lower():
            # same last name, spelling/middle differs
            if notice_pet.split()[0].lower() != portal.split()[0].lower():
                out.append(f"Petitioner — {notice_pet} (portal spelling: {portal})")
            else:
                out.append(f"Petitioner — {portal} / {notice_pet}")
        else:
            out.append(f"Petitioner (portal) — {portal}")
            out.append(f"Petitioner (published notice) — {notice_pet}")
            for extra in portal_pets[1:]:
                if extra.lower() != portal.lower():
                    out.append(f"Petitioner — {extra}")
    elif portal_pets:
        for i, pet in enumerate(portal_pets):
            label = "Petitioner"
            if _has_public_admin(row) and "public administrator" in pet.lower():
                label = "Petitioner"
            out.append(f"{label} — {pet}")
        if notice_pet and notice_pet.split()[-1].lower() not in " ".join(portal_pets).lower():
            out.append(f"Petitioner (published notice) — {notice_pet}")
    elif notice_pet:
        out.append(f"Petitioner (published notice) — {notice_pet}")

    notice_dec = _title_name(row.get("decedent") or "")
    if decedent_portal and notice_dec and decedent_portal.lower() != notice_dec.lower():
        if decedent_portal.lower() in notice_dec.lower():
            out.append(f"Decedent — {notice_dec}")
        else:
            out.append(f"Decedent — {decedent_portal} / {notice_dec}")
    elif decedent_portal:
        out.append(f"Decedent — {decedent_portal}")
    elif notice_dec:
        out.append(f"Decedent — {notice_dec}")

    for obj in dict.fromkeys(objectors):
        out.append(f"Objector — {obj}")

    support = []
    for doc in row.get("documents") or []:
        m = re.search(r"Declaration:\s*of\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)", str(doc))
        if m:
            support.append(m.group(1))
    support = [n for n in dict.fromkeys(support) if "tenzler" not in n.lower()]
    if support:
        out.append("Supporting declarations — " + ", ".join(support))
    return out or [f'Notice petitioner — {notice_pet or "—"}']


def _petition_line(row: dict) -> str:
    guess = str(row.get("petition_guess") or "")
    guess = re.sub(r"^\d{2}/\d{2}/\d{4}\s+", "", guess)
    guess = guess.replace("with Authorization to Administer Under the Independent Administration of Estates Act", "+ IAEA")
    guess = guess.replace("with Authorization to Administer Under the Independent Administration Act", "+ IAEA")
    if guess.lower().startswith("petition:"):
        guess = guess.split(":", 1)[1].strip()
    docs = " ".join(row.get("documents") or []).lower()
    if "amended" in docs and "petition" in docs and "amended" not in guess.lower():
        guess = f"{guess} — amended petitions on file".strip(" —")
    pa = _has_public_admin(row)
    petitions = [d for d in (row.get("documents") or []) if "petition: letters of administration" in d.lower()]
    if pa and len(petitions) >= 2:
        young = _title_name(row.get("petitioner") or "") or "competing petitioner"
        return f"Two Letters of Administration + IAEA petitions (Public Administrator and {young})"
    return guess or "Letters / administration (see notice)"


def _will_iaea(row: dict) -> str:
    docs = " ".join(row.get("documents") or []).lower()
    will = "Yes" if row.get("will_offered") else "No"
    if "will annexed" in docs or "letters of administration with will" in docs:
        will = "Yes (will annexed)"
    elif not row.get("will_offered") and "intestate" in _blob(row):
        will = "No (intestate administration)"
    elif "certified copy of will" in docs:
        will = "Yes — certified copy of will on file"
    iaea = "Yes" if row.get("iaea_requested") else "No"
    if row.get("iaea_requested") and not row.get("will_offered"):
        iaea = "Yes (notice)"
    return f"{will}  /  {iaea}"


def _hearings_for_display(row: dict) -> list[str]:
    hist = [str(x) for x in (row.get("hearing_history") or []) if x]
    source = hist or [str(x) for x in (row.get("hearings") or []) if x]
    if not source:
        source = [str(row.get("hearing") or row.get("next_event") or "—")]
    lines = []
    seen = set()
    for i, item in enumerate(source):
        formatted = _fmt_hearing(item, row)
        key = re.sub(r"\s+", " ", formatted.lower())
        if key in seen:
            continue
        seen.add(key)
        prefix = "Next: " if i == 0 or (not lines) else ""
        if i > 0 and "intestate (public admin)" in formatted.lower() and "11/09" in formatted:
            prefix = "Next: "
        lines.append(prefix + formatted)
    note = _notice_venue_note(row)
    if note:
        lines.append(note)
    return lines


def _counsel_for_display(row: dict) -> list[str]:
    lines = []
    for item in row.get("court_attorneys") or []:
        text = str(item)
        text = re.sub(r"^(\d{2}/\d{2}/\d{4})\s+", r"assigned \1 — ", text)
        text = text.replace("(Current)", "(Current)")
        if _has_public_admin(row) and "mcclelland" in text.lower():
            lines.append(f"PA counsel: {text}")
        elif _has_public_admin(row) and "duggan" in text.lower():
            lines.append(f"Young counsel: {text}")
        else:
            lines.append(f"Court: {text}")
    notice = str(row.get("attorney") or "").strip()
    if notice:
        notice = re.sub(r"\s+", " ", notice)
        notice = re.sub(r"Phone No\.:\s*", "", notice, flags=re.I)
        notice = _title_name(notice)
        notice = re.sub(r"\bSbn\b", "SBN", notice)
        notice = re.sub(r"\bCa\b", "CA", notice)
        notice = re.sub(r"\bLlp\b", "LLP", notice)
        notice = re.sub(r"\bP\.C\.\b", "P.C.", notice)
        lines.append(f"Notice: {notice}")
    return lines or ["—"]


def _publication_line(row: dict) -> str:
    paper = str(row.get("newspaper") or "").strip() or "—"
    pub = str(row.get("publication_line") or "").strip()
    pub = re.sub(r"^" + re.escape(paper) + r"\s+ON\s+", "", pub, flags=re.I)
    pub = re.sub(r"^AUBURN JOURNAL ON\s+", "", pub, flags=re.I)
    months = {
        "JANUARY": "Jan", "FEBRUARY": "Feb", "MARCH": "Mar", "APRIL": "Apr",
        "MAY": "May", "JUNE": "Jun", "JULY": "Jul", "AUGUST": "Aug",
        "SEPTEMBER": "Sep", "OCTOBER": "Oct", "NOVEMBER": "Nov", "DECEMBER": "Dec",
    }
    for full, abbr in months.items():
        pub = re.sub(full, abbr, pub, flags=re.I)
    pub = re.sub(r"\s+", " ", pub).strip(" .")
    post = str(row.get("post_date") or "").strip()
    if post and re.match(r"^\d{4}-\d{2}-\d{2}$", post):
        y, m, d = post.split("-")
        post_fmt = f"{m}/{d}/{y}"
    else:
        post_fmt = post
    docs = " ".join(row.get("documents") or []).lower()
    extra = " Proof of publication already on file." if "proof: publication" in docs else ""
    snippet = str(row.get("snippet") or "")
    amended = "Amended notice, " if "AMENDED" in snippet.upper()[:120] else ""
    if pub and post_fmt:
        return f"{amended}{paper} — {pub} (post date {post_fmt}).{extra}".strip()
    return f"{paper} — {pub or post_fmt or '—'}{extra}"


def _status_line(row: dict) -> str:
    bits = [str(row.get("court_status") or "Open").strip() or "Open"]
    case_type = str(row.get("case_type") or "").strip()
    if case_type:
        bits.append(case_type)
    blob = _blob(row)
    if "intestate" in blob and "will" not in blob:
        bits.append("intestate")
    elif row.get("will_offered"):
        bits.append("probate of will")
    if _has_public_admin(row) and any("petition: letters" in str(d).lower() for d in (row.get("documents") or [])):
        if sum(1 for d in (row.get("documents") or []) if "petition: letters of administration" in d.lower()) >= 2:
            bits.append("competing intestate petitions")
    return " — ".join(bits)


def _mark_companions(rows: list[dict]) -> None:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        pet = _title_name(row.get("petitioner") or "").split()
        last = pet[-1].lower() if pet else ""
        hearing = _next_hearing_line(row)
        day = _parse_mdy(hearing)
        key = (last, day.isoformat() if day else hearing[:16])
        if last and day:
            groups[key].append(row)
    for mates in groups.values():
        if len(mates) < 2:
            continue
        numbers = [str(m.get("case_number") or "") for m in mates]
        for mate in mates:
            others = [n for n in numbers if n != mate.get("case_number")]
            mate["companion_cases"] = others
            surnames = sorted(
                {
                    _aka_decedent(m).split(",")[0].split()[-1]
                    for m in mates
                    if _aka_decedent(m)
                }
            )
            mate["companion_surnames"] = surnames


def _badge(row: dict, run_date: date) -> str:
    if _is_contested(row) and _has_public_admin(row):
        return "CONTESTED / PA"
    if _is_contested(row):
        return "CONTESTED"
    nxt = None
    dates = _hearing_dates(row)
    future = [d for d in dates if d >= run_date]
    if future:
        nxt = min(future)
    if nxt and 0 <= (nxt - run_date).days <= 14:
        return f"HEARING {nxt.month}/{nxt.day}"
    if _is_continued(row):
        return "CONTINUED"
    if row.get("companion_cases"):
        return "COMPANION"
    if row.get("first_seen"):
        return "NEW PUB"
    return "OPEN"


def _flags(row: dict, run_date: date) -> str:
    bits = []
    blob = _blob(row)
    notice_pet = _title_name(row.get("petitioner") or "")
    portal_pets = [
        _title_name(p.split("—", 1)[-1])
        for p in (row.get("parties") or [])
        if p.lower().startswith("petitioner")
    ]
    if _is_contested(row) and _has_public_admin(row):
        bits.append("Two petitioners fighting over appointment. Public Administrator vs family/nominee.")
    elif _is_contested(row):
        bits.append("CONTESTED.")
        if notice_pet and portal_pets and notice_pet.split()[-1].lower() not in " ".join(portal_pets).lower():
            bits.append(
                f"Notice petitioner ({notice_pet}) does not match portal petitioner ({portal_pets[0]})."
            )
    elif row.get("will_offered"):
        bits.append("Will offered.")
    if any(p.lower().startswith("administrator") for p in (row.get("parties") or [])):
        admin = _title_name(
            next(p.split("—", 1)[-1] for p in row.get("parties") or [] if p.lower().startswith("administrator"))
        )
        bits.append(f"Portal already labels {admin} as Administrator.")
    if row.get("first_seen") and not _is_contested(row):
        bits.append("First publication in the current CNPA window.")
    if "certified copy of will" in blob:
        bits.append("Certified will already in the file.")
    if "remote appearance" in " ".join(row.get("fees") or []).lower():
        bits.append("Remote appearance fee posted.")
    if "waiver: bond" in blob:
        bits.append("Bond waivers filed.")
    if row.get("decedent_residence"):
        bits.append(f"Last residence (DE-111 §3c): {row['decedent_residence']}.")
    real = row.get("estate_real")
    try:
        real_n = float(str(real).replace(",", "")) if real not in (None, "") else None
    except ValueError:
        real_n = None
    if row.get("decedent_residence") and real_n == 0:
        bits.append("Petition lists $0 real property; last residence is still on the DE-111.")
    dates = [d for d in _hearing_dates(row) if d >= run_date]
    if dates:
        nxt = min(dates)
        if 0 <= (nxt - run_date).days <= 7:
            bits.append(f"Hearing is {nxt.strftime('%m/%d/%Y')} (this week).")
        elif 0 <= (nxt - run_date).days <= 14:
            bits.append(f"Hearing {nxt.strftime('%m/%d/%Y')}.")
    if _is_continued(row):
        notice_h = _parse_mdy(str(row.get("hearing") or ""))
        portal_h = _parse_mdy(_next_hearing_line(row))
        past = [d for d in _hearing_dates(row) if d < run_date]
        if notice_h and portal_h and notice_h != portal_h:
            bits.append(
                f"Hearing continued; notice said {notice_h.strftime('%b %d')}, portal now {portal_h.strftime('%b %d')}."
            )
        elif past and portal_h:
            bits.append(
                f"{past[-1].strftime('%b %d')} hearing continued by the parties to {portal_h.strftime('%b %d, %Y')}. Newspaper notice is stale on the hearing date."
            )
    companions = row.get("companion_cases") or []
    if companions:
        other = companions[0]
        bits.append(f"Companion to {other}. Same petitioner, counsel, filing date, and hearing.")
        surnames = row.get("companion_surnames") or []
        if len(surnames) >= 2:
            bits.append("Search assessor under both " + " and ".join(surnames) + ".")
    if not row.get("found"):
        bits.append("No eCourt hit for this case number in the filing-year window.")
    if not bits:
        bits.append("Uncontested on the public register so far. Confirm property separately.")
    return " ".join(bits)


def _priority_line(rows: list[dict], run_date: date) -> str:
    soon = []
    contested = []
    continued = []
    companions = []
    for row in rows:
        name = _title_name(row.get("decedent") or "").split(",")[0]
        last = name.split()[-1] if name else str(row.get("case_number") or "")
        future = [d for d in _hearing_dates(row) if d >= run_date]
        if future and (min(future) - run_date).days <= 14:
            d = min(future)
            soon.append(f"{last} hearing {d.month}/{d.day}")
        if _is_contested(row):
            contested.append(last)
        if _is_continued(row) and not _is_contested(row):
            continued.append(last)
        if row.get("companion_cases"):
            companions.append(last)
    bits = []
    if soon:
        bits.append("Priority this week: " + " · ".join(soon))
    if contested:
        bits.append(" and ".join(contested) + " are contested")
    if continued:
        bits.append(f"{' and '.join(continued)} continued")
    if companions:
        bits.append(" / ".join(dict.fromkeys(companions)) + " are companion matters")
    if not bits:
        return ""
    text = bits[0]
    if len(bits) > 1:
        text = text.rstrip(".") + ". " + "; ".join(bits[1:])
    if not text.endswith("."):
        text += "."
    return text


def _display_decedent(row: dict) -> str:
    name = _aka_decedent(row)
    name = re.sub(r",\s+", " a.k.a. ", name, count=1) if name.count(",") >= 2 else name
    return name


def _filed_display(row: dict) -> str:
    filed = str(row.get("filed") or row.get("filed_from_docket") or "").strip()
    if " · " in filed and _has_public_admin(row):
        parts = [p.strip() for p in filed.split("·")]
        young = _title_name(row.get("petitioner") or "").split()[-1] if row.get("petitioner") else "Young"
        if len(parts) >= 2:
            return f"{parts[0]} (PA) · {parts[1]} ({young})"
    return filed or "—"


def _kpi_counts(rows: list[dict], run_date: date) -> tuple[int, int, int, int]:
    contested = sum(1 for r in rows if _is_contested(r))
    this_month = 0
    seen_cases = set()
    for r in rows:
        for d in _hearing_dates(r):
            if d.year == run_date.year and d.month == run_date.month and d >= run_date:
                this_month += 1
                break
        if r.get("companion_cases"):
            seen_cases.add(r.get("case_number"))
    companions = len(seen_cases)
    return len(rows), contested, this_month, companions


def build_pdf(rows: list[dict], out_path: Path, run_date: date, start: date, end: date) -> Path:
    from ecourt_client import parse_summary

    s = _styles()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prepared = []
    for raw in rows:
        row = dict(raw)
        portal_text = row.get("raw_text") or ""
        if portal_text.startswith("Case Summary"):
            parsed = parse_summary(portal_text)
            for key in (
                "parties",
                "hearings",
                "hearing_history",
                "filed_from_docket",
                "documents",
                "court_attorneys",
                "fees",
                "caption",
            ):
                if parsed.get(key):
                    row[key] = parsed[key]
        if " · " in str(row.get("filed_from_docket") or ""):
            row["filed"] = row["filed_from_docket"]
        prepared.append(row)
    rows = prepared
    _mark_companions(rows)

    unique_n, contested_n, month_n, companion_n = _kpi_counts(rows, run_date)
    kpis = Table([[
        [Paragraph(str(unique_n), s["kpi_n"]), Paragraph("UNIQUE ESTATES", s["kpi_l"])],
        [Paragraph(str(contested_n), s["kpi_n"]), Paragraph("CONTESTED", s["kpi_l"])],
        [Paragraph(str(month_n), s["kpi_n"]), Paragraph("HEARINGS THIS MONTH", s["kpi_l"])],
        [Paragraph(str(companion_n), s["kpi_n"]), Paragraph("COMPANION CASES", s["kpi_l"])],
    ]], colWidths=[1.8 * inch] * 4)
    kpis.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM),
        ("BOX", (0, 0), (-1, -1), 0.4, GOLD),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    header = [Paragraph(h, s["th"]) for h in ["Case", "Decedent", "Last residence", "Filed", "Next hearing"]]
    table_rows = [header]
    for r in rows:
        url = safe_href(r.get("notice_url") or "") or ECOURT_SEARCH
        case = r.get("case_number") or "—"
        case_cell = _rl_link(url, case) if url else _esc(case)
        table_rows.append([
            Paragraph(case_cell, s["td"]),
            Paragraph(_esc(_display_decedent(r)), s["td"]),
            Paragraph(_esc(r.get("decedent_residence") or "—"), s["td"]),
            Paragraph(_esc(_filed_display(r)), s["td"]),
            Paragraph(_esc(_next_hearing_line(r)), s["td"]),
        ])
    roster = Table(table_rows, colWidths=[1.1*inch, 1.35*inch, 1.85*inch, 1.15*inch, 1.95*inch])
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, r in enumerate(rows, 1):
        badge = _badge(r, run_date)
        hot = "CONTESTED" in badge
        bg = colors.HexColor("#F8E8E8") if hot else (PALE if i % 2 else colors.white)
        cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    roster.setStyle(TableStyle(cmds))

    priority = _priority_line(rows, run_date)
    story = [
        Paragraph("HAMMOND IT CONSULTING  ·  BLAKE HAMMOND REALTY", s["kicker"]),
        Paragraph("Daily Probate Petition Feed — Case Dossiers", s["title"]),
        Paragraph(
            f"{_format_run_date(run_date)}  ·  Placer County  ·  "
            f"CNPA notices + eCourt Public summaries + DE-111 last residence",
            s["sub"],
        ),
        Paragraph(
            "Each estate below merges the published Notice of Petition to Administer Estate with the "
            "public Case Summary (parties, filing date, hearings, document titles, counsel). "
            "Public register PDFs are downloaded when the portal exposes a Download link; "
            "Unavailable filings need court e-access.",
            s["body"],
        ),
        Spacer(1, 8),
        kpis,
        Paragraph("Roster — case numbers open the published notice (not the court portal)", s["h"]),
        roster,
        Spacer(1, 8),
    ]
    if priority:
        story.append(Paragraph(_esc(priority), s["body"]))
    story.extend([
        PageBreak(),
        Paragraph("Case dossiers", s["h"]),
    ])

    for r in rows:
        notice = safe_href(r.get("notice_url") or "")
        badge = _badge(r, run_date)
        caption = _caption_for_display(r)
        head = Paragraph(
            f'{_esc(r.get("case_number"))}  ·  {_esc(caption)}<br/>'
            f'<font size="8" color="#2F4F6F">{_esc(badge)}  ·  {_esc(_status_line(r))}</font>',
            s["case"],
        )
        links = []
        case_no = r.get("case_number") or "this case"
        links.append(
            f"Court search: {_rl_link(ECOURT_SEARCH, ECOURT_SEARCH)} "
            f"(paste {_esc(case_no)} — Case Summary URLs 404 unless you search first)"
        )
        if notice:
            links.append(f"Published notice: {_rl_link(notice, notice)}")
        pairs = [
            ("Filed", _filed_display(r)),
            *_petition_fact_pairs(r),
            ("Petition", _petition_line(r)),
            ("Will / IAEA", _will_iaea(r)),
            ("Parties", _parties_for_display(r)),
            ("Hearings", _hearings_for_display(r)),
            ("Documents", _documents_for_display(r)),
            ("Counsel", _counsel_for_display(r)),
            ("Publication", _publication_line(r)),
            ("Fees paid", r.get("fees") or ["—"]),
        ]
        data = [
            [Paragraph(k, s["label"]), Paragraph(_esc(v), s["td"])]
            for k, v in pairs
        ]
        body = Table(data, colWidths=[1.45 * inch, 5.95 * inch])
        body.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("BACKGROUND", (0, 0), (0, -1), CREAM),
        ]))
        bar = Table([[""]], colWidths=[7.4 * inch], rowHeights=[4])
        bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]))
        story.append(KeepTogether([
            bar,
            Spacer(1, 6),
            head,
            Spacer(1, 3),
            Paragraph("<br/>".join(links), s["small"]),
            Spacer(1, 6),
            body,
            Spacer(1, 4),
            Paragraph(_flags(r, run_date), s["flag"]),
            Spacer(1, 12),
        ]))

    story.append(Paragraph(
        "Sources: California Public Notices (CNPA) search for NOTICE OF PETITION TO ADMINISTER ESTATE, "
        "Placer County; Placer Superior Court eCourt Public Case Search. "
        "Assessor/Recorder match is still required before treating any estate as a property lead. "
        "No inventory and appraisal appears on these public registers yet.",
        s["foot"],
    ))

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.42 * inch,
        title=f"Placer County Daily Probate Feed — {run_date.isoformat()}",
        author="Hammond IT Consulting — Blake Hammond Realty",
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return out_path
