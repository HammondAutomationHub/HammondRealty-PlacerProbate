#!/usr/bin/env python3
"""Detailed daily probate PDF: CNPA notice + Placer eCourt public docket."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
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

from pdf_report import (
    CREAM,
    GOLD,
    LINE,
    NAVY,
    PALE,
    _footer as footer,
    _rl_link,
    _styles as styles,
)

OUT = Path(__file__).resolve().parent / "data/reports/Placer-Probate-Daily-Feed-2026-09-16.pdf"

CASES = [
    {
        "case": "S-PR-0014250",
        "caption": "Estate of Moon Harrison, Cash",
        "decedent": "Cash Moon Harrison",
        "badge": "NEW PUB",
        "filed": "05/22/2026",
        "status": "Open — Probate-Roseville",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1305677",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1005372",
        "parties": [
            "Petitioner — Crystal Moon (portal spelling: Cystal Moon)",
            "Decedent — Cash Moon Harrison",
        ],
        "petition": "Probate of Will and Letters of Administration with Will Annexed + IAEA",
        "will": "Yes (will annexed)",
        "iaea": "Yes",
        "hearings": [
            "Next: 10/26/2026 8:30 AM — Estate Hearing — Dept. 2, 101 Maple St, Auburn",
        ],
        "docs": [
            "05/22/2026 Petition: Probate of Will / Letters w/ Will Annexed + IAEA",
            "06/24/2026 Notice: Petition to Administer Estate (hearing 10/26/2026)",
        ],
        "attorneys": [
            "Court: Lyon, Kathleen Cordova — Aronowitz Skidmore Lyon — assigned 05/22/2026 (Current)",
            "Notice: Kathleen C. Lyon, SBN 236224 — 200 Auburn Folsom Rd., Ste. 305, Auburn — 530-823-9736",
        ],
        "publication": "Auburn Journal — Sep 12, 19, 26, 2026 (post date 09/12/2026)",
        "fees": "06/08/2026 $435 filing paid (balance $0)",
        "flags": "Will offered. First publication in the current CNPA window.",
    },
    {
        "case": "S-PR-0014117",
        "caption": "Estate of Clyde, Timothy Scott",
        "decedent": "Timothy Scott Clyde",
        "badge": "CONTESTED",
        "filed": "03/26/2026",
        "status": "Open — Probate-Roseville — intestate",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1294920",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1004771",
        "parties": [
            "Petitioner (portal) — Nikkollette Clyde",
            "Petitioner (published notice) — Joyce O'Malley",
            "Decedent — Timothy Clyde / Timothy Scott Clyde",
            "Objector — Eric Sparks",
        ],
        "petition": "Letters of Administration (intestate) — amended petitions on file",
        "will": "No (intestate administration)",
        "iaea": "Yes (notice)",
        "hearings": [
            "Next: 10/26/2026 8:30 AM — Estate Hearing — Intestate admin — Dept. 2, Auburn",
            "07/27/2026 8:30 AM — Intestate admin — Heard: Continued by Parties — Hon. Glenn M. Holley, Dept. 2",
            "07/24/2026 8:30 AM — Estate Hearing — Continued: Court — Dept. 40",
        ],
        "docs": [
            "03/26/2026 Petition: Letters of Administration; Fee Waiver Request + Order Full",
            "04/17/2026 Notice: Petition to Administer Estate (7/24/2026)",
            "05/08/2026 Proof: Publication",
            "05/27/2026 and 05/29/2026 Notices: Rejection by Clerk (incl. objection)",
            "06/02/2026 Order: Continuing Hearing",
            "07/10/2026 Objection: to Petition for Letters of Administration",
            "07/13/2026 Amended Petition + Supplement + Duties of PR + Notice",
            "07/23/2026 Minutes — Civil; 07/27/2026 Proof of service of continuance",
            "08/06/2026 Declaration: Verification to Objection; 08/24/2026 Amended Petition",
        ],
        "attorneys": [
            "Court (from 07/10/2026): Katz, Brian R — Current (timing matches the objection)",
            "Notice counsel: Paul R. Kraft, SBN 218765 — 5170 Golden Foothill Pkwy, El Dorado Hills — (530) 344-0204",
        ],
        "publication": "Auburn Journal — Sep 9, 16, 23, 2026. Earlier proof of publication filed 05/08/2026.",
        "fees": "04/01/2026 $435; 07/20/2026 $435 GC-70655; 07/21/2026 $15.50 remote — all paid",
        "flags": "CONTESTED. Notice petitioner (Joyce O'Malley) does not match portal petitioner (Nikkollette Clyde). Hearing continued; notice said Oct 5, portal now Oct 26.",
    },
    {
        "case": "S-PR-0014286",
        "caption": "Estate of Palmer, James E",
        "decedent": "James E. Palmer",
        "badge": "OPEN",
        "filed": "06/09/2026",
        "status": "Open — Probate-Roseville",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1308196",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1004318",
        "parties": [
            "Petitioner — Jessica Palmer / Jessica L. Palmer",
            "Decedent — James Palmer / James E. Palmer",
        ],
        "petition": "Probate of Will and Letters Testamentary + IAEA",
        "will": "Yes",
        "iaea": "Yes",
        "hearings": [
            "Next: 11/09/2026 8:30 AM — Estate Hearing — Dept. 2, 101 Maple St, Auburn",
        ],
        "docs": [
            "06/09/2026 Petition: Probate of Will and Letters Testamentary + IAEA",
            "06/09/2026 Duties / Liabilities of Personal Representative",
            "08/10/2026 Notice: Petition to Administer Estate (11/9/2026)",
        ],
        "attorneys": [
            "Court: Kochenderfer, Stanley Ross Jr. — assigned 06/09/2026",
            "Notice: S. Ross Kochenderfer Jr., SBN 78829 — 12210 Herdal Dr., Ste. 11, Auburn — (530) 823-9858",
        ],
        "publication": "Auburn Journal — Sep 5, 12, 19, 2026 (post date 09/05/2026)",
        "fees": "06/23/2026 $435 commencing petition paid",
        "flags": "Uncontested on the public register so far. Will offered.",
    },
    {
        "case": "S-PR-0014199",
        "caption": "Estate of Tenzler, Marlene Y.",
        "decedent": "Marlene Y. Tenzler",
        "badge": "HEARING 9/21",
        "filed": "04/30/2026",
        "status": "Open — Probate-Roseville — probate of will",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1302176",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1002236",
        "parties": [
            "Petitioner — Flora Tenzler-Fleischbein / Flora A. Tenzler-Fleischbein",
            "Decedent — Marlene Tenzler / Marlene Y. Tenzler",
        ],
        "petition": "Probate of Will and Letters Testamentary",
        "will": "Yes — certified copy of will filed 08/27/2026",
        "iaea": "Yes (notice)",
        "hearings": [
            "Next: 09/21/2026 8:30 AM — Estate Hearing — Probate will — Dept. 2",
            "Notice listed Gibson Courthouse, Roseville; portal lists Dept. 2 / Maple St, Auburn",
        ],
        "docs": [
            "04/30/2026 Petition: Probate of Will and Letters Testamentary + Duties of PR",
            "08/27/2026 Notice: Petition to Administer Estate (9/21/2026)",
            "08/27/2026 Declaration: Certified Copy of Order Admitting Will to Probate",
            "08/27/2026 Declaration: Certified Copy of Will",
            "08/27/2026 Declarations of Flora A. Tenzler-Fleischbein and David J. Britton",
        ],
        "attorneys": [
            "Court: Kokka, Ralph Takao — Patton Martin &amp; Sullivan, LLP — assigned 04/30/2026",
            "Notice: Ralph Kokka, SBN 143519 — 12647 Alcosta Blvd., Ste. 430, San Ramon — (925) 600-1800",
        ],
        "publication": "Placer Herald, Roseville Press-Tribune, Loomis News — Sep 4, 11, 18, 2026",
        "fees": "05/14/2026 $435 petition; 09/16/2026 $15.50 remote appearance — paid",
        "flags": "Hearing is 09/21/2026 (this week). Certified will already in the file. Remote appearance fee posted today.",
    },
    {
        "case": "S-PR-0014165",
        "caption": "Estate of Unhassobiscay, Jean",
        "decedent": "Jean Unhassobiscay",
        "badge": "CONTESTED / PA",
        "filed": "04/23/2026 (PA) · 07/02/2026 (Young)",
        "status": "Open — Probate-Roseville — competing intestate petitions",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1298659",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1002921",
        "parties": [
            "Petitioner — Placer County Public Administrator (filed 04/23/2026)",
            "Petitioner — Zachary Young (filed 07/02/2026; published notice)",
            "Decedent — Jean Unhassobiscay",
            "Objector — Zachary Young",
            "Supporting declarations — Michael Biscay, Alain Biscay",
        ],
        "petition": "Two Letters of Administration + IAEA petitions (Public Administrator and Zachary Young)",
        "will": "No (intestate on calendar)",
        "iaea": "Yes",
        "hearings": [
            "Next: 11/09/2026 8:30 AM — Intestate admin (Z Young) — Dept. 2, Auburn",
            "Next: 11/09/2026 8:30 AM — Intestate (Public Admin) — Dept. 2, Auburn",
            "08/31/2026 — Public Admin — Heard: Continued by Parties — Hon. Glenn M. Holley",
            "08/28/2026 — Continued: Court — Dept. 40",
        ],
        "docs": [
            "04/23/2026 PA Petition: Letters of Administration + IAEA + Duties",
            "06/08/2026 Order: Continuing Hearing",
            "07/02/2026 Objection to appointment of Public Administrator",
            "07/02/2026 Declarations of Michael Biscay and Alain Biscay; nominations; Young petition",
            "08/26/2026 Amended notice; 08/27/2026 Minutes — Civil",
        ],
        "attorneys": [
            "PA counsel (04/23/2026): McClelland, Danika Lynn — Placer County Counsel — Current",
            "Young counsel (07/02/2026): Duggan, Jennifer — Duggan McHugh Law Corporation — Current",
            "Notice: Jennifer Duggan, SBN 183833 — 100 Howe Ave., Ste. 260, Sacramento — (916) 550-5309",
        ],
        "publication": "Amended notice, Auburn Journal — Sep 2, 9, 16, 2026 (post date 09/02/2026)",
        "fees": "04/24/2026 $435 PA; 08/05/2026 $435 + $435 Young; 08/13/2026 $15.50 remote — paid",
        "flags": "Two petitioners fighting over appointment. Public Administrator vs family/nominee.",
    },
    {
        "case": "S-PR-0014216",
        "caption": "Estate of Albrecht, Peter",
        "decedent": "Peter Albrecht",
        "badge": "HEARING 9/28",
        "filed": "05/14/2026",
        "status": "Open — Probate-Roseville — portal role: Administrator",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1302310",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1001541",
        "parties": [
            "Administrator (portal) — Christopher Albrecht",
            "Decedent — Peter Albrecht",
        ],
        "petition": "Letters of Administration + IAEA",
        "will": "No",
        "iaea": "Yes",
        "hearings": [
            "Next: 09/28/2026 8:30 AM — Estate Hearing — Dept. 2",
            "Published notice listed 10820 Justice Center Dr, Roseville",
        ],
        "docs": [
            "05/14/2026 Petition: Letters of Administration + IAEA",
            "05/26/2026 Duties / Liabilities of Personal Representative",
            "05/27–05/28/2026 Notices of hearing / petition (9/28/2026)",
            "06/26/2026 Proof: Publication",
            "06/30/2026 Waiver: Bond (two entries)",
            "08/19/2026 Re-notice of hearing and petition (9/28/2026)",
        ],
        "attorneys": [
            "Court: Breunig, Mark Robert — assigned 05/14/2026",
            "Notice: Mark Breunig, SBN 175937 — 554 E Street, Lincoln — (916) 672-2042",
        ],
        "publication": "Auburn Journal — Aug 29, Sep 5, 12, 2026. Proof of publication already on file.",
        "fees": "05/14/2026 $435 first petition paid",
        "flags": "Portal already labels Christopher Albrecht as Administrator. Bond waivers filed. Hearing 09/28/2026.",
    },
    {
        "case": "S-PR-0014190",
        "caption": "Estate of Gunion, Denis R.",
        "decedent": "Denis R. Gunion",
        "badge": "CONTINUED",
        "filed": "04/28/2026",
        "status": "Open — Probate-Roseville — probate of will",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1302138",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_1001841",
        "parties": [
            "Petitioner — Robert Gunion / Robert D. Gunion",
            "Decedent — Denis Gunion / Denis R. Gunion",
        ],
        "petition": "Probate of Will and Letters Testamentary",
        "will": "Yes",
        "iaea": "Yes (notice)",
        "hearings": [
            "Next: 02/08/2027 8:30 AM — Estate Hearing — Probate will — Dept. 2, Auburn",
            "09/14/2026 8:30 AM — Probate will — Heard: Continued by Parties — Hon. Glenn M. Holley",
        ],
        "docs": [
            "04/28/2026 Petition: Probate of Will and Letters Testamentary + Duties of PR",
            "09/08/2026 Notice: Petition to Administer Estate (9/14/2026)",
            "09/11/2026 Minutes — Civil",
        ],
        "attorneys": [
            "Court: Patton, Rachel Penn — Patton Law Group — assigned 04/28/2026",
            "Notice: Rachel P. Patton, SBN 265353 — 919 Reserve Dr., Ste. 114, Roseville — 916-626-2932",
        ],
        "publication": "Auburn Journal — Aug 29, Sep 5, 12, 2026 (post date 08/29/2026)",
        "fees": "05/14/2026 $435 commencing petition paid",
        "flags": "Sep 14 hearing continued by the parties to Feb 8, 2027. Newspaper notice is stale on the hearing date.",
    },
    {
        "case": "S-PR-0014335",
        "caption": "Estate of Eisley, James Milton",
        "decedent": "James Milton Eisley a.k.a. James M. Eisley",
        "badge": "COMPANION",
        "filed": "07/09/2026",
        "status": "Open — Probate-Roseville",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1310799",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_999919",
        "parties": [
            "Petitioner — William Eisley / William H. Eisley",
            "Decedent — James Eisley / James Milton Eisley",
        ],
        "petition": "Probate of Will and Letters Testamentary + IAEA",
        "will": "Yes",
        "iaea": "Yes",
        "hearings": [
            "Next: 11/23/2026 8:30 AM — Estate Hearing — Dept. 2, 101 Maple St, Auburn",
        ],
        "docs": [
            "07/09/2026 Petition: Probate of Will and Letters Testamentary + IAEA",
            "07/15/2026 Notice: Petition to Administer Estate (11/23/2026)",
            "09/11/2026 Proof: Publication",
        ],
        "attorneys": [
            "Court: Wilson, Randall Ray — Sinclair Wilson Baldo &amp; Chamberlain — assigned 07/09/2026",
            "Notice: Randall R. Wilson, SBN 103594 — 2390 Professional Dr., Roseville — 916-783-5281",
        ],
        "publication": "Auburn Journal — Aug 26, Sep 2, 9, 2026 (post date 08/26/2026)",
        "fees": "07/13/2026 $435 commencing petition paid",
        "flags": "Companion to S-PR-0014334 (Jacqueline Ball / Eisley). Same petitioner, counsel, filing date, and hearing.",
    },
    {
        "case": "S-PR-0014334",
        "caption": "Estate of Ball, Jacqueline Ann",
        "decedent": "Jacqueline Ann Ball a.k.a. Jackie A. Ball, Jacqueline Ann Eisley, Jackie A. Eisley",
        "badge": "COMPANION",
        "filed": "07/09/2026",
        "status": "Open — Probate-Roseville",
        "url": "https://webportal.placerco.org/eCourtPublic/?q=node/45/1310796",
        "notice_url": "https://www.capublicnotice.com/advert/-Notices_999918",
        "parties": [
            "Petitioner — William Eisley / William H. Eisley",
            "Decedent — Jacqueline Ball / Jacqueline Ann Ball",
        ],
        "petition": "Probate of Will and Letters Testamentary + IAEA",
        "will": "Yes",
        "iaea": "Yes",
        "hearings": [
            "Next: 11/23/2026 8:30 AM — Estate Hearing — Dept. 2, 101 Maple St, Auburn",
        ],
        "docs": [
            "07/09/2026 Petition: Probate of Will and Letters Testamentary + IAEA",
            "07/15/2026 Notice: Petition to Administer Estate (11/23/2026)",
            "09/11/2026 Proof: Publication",
        ],
        "attorneys": [
            "Court: Wilson, Randall Ray — Sinclair Wilson Baldo &amp; Chamberlain — assigned 07/09/2026",
            "Notice: Randall R. Wilson, SBN 103594 — 2390 Professional Dr., Roseville — (916) 783-5281",
        ],
        "publication": "Auburn Journal — Aug 26, Sep 2, 9, 2026 (post date 08/26/2026)",
        "fees": "07/13/2026 $435 commencing petition paid",
        "flags": "Companion to S-PR-0014335. Search assessor under both Ball and Eisley.",
    },
]


def cover(s):
    kpis = Table([[
        [Paragraph("9", s["kpi_n"]), Paragraph("UNIQUE ESTATES", s["kpi_l"])],
        [Paragraph("2", s["kpi_n"]), Paragraph("CONTESTED", s["kpi_l"])],
        [Paragraph("2", s["kpi_n"]), Paragraph("HEARINGS THIS MONTH", s["kpi_l"])],
        [Paragraph("2", s["kpi_n"]), Paragraph("COMPANION CASES", s["kpi_l"])],
    ]], colWidths=[1.8 * inch] * 4)
    kpis.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CREAM),
        ("BOX", (0, 0), (-1, -1), 0.4, GOLD),
        ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    header = [Paragraph(h, s["th"]) for h in ["Case", "Decedent", "Filed", "Next hearing", "Watch"]]
    rows = [header]
    for c in CASES:
        rows.append([
            Paragraph(_rl_link(c["url"], c["case"]), s["td"]),
            Paragraph(c["decedent"], s["td"]),
            Paragraph(c["filed"], s["td"]),
            Paragraph(c["hearings"][0].replace("Next: ", ""), s["td"]),
            Paragraph(c["badge"], s["td"]),
        ])
    roster = Table(rows, colWidths=[1.15*inch, 1.55*inch, 1.35*inch, 2.35*inch, 1.0*inch])
    cmds = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("GRID", (0, 0), (-1, -1), 0.25, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, c in enumerate(CASES, 1):
        bg = colors.HexColor("#F8E8E8") if "CONTESTED" in c["badge"] else (PALE if i % 2 else colors.white)
        cmds.append(("BACKGROUND", (0, i), (-1, i), bg))
    roster.setStyle(TableStyle(cmds))
    return [
        Paragraph("HAMMOND IT CONSULTING  ·  BLAKE HAMMOND REALTY", s["kicker"]),
        Paragraph("Daily Probate Petition Feed — Case Dossiers", s["title"]),
        Paragraph("Wednesday, September 16, 2026  ·  Placer County  ·  CNPA notices + eCourt Public summaries", s["sub"]),
        Paragraph(
            "Each estate below merges the published Notice of Petition to Administer Estate with the "
            "public Case Summary (parties, filing date, hearings, document titles, counsel). "
            "PDFs on the register are listed by title only — the public portal does not allow download.",
            s["body"],
        ),
        Spacer(1, 8),
        kpis,
        Paragraph("Roster — click the case number for the court Case Summary", s["h"]),
        roster,
        Spacer(1, 8),
        Paragraph(
            "Priority this week: Tenzler hearing 9/21 · Albrecht hearing 9/28 · Clyde and Unhassobiscay are contested. "
            "Gunion continued to Feb 2027. Eisley/Ball are companion wills set 11/23.",
            s["body"],
        ),
        PageBreak(),
    ]


def kv_table(pairs, s):
    data = [[Paragraph(k, s["label"]), Paragraph(v, s["td"])] for k, v in pairs]
    t = Table(data, colWidths=[1.25 * inch, 6.15 * inch])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ("BACKGROUND", (0, 0), (0, -1), CREAM),
    ]))
    return t


def case_block(c, s):
    head = Paragraph(
        f'{c["case"]}  ·  {c["caption"]}<br/>'
        f'<font size="8" color="#2F4F6F">{c["badge"]}  ·  {c["status"]}</font>',
        s["case"],
    )
    links = Paragraph(
        f'Court file: {_rl_link(c["url"], c["url"])}<br/>'
        f'Published notice: {_rl_link(c["notice_url"], c["notice_url"])}',
        s["small"],
    )
    body = kv_table([
        ("Filed", c["filed"]),
        ("Petition", c["petition"]),
        ("Will / IAEA", f'{c["will"]}  /  {c["iaea"]}'),
        ("Parties", "<br/>".join(c["parties"])),
        ("Hearings", "<br/>".join(c["hearings"])),
        ("Documents", "<br/>".join(c["docs"])),
        ("Counsel", "<br/>".join(c["attorneys"])),
        ("Publication", c["publication"]),
        ("Fees paid", c["fees"]),
    ], s)
    flag = Paragraph(c["flags"], s["flag"])
    bar = Table([[""]], colWidths=[7.4 * inch], rowHeights=[4])
    bar.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GOLD)]))
    return KeepTogether([
        bar,
        Spacer(1, 6),
        head,
        Spacer(1, 3),
        links,
        Spacer(1, 6),
        body,
        Spacer(1, 4),
        flag,
        Spacer(1, 12),
    ])


def main():
    s = styles()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(OUT),
        pagesize=letter,
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.42 * inch,
        title="Placer County Daily Probate Feed — 16 Sep 2026",
        author="Hammond IT Consulting — Blake Hammond Realty",
    )
    story = cover(s)
    story.append(Paragraph("Case dossiers", s["h"]))
    for c in CASES:
        story.append(case_block(c, s))
    story.append(Paragraph(
        "Sources: California Public Notices (CNPA) search for NOTICE OF PETITION TO ADMINISTER ESTATE, "
        "Placer County; Placer Superior Court eCourt Public Case Search, Filed 01/01/2026–12/31/2026. "
        "Assessor/Recorder match is still required before treating any estate as a property lead. "
        "No inventory and appraisal appears on any of these public registers yet.",
        s["foot"],
    ))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    print(OUT)


if __name__ == "__main__":
    main()
