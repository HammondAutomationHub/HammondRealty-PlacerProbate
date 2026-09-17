# Placer Probate Monitor add-on

Supervisor add-on for Hammond IT's Placer County probate notice monitor.

## Install

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add `https://github.com/HammondAutomationHub/HammondRealty-PlacerProbate`
3. Install **Placer Probate Monitor**, start it, then **Open Web UI**

Do not also run the HACS integration on the same instance, or the scrape will run twice.

## Configuration

Set recipients, SMTP, schedule, and CNPA/eCourt search options in the add-on web UI (ingress). Gmail needs an [App Password](https://myaccount.google.com/apppasswords).

Reports are written to `/data/reports` inside the add-on container.

## Ports

Ingress uses port 8099 inside the add-on. Open the UI from the add-on page rather than exposing that port on the host unless you need it.
