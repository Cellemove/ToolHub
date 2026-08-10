# ToolHub

One hub for internal operator tools. First tool: **ROAS Calculator** — break-even & target
ROAS with multi-currency support, ported from `ROAS BE calculation.xlsx`.

**Stack:** React 19 + Vite + TypeScript · Python FastAPI · Supabase (Postgres)

## Run

```sh
# backend — http://127.0.0.1:8000  (docs at /docs)
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload

# frontend — http://localhost:5173  (proxies /api to the backend)
cd frontend
npm install
npm run dev
```

## Google Sheet as live source (optional)

`GET /api/roas/products` reads product presets straight from the reference
[Google Sheet](https://docs.google.com/spreadsheets/d/1-OEZQk_HvpfcGEfc1HWyrymxLNEI6mALgapLtZiPIRU/edit)
— the calculator then shows a product picker that prefills all fields, so the sheet
stays the source of truth.

The sheet stays **private** — access goes through the service account
`toolhub-sheets@toolhub-505111.iam.gserviceaccount.com` (GCP project `toolhub-505111`),
**keyless**: no key files, because that project's org policy blocks key creation.
The backend impersonates the service account via local ADC and the IAM Credentials API.

1. In Google Sheets: **Share → add `toolhub-sheets@toolhub-505111.iam.gserviceaccount.com`
   → Viewer.** Nobody else gains access.
2. `.env` sets `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`; start the backend with `--env-file ../.env`.
   Requires `gcloud auth application-default login` once on the machine, plus
   `roles/iam.serviceAccountTokenCreator` on the SA for your user (already granted).

Alternative auths (in priority order the backend tries): `GOOGLE_IMPERSONATE_SERVICE_ACCOUNT`
(impersonation), `GOOGLE_APPLICATION_CREDENTIALS` (key file, for hosts without gcloud),
public CSV export (link-shared sheets only). Point at another sheet/tab with
`ROAS_SHEET_ID` / `ROAS_SHEET_GID` (the gid is the number after `gid=` in the tab URL).
Until one path works, the endpoint returns 503 with a hint and the picker hides.

## Supabase (optional)

The API serves a built-in tool list until Supabase is configured:

1. Run `supabase/migrations/001_tools.sql` in the Supabase SQL editor.
2. Copy `.env.example` to `.env`, fill `SUPABASE_URL` + `SUPABASE_ANON_KEY`.
3. Start the backend with `uvicorn app.main:app --reload --env-file ../.env`.

## The math

All percentages are fractions of the selling price; `fees = PSP + VAT + other`.

| Output | Formula |
|---|---|
| Multiplier | `price / COGS` |
| ROAS at margin *m* | `price / (price·(1 − fees − m) − COGS)` |
| Break-even ROAS | ROAS at `m = 0` |
| Buying window | ROAS at min margin → ROAS at target margin |
| Break-even CPA | `price·(1 − fees) − COGS` (contribution per order) |

A denominator ≤ 0 means the margin is unachievable — the API returns `null` + a warning
instead of the spreadsheet's `#DIV/0!`.

## Tests

```sh
cd backend && pytest
```

Assertions pin the exact numbers from the reference spreadsheet rows.

## Adding a tool

1. Insert a row in `tools` (or `FALLBACK_TOOLS` in `backend/app/main.py`).
2. Add endpoint(s) under `backend/app/`.
3. Add a page under `frontend/src/pages/` and route it in `App.tsx`.
