# BUILD_LOG.md

Execution evidence for Happen. No secret values belong in this file.

## Verify accounts and workflow controls

- Date: 2026-10-04
- Harness: agent
- Autonomy: A1
- Spend: $0
- Decision: record the access matrix from local evidence. Do not run `entire enable`, query paid accounts, or publish a DevRelay session.
- Later process change, requested on 2026-10-04: keep `docs/HANDOFF.md` as the untouched locked plan. Track progress in public `docs/HANDOFF2.md`. Use one branch per phase and one one-line commit per step.
- Product behavior changed: no
- Cost changed: no

### Observed toolchain

| Tool | Observed |
|---|---|
| git | 2.53.0 |
| Python on PATH | 3.14.4 at `/usr/bin/python3` |
| Locked Python | 3.13, not installed. `uv` can download CPython 3.13.15. |
| uv | 0.12.5 |
| Node | 22.14.0 |
| npm | 10.9.2 |
| GitHub CLI | 2.46.0, authenticated as `kernelKain` |
| Docker | 29.8.2, present only as the documented deployment fallback |
| Entire CLI | 0.11.3 |
| Hugging Face CLI | absent |
| Render CLI | absent |

Python 3.13 is the locked backend version. The system interpreter is 3.14.4. Installing 3.13.15 with `uv` is deferred until the backend environment is created. That is a toolchain observation, not a version-policy change.

### Access matrix

| Control | Evidence | Status |
|---|---|---|
| Repository | Public `https://github.com/kernelKain/happen`. Remote `origin` is `git@github.com:kernelKain/happen.git`. | Verified |
| Baseline | `main` at `a45880a` (`a45880a2d3b8d80d2265f0403905ae62bb2f2603`), tracking `origin/main`. Message: Initial commit, 2026-10-03 19:25 IST. | Verified |
| Working tree | Only untracked `docs/` before this step. No unrelated code changes. | Verified |
| Branch `build/happen-mvp` | `git branch --list` returned no match. | User action required before implementation |
| GitHub Actions | Actions enabled, all actions allowed, default workflow permission `read`, reviewers cannot be approved by workflows. | Verified |
| Pull requests | None. | Expected |
| `SERPAPI_API_KEY` | Unset in the process environment. No repository `.env`. | Blocked for the SerpApi probe |
| SerpApi balance | Not queried. | Unverified |
| `HF_TOKEN` | Unset. No local Hugging Face token file. | Blocked for gated model download |
| Gemma terms and artifact | Not checked. | Unverified until the Gemma and Render proof |
| Render balance and plan price | No Render CLI and no Render API key in the environment. Dashboard was not opened. | Unverified user-dashboard check |
| Colab T4 | Not checked in this step. | Unverified until the Gemma and Render proof |
| Entire | `entire status` reports not set up. `.entire/` was not created. | User action: `entire enable` |
| CodeRabbit | No `.coderabbit.yaml`, which matches the locked default. The current GitHub token cannot list App installations (HTTP 403). | Time-boxed unverified |
| DevRelay | MLH account is connected with `dev:read:all` and `dev:write:all`. DEV profile `kernelkain` (id 3953019) resolves. No session was saved. | Connection verified |
| Live URL | Not deployed. | Expected |
| Spend | $0. | Verified |

### HANDOFF and repository

Git matches the locked baseline: branch `main`, commit `a45880a`, public remote, no execution branch, no deployment. `docs/HANDOFF.md` remains the uncommitted planning artifact and is now ignored.

Entire CLI 0.11.3 is installed and the GitHub login is active. The repository is not enabled yet. Before the next phase, run `entire enable` from the repository root, then `entire status`. Checkpoints appear on the next push. The walking-skeleton phase is not complete. The next step is the health and metadata API.

### Verification

- `git status`, `git branch -vv`, `git log`, and `git remote -v` match the matrix.
- `gh repo` metadata: `visibility=public`, `default_branch=main`.
- `gh api repos/kernelKain/happen/actions/permissions` and workflow-permission endpoints match the matrix.
- `entire status` printed `not set up`.
- DevRelay `mlh_connection_status` reported connected, and `get_authenticated_user` returned DEV user `kernelkain`.
- No secret value was printed or written.

### Blockers carried forward

1. `SERPAPI_API_KEY` is set locally. Resolved on October 4, 2026.
2. No `HF_TOKEN` is required for the public GGUF. A free read token is needed only if a later download of official `google/gemma-3-270m-it` weights is rejected as restricted.
3. Render balance is $50.00. Backend list prices are $25/month for `1c-2g` and $85/month for `2c-4g`, drawn from those credits while a service is running. The free 512 MB web service is too small for the measured model.
4. Branch `prove-access` existed locally for the access proofs. The walking-skeleton branch is created for the scaffold.
5. Run `entire enable` when ready. This does not block the scaffold.
6. CodeRabbit installation is still unverified. This does not block the scaffold.

## Prove SerpApi evidence shape

- Date: 2026-10-04
- Result: the Indiranagar restaurant query is viable
- Product behavior changed: no
- Cost changed: yes, 5 SerpApi searches, still inside the free plan

### Evidence

- Account before the probe: Free Plan, 250 searches left, 0 used this month.
- Account after the probe: 245 searches left, 5 used this month.
- The hourly counter read 4. The monthly counter is the budget figure.
- Search `restaurants in Indiranagar, Bengaluru` returned HTTP 200, provider status Success, and 20 local results in 2.068 seconds.
- Place details succeeded for Bombay Brasserie, Chianti Indiranagar, and Truffles Indiranagar. Each has a 7-day hours list.
- Popular times were missing for Bombay Brasserie and present for Chianti (126 points) and Truffles (133 points).
- The Chianti reviews call returned 5 snippets, 5 dates, and 5 links in 1.189 seconds. Snippet lengths were 889, 366, 1217, 815, and 1059 characters.
- No API key, phone number, reviewer name, or raw payload was written into the repository.

### Decision

Keep `restaurants in Indiranagar, Bengaluru` as the canonical discovery query. Do not add a cuisine filter. Treat missing popular times as unknown evidence.

## Prove Gemma and Render feasibility

- Date: 2026-10-04
- Result: local untuned Gemma runs with no token and no model-API fee
- Product behavior changed: no
- Cost changed: no money spent. Render prices were checked against the existing $50 credits.

### Evidence

- `google/gemma-3-270m-it` is gated. An anonymous download returned HTTP 401. The user accepted the terms in the browser. That acceptance does not authorize this machine without a token.
- `bartowski/google_gemma-3-270m-it-GGUF` is public. `google_gemma-3-270m-it-Q4_K_M.gguf` downloaded with no token.
- Size: 253,115,168 bytes. SHA-256: `c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800`.
- The file is in `/tmp/happen-models/` and is not in git.
- Python 3.13.15 and `llama-cpp-python==0.3.36` imported after a source build. PyPI published no wheel for 0.3.36. Native build is the selected path. Docker remains the fallback if Render cannot compile it.
- Load time: 0.525 seconds. RSS after load: 356.7 MB. RSS after generation: 371.8 MB.
- Two temperature-0 prompts returned JSON in 2.337 and 2.923 seconds. Exact-span validation rejected every quoted span. The untuned model is usable only behind that validator.
- Render static sites are free. Free web services have 512 MB and spin down after 15 idle minutes. The model does not fit that plan safely.
- Web service list prices checked on October 4, 2026: `1c-2g` is $25/month and `2c-4g` is $85/month. $50 of credits covers roughly 60 days or 18 days of continuous uptime. Suspend after judging.

### Decision

Operate on the local quantized 270M model. Do not call a hosted model API. Do not generate a Hugging Face token unless an official-weight download is rejected as restricted. Keep the backend off the free 512 MB plan. Prefer `1c-2g` at deploy time because the measured memory fits, and move to `2c-4g` only if a live timing run misses the 30-second limit.

## Scaffold the locked monorepo

- Date: 2026-10-04
- Result: backend import and frontend production build succeed
- Product behavior changed: no
- Cost changed: no

### Evidence

- `uv sync --project backend` installed the locked packages on Python 3.13.15, including `llama-cpp-python==0.3.36`.
- `import happen_api` prints `0.1.0`. `llama_cpp.__version__` is `0.3.36`.
- `ruff check` passed for `backend/src` and `scripts/download-model.py`.
- `npm run build` passed with Vite 8.3.2 after adding the React type packages.
- `python scripts/download-model.py` printed `checksum-ok google_gemma-3-270m-it-Q4_K_M.gguf`.
- Direct Python dependencies are MIT, BSD-3-Clause, or Apache-2.0. The added `@types/react` and `@types/react-dom` packages are MIT.

### Decision

Add `@types/react==19.3.0` and `@types/react-dom==19.3.0` because `react==19.3.0` publishes JavaScript without TypeScript declarations. No locked runtime version changed.

## Build health, metadata, and safe config

- Date: 2026-10-04
- Queue step: P1.2
- Result: health and metadata contracts pass locally. The model is not loaded.
- Product behavior changed: the API can report degraded readiness and the canonical preset. It cannot recommend a restaurant yet.
- Cost changed: no

### Evidence

- `uv run ruff check src tests` passed.
- `uv run pytest` passed, 19 tests.
- A TestClient call to `/healthz` returned HTTP 200 in under one second with `degraded` / `not_loaded`.
- Importing the app did not import `llama_cpp`.
- The local `.env` contains only `SERPAPI_API_KEY`. Startup succeeds because non-secret fields use the example defaults and the model manifest.
- No secret value was printed or written.

### Decisions

- API contract version is `1.0.0`. Scoring policy version is `v1`.
- The only neighbourhood is `indiranagar`, the only category is `restaurants`, and the only experience is `easier_conversation`. The canonical arrival range is 18:00–21:00 in `Asia/Kolkata`, with priorities `conversation`, `short_wait`, `seating`.
- Health stays `degraded` until both the model and the fixture are ready. HTTP status remains 200 so a missing model does not restart the process.
- Unknown paths use error code `NOT_FOUND`. That code is not in the original stable list; the envelope shape is unchanged.
- Interactive API docs are disabled so only `/healthz` and `/api/v1/meta` are public routes.
- `HAPPEN_LIVE_ENABLED` defaults to false. A configured key does not by itself mark live mode available.

## Build the frontend shell

- Date: 2026-10-04
- Queue step: P1.3
- Result: the planner shell renders the service preset and its failure states. No recommendation is invented.
- Product behavior changed: the page now collects the evening request and explains when submission is unavailable.
- Cost changed: no

### Evidence

- `npm test` passed, 3 tests.
- `npm run build` passed.
- `npx playwright test` passed, 5 tests. Horizontal overflow was 0 at 1280×720 and 390×844. Axe reported no serious or critical violations on the initial and service-error states.
- Against the local API, the page showed Indiranagar, keyboard restore returned 18:00, and the browser console had no errors.
- Measured contrast for text, muted text, the amber action, and the repository link is above 4.5:1.
- The production bundle does not contain `SERPAPI`, `HF_TOKEN`, or `api_key`.

### Decisions

- The frontend accepts contract major `1`. Metadata loading retries once after one second.
- When `VITE_API_BASE_URL` is unset, the app calls same-origin `/api/v1/meta`. Vite proxies that path to `http://127.0.0.1:8000` in dev and preview.
- Find the moment stays disabled until `model_status` is `ready`. The current API reports `not_loaded`.
- No decorative motion was added.

## Establish CI and first public deployment

- Date: 2026-10-04
- Queue step: P1.4
- Result: CI and the Render blueprint are written and checked locally. Nothing is deployed.
- Product behavior changed: no
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src`, `backend/tests`, and `scripts/scan-secrets.py`.
- `uv run pytest` passed, 21 tests.
- `npm run check`, `npm test` (3 tests), `npm run build`, and `npx playwright test` (5 tests) passed.
- `python3 scripts/scan-secrets.py` passed on tracked files and on `frontend/dist`. Output is a path plus a rule name.
- `render.yaml` parses. The API service imports `happen_api.main:app`.
- GitHub Actions has not run. No Render service was created.

### Decisions

- Backend plan is `1c-2g` in Singapore. Measured RSS after generation was 371.8 MB, under 80% of 2 GB. Move to `2c-4g` only if a live timing run misses 30 seconds. The static site has no region; Render rejected `region` on a static site.
- Both services track `walking-skeleton` and use `autoDeployTrigger: checksPass`. Point them at `main` after this branch merges.
- The first build does not download the model. Health stays HTTP 200 and `degraded`.
- `HAPPEN_LIVE_ENABLED` is false. `SERPAPI_API_KEY` is dashboard-only. `HF_TOKEN` is omitted because this model file is public.
- CORS and `VITE_API_BASE_URL` reference the other service's `RENDER_EXTERNAL_URL`. No wildcard and no content-security-policy header until the real hosts exist.
- The Hook characterization test is not part of this tree. The backend job runs the full pytest suite, so the test joins CI when it is added. Browser tests stay out of this workflow.

## Domain contracts and scoring

- Date: 2026-10-04
- Queue step: P2.1
- Result: hours, windows, temporal mapping, and scoring policy v1 pass locally. No recommendation endpoint yet.
- Product behavior changed: the backend can score normalized evidence. The page still cannot request a recommendation.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src` and `backend/tests`.
- `uv run pytest` passed, 51 tests, including repeated identical decisions and the locked label boundaries.
- No threshold was relaxed. No secret was printed.

### Decisions

- Evening bands use the window start in `Asia/Kolkata`: early 17:00–19:00, mid 19:00–21:00, late 21:00–23:00. Saturday and Sunday are the weekend.
- A verified window exists only when the full 30 minutes sit inside both the request and a verified opening interval. Closed, missing, unparseable, and contradictory hours produce no verified window.
- Short wait keeps the ordinary weights when one source is missing: popularity 0.60, wait reviews 0.40. Fit always divides by six.
- Confidence uses the locked weights. Coverage counts a priority only when applicable evidence exists, and short wait counts only the sources that are present. Temporal specificity, quality, agreement, and freshness are means over applicable evidence. No applicable evidence scores confidence 0 and the fit label unknown.
- A recommendation requires two supported candidates. A third unsupported candidate stays a partial result. Selection order is fit, confidence, first-priority dimension, earlier arrival, then normalized name.
- `docs/HANDOFF.md` stays the locked plan. Progress for this step is recorded here and in `docs/HANDOFF2.md`.

## Fixture schema and adapter

- Date: 2026-10-04
- Queue step: P2.2
- Result: a labeled synthetic Indiranagar dinner fixture loads through a checksummed adapter. Missing, checksum, and schema failures use different error codes.
- Product behavior changed: the backend can load fictional normalized places. The page still cannot request a recommendation, and metadata does not call this file a captured fixture.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src` and `backend/tests`.
- `uv run pytest` passed, 60 tests.
- `python3 scripts/scan-secrets.py` passed.
- The installed scenario checksum is `e5168468129b4e2a8acf76db1014c7778cc4ee3a8985c0d520fe87265bcc2ad6`.

### Decisions

- The development fixture uses `data_label=synthetic_development`. It is not `live` and not a verified SerpApi capture. Excerpts start with `Synthetic note:`.
- The loader returns normalized places, hours, busyness, and excerpts. It does not store a winning window. Runtime scoring still has to calculate the result.
- A checksum or schema failure stops the load. Evidence older than seven days still loads with `stale=true`.
- `/api/v1/meta` keeps `fixture_available=false` until a recommendation response can show this label. Reporting it as a captured fixture on the current page would be inaccurate.

## Gemma extraction and validation

- Date: 2026-10-04
- Queue step: P2.3
- Result: the validator keeps exact spans and drops the rest. One local extraction of the synthetic north-gallery excerpt was partially accepted on attempt 1, with 0 signals, 2 rejected signals, and all three dimensions unknown.
- Product behavior changed: extraction can run in-process when called. The page and health endpoint still report the model as not loaded.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src` and `backend/tests`.
- `uv run pytest` passed, 68 tests, including the local extraction test.
- `python3 scripts/scan-secrets.py` passed.
- The real run did not put a quoted span into scoring. Raw model text was not copied here.

### Decisions

- One markdown fence is stripped, and integer schema version 1 is read as `"1"`. A signal that fails the schema is dropped. A missing dimension becomes unknown. A non-list or more than six signals makes the document malformed.
- A malformed document gets one retry. A parsed document, including an all-unknown result, does not.
- The model loads on first extraction, after a checksum check, and is not loaded at health startup. `fixture_available` stays false.
- The real extraction used the synthetic fixture excerpt. Untuned 270M output stayed behind the validator.

## Fixture recommendation API

- Date: 2026-10-04
- Queue step: P2.4
- Result: `POST /api/v1/demo-recommendations` returns three timelines. Accepted evidence selects one moment and a different-restaurant fallback. An all-unknown extraction returns insufficient evidence and no winner.
- Product behavior changed: the fixture endpoint scores in process. The page still leaves Find the moment off, and metadata still reports the fixture as unavailable.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src` and `backend/tests`.
- `uv run pytest` passed, 77 tests.
- `python3 scripts/scan-secrets.py` passed.
- The characterization test uses exact quoted spans and does not load the model. The installed fixture with no accepted review evidence does not invent a recommendation.

### Decisions

- Provenance mode is `captured_fixture`. The response also carries `data_label=synthetic_development` and the planning disclaimer, because this file is not a SerpApi capture.
- `/api/v1/meta` keeps `fixture_available=false`, so the current page does not describe the synthetic file as captured evidence.
- A completed identical idempotency key replays the decision with a new request id and generation time. A different payload for that key returns `IDEMPOTENCY_CONFLICT`. Errors are not stored as successes.
- The rolling recommendation limit defaults to 30 requests per 60 seconds, with at most three active recommendations. Health checks are not counted.
- The model still loads only when an extraction has no scripted substitute. A missing model file returns `MODEL_UNAVAILABLE` without importing the runtime.

## Planner, matrix, and evidence UI

- Date: 2026-10-04
- Queue step: P2.5
- Result: the result screen renders three timelines, one recommended moment, a fallback at another restaurant, separate fit and confidence labels, provenance, and accepted evidence.
- Product behavior changed: `/?layout=sample` shows that labeled screen. The normal page still has an empty matrix, and Find the moment stays off.
- Cost changed: no

### Evidence

- `npm run check` passed.
- `npm test` passed, 4 tests.
- `npm run test:shell` passed, 8 tests. The result check covers 1280×720 and 390×844, opens the evidence panel, and confirms the ordinary page does not show the sample restaurants.
- The local preview at `http://127.0.0.1:4173/?layout=sample` showed Courtyard Lantern as Recommended with fit Strong and confidence High, North Gallery Supper as Fallback, and Platform Seats as the third timeline. Why this moment opened the quoted spans and source links.

### Decisions

- The sample is explicitly labeled as a layout. It uses the synthetic fixture names and quoted notes. It is not stored as a scored winner.
- Find the moment is still not connected to the fixture endpoint. That connection is the next step.
- The reveal is immediate. No staggered motion was added.

## Fixture Hook proof

- Date: 2026-10-04
- Queue step: P2.6
- Result: Find the moment scores the synthetic fixture. A mocked contract response shows one recommended moment and a different-restaurant fallback. A real local submit returns three timelines and no winner.
- Product behavior changed: the button works while the model status is not loaded. The badge says Synthetic fixture. `fixture_available` stays false.
- Cost changed: no

### Evidence

- `npm run check` passed through Biome. `npm test` passed, 6 tests. `npm run build` passed.
- `npm run test:shell` passed, 11 tests. The new journey covers keyboard submit, gathering, the mocked winner, insufficient evidence, a 503 with preserved inputs, and a retry that uses a new idempotency key.
- One uncached `POST /api/v1/demo-recommendations` for the Indiranagar preset returned HTTP 200 in 13.9 seconds with `outcome=insufficient_evidence`, three candidates, `recommendation=null`, `evidence=0`, and `rejected_evidence_count=6`.
- Chromium against `http://127.0.0.1:5173/` submitted that preset, showed North Gallery Supper, Courtyard Lantern, and Platform Seats, showed “No moment selected,” opened evidence with no accepted quotes, and Start over restored the empty matrix. The request went to `/api/v1/demo-recommendations`.

### Decisions

- The page enables submission when the service contract matches. The model loads on the first extraction, so a not-loaded status does not keep the button off.
- The winner characterization is a mocked response. The installed model is not replaced with precomputed spans.
- The client timeout is 30 seconds. The measured cold request finished in 13.9 seconds.

## Bounded SerpApi client

- Date: 2026-10-04
- Queue step: P3.1
- Result: Search, place, and review calls are implemented behind fake HTTP. No live SerpApi request was sent.
- Product behavior changed: no. The page still uses the synthetic fixture.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed for `backend/src/happen_api/providers` and `backend/tests/unit/test_serpapi_client.py`.
- `uv run pytest` passed, 97 tests.
- `python3 scripts/scan-secrets.py --extra backend/src/happen_api/providers --extra backend/tests/unit/test_serpapi_client.py` reported nothing.

### Decisions

- One client instance is one recommendation, with a 7-attempt credit budget and a 14-second shared deadline.
- HTTP 429 is not retried. Monthly quota language disables later calls on that client. A 429 without that language stays transient and does not disable live mode.
- Provider phone numbers and review identities stay in the redacted payload until normalization. Credential fields and echoed key values are removed now.
- Progress stays in this log and `docs/HANDOFF2.md`. `docs/HANDOFF.md` stays the locked plan.

## Candidate normalization

- Date: 2026-10-04
- Queue step: P3.2
- Result: Provider documents normalize into three place records, or an insufficiency result with reason codes. No live SerpApi request was sent.
- Product behavior changed: no. The page still uses the synthetic fixture.
- Cost changed: no

### Evidence

- `uv run ruff format` and `uv run ruff check` passed for the normalizer and its tests.
- `uv run pytest` passed, 102 tests.
- `python3 scripts/scan-secrets.py --extra backend/src/happen_api/providers/serpapi/normalizer.py --extra backend/tests/unit/test_serpapi_normalizer.py` reported nothing.

### Decisions

- A type must contain “restaurant”. Cafes and unlabeled places are rejected instead of being relabeled.
- The provenance URL is a supplied Google Maps URL. If the provider omits one, Happen builds the Maps search URL from a safe `place_id`.
- Closure on the visit date rejects the place. Missing hours, busyness, or reviews do not.
- Place-detail calls restrict selection to the rows those details match.
- Reviewer names, phones, live busyness, and out-of-range popularity values are not copied. Excerpts stop at three and at 400 characters.

## Live orchestration

- Date: 2026-10-04
- Queue step: P3.3
- Result: `POST /api/v1/recommendations` scores live evidence or returns an explicit error. A failure does not load the fixture. No live SerpApi request was sent.
- Product behavior changed: the live route exists. The page still calls the demo endpoint.
- Cost changed: no

### Evidence

- `uv run ruff format --check` and `uv run ruff check` passed.
- `uv run pytest` passed, 113 tests.
- `python3 scripts/scan-secrets.py` reported nothing for the live route, guard, orchestration, and contract tests.

### Decisions

- Live provenance is `live` / `live` / fixture version `none`, with the planning disclaimer. It is not labeled synthetic.
- Fewer than three candidates is HTTP 200 `insufficient_evidence`. An unreadable search is HTTP 502. Auth and quota disable later live calls. Transient failures use the circuit.
- The process search budget defaults to 42. Each recommendation still takes at most 7 attempts and 14 provider seconds inside the 28-second server deadline.
- The snapshot cache stores normalized evidence for 15 minutes. Raw provider documents are not cached.
- `fixture_available` stays false. The demo route remains the only fixture path.

