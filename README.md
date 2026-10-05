# Happen

Turn your evening into a checked plan.

Describe one evening in your own words. Happen checks live place listings through SerpApi and returns one source-backed plan with up to two stops. Anything the sources do not confirm is marked as unknown.

General chat helps you explore possibilities. Happen narrows them into one feasible sequence, shows what was checked, and keeps unsupported details unknown.

**[Try it live](https://happen-web.onrender.com/)**

| | |
|---|---|
| **Live app** | [happen-web.onrender.com](https://happen-web.onrender.com/) |
| **API health** | [happen-api.onrender.com/healthz](https://happen-api.onrender.com/healthz) |
| **Build log** | [entire.io/gh/kernelKain/happen/sessions](https://entire.io/gh/kernelKain/happen/sessions) |
| **License** | MIT — see [LICENSE](LICENSE) |

The live app spends real SerpApi credits on every uncached search. There is no login and no database, so nothing you type is stored.

## Screenshots

| Landing | Review | Result |
|---|---|---|
| ![Landing page](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/landing.png) | ![Review step](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/review.png) | ![A checked Lisbon plan](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/plan.png) |

## How it works

1. **Describe.** Write the evening, for example: *Coffee in Mexico City on Wednesday at 6 pm, then a museum, for two.*
2. **Review.** Happen turns it into a short brief: place, date, time, stop order, group size, and budget. If something essential is missing or ambiguous — "at 9" could mean morning or evening — it asks one question instead of guessing. You can edit any detail.
3. **Plan.** **Check live places** searches SerpApi. Python checks opening hours and your requested details, then picks at most two stops.

Each stop shows its time, why it was chosen, the listing details, and one **Couldn't confirm** line. **View sources** opens what was checked, the planned day's hours, the source links, and a full audit with retrieval times.

To change the plan, type the change and choose **Review this change**. Your current plan stays until you choose **Apply**.

## What runs

- **SerpApi** is the only external data source. It delivers Google Maps listings, official websites, and community text. The facts come from those sources, not from SerpApi.
- **Python** reads the prompt with a deterministic parser, checks feasibility, and chooses the stops. Missing evidence never counts in a place's favour.
- **The customer path loads no model.** A local Gemma model was measured against held-out gates and failed them (`ml/reports/model-quality.json`), so it stays off. No hosted model API is called. The gate is enforced in code: the backend hashes the model file at startup and only allows model-derived claims when the report for that exact hash says it passed. `/healthz` reports `model_claims_enabled` honestly, and it is currently `false`.
- **Each plan makes at most eight billed SerpApi requests.** The server keeps the count and refuses the ninth before it is sent. Identical searches are cached in memory for 15 minutes.

There is no database, no account, and no paid service besides SerpApi.

### Why the model is off, not missing

The original design had Gemma 3 270M extracting structured evidence from listings and reviews. It could not clear the gates, so a deterministic parser reads the prompt instead. The code, the held-out set, the quality report, and the gate are all still in the repo, because turning the model back on is a config change once a build passes. The [build log](https://entire.io/gh/kernelKain/happen/sessions) has the full session.

## Run it locally

Requires Python 3.13 and Node.js 20 or newer. Python 3.14 is not supported yet.

```bash
git clone https://github.com/kernelKain/happen.git
cd happen
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

Current suite: 466 backend tests, 68 frontend unit tests, and 22 Playwright tests with automated accessibility checks.

## Deploying

`render.yaml` defines both services, so the app deploys straight from the repository:

- `happen-web` — the built frontend as a static site.
- `happen-api` — the FastAPI backend, deployed in `singapore`.

Both track `main` and deploy only after CI passes. The backend build downloads the pinned public Gemma build and verifies its SHA-256; no Hugging Face token is needed.

Set these in the Render dashboard, never in the repository:

| Variable | Service | Notes |
|---|---|---|
| `SERPAPI_API_KEY` | `happen-api` | The only required secret. |
| `HAPPEN_LIVE_ENABLED` | `happen-api` | `true` for live retrieval. |

## Limits

- One evening, at most two stops.
- No travel time. The second stop shows its listed hours and a directions link, not a calculated arrival.
- No live crowd levels, reservations, capacity checks, or price conversion.
- No stop swapping or alternative stops once a plan is built.
- The request count and cache live in one process and reset when it restarts.
- Production never serves captured fixtures. They exist only for tests.

## Contributing

Issues and pull requests are welcome. Please read [`docs/HANDOFF.md`](docs/HANDOFF.md) first — it is the product contract, and changes are checked against it. Small pull requests with one clear purpose are easiest to review.

Run the full check suite above before opening a pull request. Please never commit a SerpApi key, and do not add a database, an authentication layer, or a hosted model API.

## Security

Do not open a public issue for a leaked credential. If you find a vulnerability, report it privately to the maintainer. SerpApi keys are read from the environment only, and `scripts/scan-secrets.py` runs over the whole tree and the production bundle in CI.

## Acknowledgements

- [SerpApi](https://serpapi.com/search-api) — the only place-data provider.
- [Gemma](https://ai.google.dev/gemma) — Google's open-weight models, evaluated locally.
- [Entire](https://entire.io/) — agent session checkpoints throughout the build.
- [Render](https://render.com) — hosting for the live app.

## License

MIT. See [LICENSE](LICENSE).
