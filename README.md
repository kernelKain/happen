# Happen

Happen plans one evening from a prompt. The plan has at most two stops, and each stop is tied to live place evidence for that destination.

It is for someone who already knows the night they want: dinner in one city, then one more stop, at a time that fits that place. It is not a multi-day itinerary and it does not claim it can plan every city, venue, language, or evening.

## Prompt-led workflow

1. You describe one evening in your own words.
2. Happen turns that wording into an editable brief: destination, one local date, one start time, and at most two intents.
3. If the place, the date, or the time is missing, Happen asks one question and waits.
4. If the destination matches more than one place, you choose before any billed search.
5. **Find the plan** retrieves live place evidence and shows a timeline of at most two stops.
6. A later change shows a diff. The current timeline stays until you apply the change.

An example on the page fills the composer. It does not send a search.

## What the customer path actually runs

The customer path loads no model. Reading your prompt is deterministic local
parsing in `backend/src/happen_api/planning/interpret.py`. Choosing and ordering
the stops is Python in `backend/src/happen_api/planning/itinerary.py`, scoring
from retrieved evidence only. A fact the retrieval did not supply adds nothing,
so an unknown hour or an unverified preference cannot win a comparison.

Local Gemma remains in the repository for reproducible evaluation, not for the
request path. No hosted model API receives the prompt; the prompt never leaves
the machine. Unused model weights do not improve a plan, and this README does
not claim they do.

## Measured model quality

The quality report is `ml/reports/model-quality.json`, measured on 2026-10-05. Claims stay off (`claims_enabled` is false). The selected fallback is `deterministic_parser`.

Gates: schema parse rate at least 0.95, essential planning-field accuracy at least 0.90, and review dimension-polarity accuracy at least 0.80.

The pinned model stays `google_gemma-3-270m-it-Q4_K_M.gguf` (sha256 `c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800`). On 24 planning examples it parsed 22 (parse rate 0.9167) and got 64 of 96 essential fields right (0.6667). Both the schema gate and the essential-field gate failed. On 30 held-out review examples it parsed 2 (0.0667) and its dimension-polarity accuracy was 0.0444. The review gate failed.

A public 1B candidate was measured and not selected. It parsed all 24 planning examples and passed the schema gate, but essential-field accuracy was 0.7917, below 0.90. Review polarity was 0.6778, below 0.80. The deterministic parser remains the reader.

## SerpApi provenance, cache, and the eight-request cap

SerpApi is the only external source of place data and supporting web data. Shown places carry source provenance and a retrieval timestamp. Clock times use the destination's local zone. A fact the retrieval did not supply stays unknown. Unknown hours are not treated as a reason to pick a stop.

One submitted plan may spend at most eight billed SerpApi requests. Place search, details, reviews, supporting web search, a paid destination-resolution fallback, and a retry that consumes a credit all count. The free Locations API does not. Happen stops before a ninth billed request.

The count is kept on the server. Reading a prompt issues an opaque plan token, and both billed routes require it, so a caller cannot lower or reset its own reported spend by sending a number. Destination resolution and place discovery draw on that one allowance rather than getting eight each. A refinement keeps the same token, so a rescore from stored evidence spends nothing. A refinement treated as a new submitted plan is issued a fresh token deliberately and gets a fresh cap of eight.

Identical place lists are cached in memory for 15 minutes, at most 32 entries. The cache key is a sha256 of the canonical destination, the local date, the time window, and the ordered intents. It does not store the prompt, the API key, raw provider payloads, or review text. A repeat of that same plan does not send another provider request. Quota, timeout, and empty results are not cached. The cache belongs to one process and is gone when that process stops.

`HAPPEN_SERPAPI_SEARCH_BUDGET` in `.env.example` is the older development live-guard budget. It is not the evening-plan cap. The plan cap is eight, in `PLAN_BILLED_REQUEST_LIMIT`.

## Local setup

Copy the example environment and fill the two secrets on your machine. Do not commit `.env`, and do not paste either value into chat, logs, or docs.

```bash
cp .env.example .env
```

- `SERPAPI_API_KEY` is the SerpApi key. Leave live mode off until this is set.
- `HF_TOKEN` is optional. The pinned public GGUF does not need it.
- `APP_ENV=development` mounts the historical recommendation routes so tests can replay fixtures. Production does not mount them.
- `CORS_ALLOWED_ORIGINS` lists exact origins. Development accepts localhost and `127.0.0.1`. Production accepts `https` origins only. Credentials are not sent.
- `HAPPEN_LIVE_ENABLED=true` requires a non-empty `SERPAPI_API_KEY`.
- `VITE_API_BASE_URL` is the backend origin baked into the frontend at build time. The local default is `http://127.0.0.1:8000`.

Python dependencies live in `backend/`. Frontend dependencies live in `frontend/`.

## Download the pinned model

From the repository root:

```bash
python3 scripts/download-model.py
```

The script reads `ml/model-manifest.json`, downloads `google_gemma-3-270m-it-Q4_K_M.gguf` into `ml/.cache/`, and deletes the file if the size or sha256 does not match. A matching file already on disk prints `checksum-ok` and does not download again. Do not commit `*.gguf` files. The public quantized model does not need `HF_TOKEN`.

The customer planner still uses the deterministic parser when this file is absent, corrupt, or below the quality gate.

## Run the app

Frontend, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the address Vite prints, usually `http://127.0.0.1:5173`.

Backend, from the repository root:

```bash
cd backend
uv sync
uv run uvicorn happen_api.main:app --host 127.0.0.1 --port 8000
```

`http://127.0.0.1:8000/healthz` returns HTTP 200. Health can report that the fixture file verifies. That status is not a plan. Neither response includes a secret.

## Tests

From the repository root:

```bash
cd backend
uv sync
uv run ruff format --check src tests ../scripts/scan-secrets.py
uv run ruff check src tests ../scripts/scan-secrets.py
uv run pytest
cd ..
python3 scripts/scan-secrets.py
cd frontend
npm ci
npm run check
npm test
npm run build
npm run test:shell
```

`npm test` is Vitest. `npm run test:shell` is Playwright, including axe, at 1280px and 390px. Playwright serves the built `dist/`, so build before the shell tests. Automated tests use fixtures and mocks. They do not spend SerpApi credits.

## Known limitations

- One evening, at most two stops. Extra nights or stops stay unplanned.
- There is no swap endpoint. A stop cannot be changed after the plan is built.
- A plan response carries no runner-up, no alternative, and no why-won
  comparison. Python picks the stops; the page shows what was picked.
- The timeline is the local start time and each stop's own hours. There is no
  calculated arrival, no departure time, no route mode, distance, or duration,
  and the second stop says so rather than implying a route.
- Happen does not claim universal coverage.
- No model loads in the customer path. Local Gemma was measured and missed its gates, so it stays disabled and model claims stay off.
- Travel time between stops stays unverified until a source states it.
- Hours, reviews, or pages the provider did not return stay unknown.
- The in-memory throttle and plan cache reset when the process stops. They are not shared across processes.
- Planning requests are limited to 16 KB and 2,000 characters.
- Production does not serve captured fixtures. Fixture files remain for tests, and a development process still mounts the historical routes for those tests.
- There is no database, account, or hosted model API.
- This branch is not deployed.

## Remaining user-owned work

The branch passes every automated check. The manual checks cannot be done from
this repository alone, so they stay with the user:

- Run the app locally and plan one real evening. Read the brief, the timeline,
  and the change as if you had never seen the code, and note anything you cannot
  explain.
- Confirm in the network tab that one submitted plan sends at most eight billed
  requests, and that asking the same evening again sends none.
- Ask a follow-up question about the plan and confirm it spends nothing. Then
  submit a refinement and confirm it opens a new eight-request allowance.
- Optionally, and only with approval, spend a few credits to measure warm p50 and
  p95 against real SerpApi. The committed benchmark is fixture-only and cannot
  answer this.
- Walk a friend through it and write down what they say is unclear.
- Create the host services, set the provider key in the host secret store, and
  deploy.
- Any public submission, including a DEV post.

Happen cannot swap a stop after the plan is built, and a plan response carries
no runner-up, no why-won comparison, no calculated arrival or departure time,
and no route distance or duration. Those are absent on purpose rather than
pending, and `docs/HANDOFF2.md` records why.

Do not put the provider key in `render.yaml`, docs, or git. `render.yaml` tracks
`main`, turns live mode on, and leaves `SERPAPI_API_KEY` as a dashboard secret
with no value in the file.

## DEV challenge story

Happen is for one person planning one real evening with someone they want to take out: a place, a date, a time, and at most one more stop. The night is specific. The product is not a general travel guide.

### What runs in the customer path

Deterministic local parsing reads the prompt into a brief. SerpApi supplies live place evidence for that evening. Python scores and selects one or two stops. No model is loaded, and no hosted model API receives the prompt.

### What was experimentally evaluated

Local open-weight Gemma was downloaded, checksummed, and measured on held-out sets. That evaluation is reproducible from this repository: the pinned artifact, the dataset, the gate thresholds, and the measured numbers are all committed. The evaluation is real work with a recorded negative result.

### What failed its gate

Both measured candidates failed. The pinned 270M model parsed 22 of 24 planning examples and missed the schema gate at 0.9167, and reached 0.6667 essential-field accuracy against a 0.90 gate. On 30 held-out review examples it parsed 2, with 0.0444 dimension-polarity accuracy against a 0.80 gate. The 1B candidate passed the schema gate but reached only 0.7917 essential-field accuracy and 0.6778 review polarity. Failed output is rejected rather than repaired into a claim, `claims_enabled` is false, and the model stays disabled.

### What SerpApi and Python actually do

SerpApi is how the plan meets the city. Place identity, hours, review-derived highlights, and supporting web facts come from SerpApi and nowhere else. Each shown fact keeps its source and retrieval time, and one submitted plan stops at eight billed requests so a single evening cannot become an unbounded crawl. Python does the feasibility checks, the scoring from retrieved evidence, and the selection. When evidence is missing or the allowance is spent, the page says so and does not substitute a captured fixture.

### The honest open-model result

No hosted model API is called, and the open weights can be checksummed, replaced, or left unused. This build does not claim a Gemma prize category: the model is measured and disabled, so open-source AI is not at the runtime core of the customer path. What the failure demonstrates is that a gate held: a model that missed its benchmark cannot invent a place, and the plan does not depend on an unmeasured claim.
