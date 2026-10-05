# Placer County daily probate monitor

Hammond IT Consulting — Blake Hammond Realty

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=HammondAutomationHub&repository=HammondRealty-PlacerProbate&category=integration)

Pulls [CNPA public notices](https://www.capublicnotice.com) for **NOTICE OF PETITION TO ADMINISTER ESTATE** in **Placer County**, looks up each `S-PR` number on [Placer eCourt Public](https://webportal.placerco.org/eCourtPublic/?q=node/48), writes a dossier PDF, and can email the digest.

This GitHub repo can be added in **HACS** as a custom **integration**, or in the **Add-on Store** as a Supervisor add-on repository. Use one or the other, not both, or you will scrape twice.

HACS does not install Home Assistant add-ons. The add-on is installed from Supervisor, not from HACS.

A published petition is **not** proof that a house is in the estate.

## Install with HACS

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Repository: `https://github.com/HammondAutomationHub/HammondRealty-PlacerProbate`
3. Type: **Integration**
4. Download **Placer Probate Monitor**, then restart Home Assistant
5. Settings → Devices & services → **Add integration** → Placer Probate Monitor
6. Set recipients, SMTP, frequency (hourly / daily / weekdays / weekly / monthly), and search options

After that, configure it from the integration’s **Configure** menu. Services:

- `placer_probate_monitor.run_now`
- `placer_probate_monitor.test_email`

Reports are stored under `/config/placer_probate_monitor/reports` (or your Home Assistant config folder).

If your GitHub URL is different, paste that URL instead.

## Install as a Home Assistant add-on

Supervisor looks for `repository.yaml` at the repo root and `config.yaml` in a subfolder.

1. Settings → Add-ons → Add-on Store → ⋮ → **Repositories**
2. Add `https://github.com/HammondAutomationHub/HammondRealty-PlacerProbate`
3. Install **Placer Probate Monitor**, start it, **Open Web UI**
4. Recipients, SMTP, schedule, and search knobs are in that UI

Local / unpublished install: copy the repo to `/addons/placer-probate-monitor` on the host, then Check for updates and install from **Local add-ons**.

The add-on listens on ingress port 8099. Reports land in `/data/reports` inside the container.

## What you get per estate

From the newspaper notice:

- Decedent, petitioner, case number
- Hearing text printed in the ad
- Will / IAEA flags
- Attorney name, firm, phone
- Paper and publication dates
- Notice URL

From the court portal (same session as a manual search):

- Case search on [Placer eCourt Public](https://webportal.placerco.org/eCourtPublic/?q=node/48) (Case Summary deep links 404 unless you search first)
- Official caption and filing date
- Parties (petitioner, decedent, objector, administrator)
- Next hearing and prior hearings
- Document register titles and dates
- Court-assigned counsel
- Filing / appearance fees

## CLI setup

```bash
cd placer-probate-monitor
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` only if you want email. Gmail needs an
[App Password](https://myaccount.google.com/apppasswords), not your normal password.

## Run

Print + write files, do not email, do not update seen-cases
(NEW vs SEEN is computed in memory):

```bash
python3 placer_probate_monitor.py --dry-run
```

CNPA + eCourt + PDF, no email:

```bash
python3 placer_probate_monitor.py --no-email
```

Full daily job (update tracker and email PDF):

```bash
python3 placer_probate_monitor.py
```

Skip the court portal if it is down:

```bash
python3 placer_probate_monitor.py --no-email --skip-portal
```

Outputs in `data/reports/`:

- `Placer-Probate-Daily-Feed-YYYY-MM-DD.pdf`
- `dossiers-YYYY-MM-DD.json` (merged notice + portal)
- `notices-YYYY-MM-DD.json`
- `report-YYYY-MM-DD.html` / `.txt`

## Home Assistant add-on

This repo is also a Supervisor add-on. Prefer **Install as a Home Assistant add-on** above (GitHub repository URL). The Ingress UI covers recipients, SMTP, frequency, timezone, lookback, Run now, and test email.

## Daily schedule (CLI)

Linux / macOS cron (8:30 a.m. Pacific):

```cron
TZ=America/Los_Angeles
30 8 * * * cd /FULL/PATH/placer-probate-monitor && .venv/bin/python placer_probate_monitor.py >> data/cron.log 2>&1
```

macOS launchd: a LaunchAgent that runs the same command.

Windows Task Scheduler: start program
`C:\path\to\.venv\Scripts\python.exe` with argument
`placer_probate_monitor.py` and start-in folder set to the project.

## How the court lookup works

The public Case Summary URL 404s if you open it cold.
The script:

1. GET the search form (and abort if expected Drupal field names are missing)
2. POST case number + Filed `01/01/{year-2}`–`12/31/{year+1}`
3. Read filing date / next event / Case Summary link
4. GET that link **in the same cookie session**
5. Pause ~1.2 seconds between cases

Do not raise the rate. One run per day is enough.

## Files

| File | Role |
|---|---|
| `hacs.json` | HACS custom-repository metadata |
| `brand/icon.png` | HACS brand icon (also at `custom_components/placer_probate_monitor/brand/icon.png`) |
| `custom_components/placer_probate_monitor/` | Home Assistant integration (HACS) |
| `repository.yaml` | Supervisor add-on repository index |
| `placer_probate_monitor/` | Home Assistant add-on (Dockerfile, Ingress UI) |
| `placer_probate_monitor.py` | CLI entry point |
| `ecourt_client.py` | Placer portal search + Case Summary parse |
| `pdf_report.py` | Dossier PDF |
| `make_sample_pdf.py` | Frozen 16 Sep 2026 sample (optional) |

## Limits

- Portal documents are titles only. You cannot download the petition from the public site.
- No inventory / appraisal and no APN appear on these pages.
- CNPA only has papers that upload. A filing with no published notice will not show up here.
- If eCourt HTML changes, `ecourt_client.py` is the file to adjust.
