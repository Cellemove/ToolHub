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

1. Run the migrations in order in the Supabase SQL editor. Migration
   `004_roas_offers.sql` creates and pre-populates the active market/bundle overview.
2. Copy `.env.example` to `.env`, fill `SUPABASE_URL` + `SUPABASE_ANON_KEY`.
3. Set the server-only `SUPABASE_SERVICE_KEY` to enable **Set as active offer**.
   Do not expose this key through a `VITE_` variable or client code.
4. Start the backend with `uvicorn app.main:app --reload --env-file ../.env`.

The calculator itself is test mode: changing inputs and calculating never writes a
record. An operator must explicitly choose **Set as active offer**. That action
upserts the `(market, product, bundle)` slot, so each slot has exactly one active
configuration and the overview updates without storing discarded tests.
Each overview row also has a two-step **Remove → Confirm remove** action. The
backend deletes only the exact `(market, product, bundle)` slot via the
server-only service-role credential.
The calculator also exposes **Add bundle to sheet**, which explicitly appends
the current price, USD COGS, fees, and margin inputs to the Google Sheet. This
is independent from **Set as active offer** and prevents exact-name duplicates
that are already loaded as sheet presets.

The selling price can be entered in any supported currency (USD, EUR, GBP, CZK,
PLN, MXN, CAD, CHF, AUD, SEK, AED); COGS stays USD. ROAS math and Google Sheet
writes convert the price to USD via the FX rates, while active offers store the
price in its own currency and the backend converts when computing metrics.
Selecting a market never mutates inputs; it only changes the display-only FX panel.

Supported markets are `UK`, `USA`, `CANADA`, `PT`, `PL`, `GR`, `FR`, `DE`,
`ES`, `MX`, and `CZ`. Markets without a verified active offer remain visible
with an empty state; the app does not fabricate price or COGS configurations.

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

## Deploy (Vercel)

`vercel.json` defines two services: `frontend` (Vite static build) and `backend`
(FastAPI, entrypoint `backend/main.py`), with `/api/*` rewritten to the backend —
same-origin, so no CORS config needed in production.

In the Vercel project settings, set `SUPABASE_URL` and `SUPABASE_ANON_KEY` (and run
the two migrations in Supabase so the registry serves from the database).

Sheet presets in production use **Workload Identity Federation** (keyless): enable
OpenID Connect Federation in the Vercel project (Settings → Security, issuer mode
Team), then set on Vercel:

```
GOOGLE_IMPERSONATE_SERVICE_ACCOUNT=toolhub-sheets@toolhub-505111.iam.gserviceaccount.com
GOOGLE_WIF_AUDIENCE=//iam.googleapis.com/projects/67886675912/locations/global/workloadIdentityPools/vercel/providers/vercel
```

GCP side (once per Vercel team/project): an OIDC provider `vercel` in the pool
trusting issuer `https://oidc.vercel.com/<team-slug>`, and a
`roles/iam.workloadIdentityUser` binding on the service account for
`.../subject/owner:<team-slug>:project:<project-name>:environment:production`.

## Adding a tool

1. Insert a row in `tools` (or `FALLBACK_TOOLS` in `backend/app/main.py`).
2. Add endpoint(s) under `backend/app/`.
3. Add a page under `frontend/src/pages/` and route it in `App.tsx`.
