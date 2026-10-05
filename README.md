# Happen

Turn your evening into a checked plan.

Describe one evening in your own words. Happen checks live place listings through SerpApi and returns one source-backed plan with up to two stops. Anything the sources do not confirm is marked as unknown.

General chat helps you explore possibilities. Happen narrows them into one feasible sequence, shows what was checked, and keeps unsupported details unknown.

## How it works

1. **Describe.** Write the evening, for example: *Coffee in Mexico City on Wednesday at 6 pm, then a museum, for two.*
2. **Review.** Happen turns it into a short brief: place, date, time, stop order, group size, and budget. If something essential is missing, it asks one question. You can edit any detail.
3. **Plan.** **Check live places** searches SerpApi. Python checks opening hours and your requested details, then picks at most two stops.

Each stop shows its time, why it was chosen, the listing details, and one **Couldn't confirm** line. **View sources** opens what was checked, the planned day's hours, the source links, and a full audit with retrieval times.

To change the plan, type the change and choose **Review this change**. Your current plan stays until you choose **Apply**.

## What runs

- **SerpApi** is the only external data source. It delivers Google Maps listings, official websites, and community text. The facts come from those sources, not from SerpApi.
- **Python** reads the prompt with a deterministic parser, checks feasibility, and chooses the stops. Missing evidence never counts in a place's favour.
- **The customer path loads no model.** A local Gemma model was measured and failed its quality gates (`ml/reports/model-quality.json`), so it stays off. No hosted model API is called.
- **Each plan makes at most eight billed SerpApi requests.** The server keeps the count. Identical searches are cached in memory for 15 minutes.

There is no database, no account, and no paid service besides SerpApi.

## Run it locally

Create the environment file and add your SerpApi key. Never commit `.env`.

```bash
cp .env.example .env
# set SERPAPI_API_KEY and HAPPEN_LIVE_ENABLED=true
```

Backend:

```bash
cd backend
uv sync
uv run uvicorn happen_api.main:app --host 127.0.0.1 --port 8000
```

Frontend, in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://127.0.0.1:5173`. Health is at `http://127.0.0.1:8000/healthz`.

The model file is optional and only used for evaluation: `python3 scripts/download-model.py`. Do not commit `*.gguf` files.

## Tests

Automated tests use mocks and fixtures. They never spend SerpApi credits.

```bash
cd backend
uv run ruff format --check src tests ../scripts/scan-secrets.py
uv run ruff check src tests ../scripts/scan-secrets.py
uv run pytest
cd ..
python3 scripts/scan-secrets.py
cd frontend
npm run check
npm test
npm run build
npm run test:shell   # Playwright and axe at 1280px and 390px
```

## Limits

- One evening, at most two stops.
- No travel time. The second stop shows its listed hours and a directions link, not a calculated arrival.
- No live crowd levels, reservations, capacity checks, or price conversion.
- No stop swapping or alternative stops once a plan is built.
- The request count and cache live in one process and reset when it restarts.
- Production never serves captured fixtures. They exist only for tests.
