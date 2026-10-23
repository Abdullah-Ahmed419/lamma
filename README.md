# Lamma | لَمّة

Cardboard collection and pickup-round planning prototype for SolveThe17, SDG 11.

## Current prototype

- Arabic, mobile-friendly shop and collector views.
- Add and cancel collection requests.
- Suggest rounds using approximate location, capacity and pickup period.
- Reserve requests, release unfinished stops, and record actual weight and agreed price.
- Display collected weight and transaction totals.

The role switcher is a demo control, not authentication. Data is stored only in the current browser's localStorage. Locations are illustrative area centers; distances are straight-line estimates, not driving routes. Recorded collections do not prove recycling. Transaction totals are not collector profit.

## Run locally

Requires Python 3 for the local static server:

```sh
python -m http.server 8000 --directory dist
```

Open http://localhost:8000. No dependency installation or API keys are needed for this prototype.

## Project files

- `dist/index.html`: page structure.
- `dist/style.css`: responsive styling.
- `dist/app.js`: demo state, requests, rounds and receipts.

## Planned multi-user MVP

- Arabic and English with RTL/LTR layouts.
- Authentication and server-enforced shop, collector and admin permissions.
- Shared database and atomic request booking.
- Real pickup locations and map display.
- Shop confirmation of collection weight and price.
- Role-specific summaries and operational administration.

These features are not implemented in the current prototype.

## Verification

JavaScript syntax and simulated request lifecycle checks passed for capacity selection, booking, completion and transaction totals. Browser visual QA remains pending.

## GitHub destination

https://github.com/Abdullah-Ahmed419/lamma

Never commit credentials or personal customer information. The demo does not currently require an environment file.
