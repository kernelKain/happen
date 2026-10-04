# Happen execution notes

This is the running notebook for the build. A new chat must read this file before doing anything else.

`docs/HANDOFF.md` is the locked plan from Prompt 1. Do not edit it to track progress. When this file and `HANDOFF.md` disagree about what has been done, believe this file plus the git history. When they disagree about the product, believe `HANDOFF.md`.

## Resume for the next chat

Find the moment still scores the synthetic fixture. A real submit returns three timelines and no winner, because the installed model kept no review spans. The labeled winner layout remains at `/?layout=sample`. `POST /api/v1/recommendations` can score live evidence, and a provider failure stays an error instead of loading the fixture. The page still calls the demo endpoint. No live search was spent. The public Render URL is still missing.

`docs/HANDOFF.md` section 27 still says the build has not started. That section is the locked planning snapshot. This file is the progress log.

| | |
|---|---|
| Current phase | Live sponsor Hook |
| Phase complete | No |
| Last finished step | Assemble live orchestration and protections |
| Next step | Capture and verify canonical fixture |
| Branch | `live-sponsor` |
| Pull request | https://github.com/kernelKain/happen/pull/5 merged the fixture Hook into `main` at `b5cf7da`. This branch has no pull request yet. |
| Remote | `origin/main` is at `b5cf7da`. This branch adds the SerpApi client, the candidate normalizer, and the live recommendation route. |
| Live URL | Not deployed |

Still open from the walking skeleton, and not a blocker for local scoring:

1. Create the Render services from `render.yaml`, then paste the frontend URL and the health URL back here.
2. Let CodeRabbit finish on the merged walking-skeleton pull request before the next phase pull request.

## Working rules for every later chat

- Branch names, commit messages, and code comments do not use phase or step numbers.
- Each step gets one short commit message that says what the change does. Do not name the coding tool.
- One branch per phase: `walking-skeleton`, then `fixture-hook`, `live-sponsor`, `demo-experience`, `harden-freeze`, `production`, `submission`, and `submit`.
- After each phase pull request, wait for the CodeRabbit review. Before the next phase, fetch and pull the latest remote branch so review edits are included.
- Before the next phase, also stop so the app can be tested by hand. Give the exact frontend and backend commands for what exists at that moment.
- Do not push, merge, deploy, or publish unless asked.
- Keep secrets out of git, notes, and logs.

## How to run what exists today

The page can be opened. The API serves health, metadata, and `POST /api/v1/demo-recommendations`. Metadata still reports the fixture as unavailable and the model as not loaded. **Find the moment** is still available: it scores the labeled synthetic fixture, and the model loads on the first request. A real submit currently returns three timelines and no winner. The labeled winner layout is at `http://127.0.0.1:5173/?layout=sample` while the dev server is running. That sample is not a scored visit.

Frontend, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the local address Vite prints, usually `http://127.0.0.1:5173`. With the API running, the page shows the Indiranagar planner and **Find the moment** scores the synthetic fixture. Stop it with Ctrl+C.

Backend, from the repository root:

```bash
cd backend
uv sync
uv run uvicorn happen_api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/api/v1/meta`. Health returns HTTP 200 with `status` `degraded` because the model is not loaded and no fixture is installed. Metadata lists the Indiranagar preset. Neither response includes a secret. Stop the server with Ctrl+C.

Checks:

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
```

## Entire

The CLI is already installed and the GitHub login is already active. This repository is not enabled yet. Do this before the next phase, from the repository root:

```bash
entire enable
entire status
```

If the CLI were missing on another machine, the full sequence is:

```bash
curl -fsSL https://entire.io/install.sh | bash
entire login
entire enable
```

Then keep working as usual. The first checkpoint appears when the repository is pushed after `entire enable`. Commit `.entire/settings.json` if Entire generates it. Do not commit `.entire/settings.local.json`. Do not paste tokens into chat.

Deadline: October 5, 2026 at 06:59 UTC (12:29 PM IST). Feature freeze is build hour 19 of 24. Spend cap: $0 out of pocket. Existing free credits may be used.

## Right now

| | |
|---|---|
| Status | Find the moment scores the synthetic fixture. The live recommendation route is tested with a fake provider and is not wired to the page. The public URL is still not deployed. |
| Last finished step | Assemble live orchestration and protections |
| Next step | Capture and verify canonical fixture |
| Branch | `live-sponsor` |
| Live URL | Not deployed |
| Spend | $0 |
| Biggest blocker | Render services are still not created. Local SerpApi client work can continue without them. |

## How branches and commits work

You asked for this on October 4, 2026. It replaces the earlier single-branch, no-commit rule for the coding agent.

- One branch per phase, created when that phase starts. Branch names do not use phase or step numbers.
- One commit per step. The message is one short sentence that says what the change does. Do not name the coding tool, and do not use phase or step numbers.
- After a branch has a pull request, wait for the CodeRabbit review and any changes it pushes. Before the next phase, fetch and pull that updated branch, and let the app be tested by hand.
- `docs/HANDOFF.md` and `docs/HANDOFF2.md` stay in git so the process is public.
- Secrets, `.env`, model binaries, and raw provider payloads stay ignored.
- Cursor does not push, merge, deploy, or publish unless you explicitly ask.

| Phase | Branch | When it is created |
|---|---|---|
| Prove access | `prove-access` | Created when access checks started |
| Walking skeleton | `walking-skeleton` | Created for the scaffold |
| Fixture Hook | `fixture-hook` | Created when fixture work starts |
| Live sponsor Hook | `live-sponsor` | Created when live sponsor work starts |
| Demo experience | `demo-experience` | Created when the demo polish starts |
| Harden and freeze | `harden-freeze` | Created when hardening starts |
| Production release | `production` | Created when production work starts |
| Submission evidence | `submission` | Created when submission writing starts |
| Submit and buffer | `submit` | Created when the final submit work starts |

## What you do versus what Cursor does

Cursor edits the repo, runs local checks, and updates this file. You handle accounts, secrets, dashboards, a real friend walkthrough, and any public publish or challenge submit. Never paste a secret into chat. Put keys in a local ignored `.env` file or in the host's secret settings.

---

## Prove access and feasibility

Branch: `prove-access`

Goal: measure SerpApi coverage, Gemma inference, and Render cost before building the app. Planned budget: 90 minutes. Done when every architecture-critical assumption has a measured result.

### Verify accounts and workflow controls

Status: **Done** on October 4, 2026.

Cursor checked the public repo, toolchain, GitHub Actions, Entire, CodeRabbit, and DevRelay. No secret values were printed. Evidence is in `docs/BUILD_LOG.md`.

What is true now:

- Repo `kernelKain/happen` is public on `main` at `a45880a`.
- Python on PATH is 3.14.4. The locked backend is Python 3.13, which `uv` can install as 3.13.15 when the backend environment is created.
- Node 22.14.0, npm 10.9.2, uv 0.12.5, Entire CLI 0.11.3, Docker 29.8.2.
- GitHub Actions is enabled. Workflows have read permission.
- Entire is installed and not enabled. No `.entire/` directory was created.
- CodeRabbit has no config file, which matches the plan. The GitHub token cannot list installed Apps.
- DevRelay is connected to DEV user `kernelkain`. No session was published.
- `SERPAPI_API_KEY` and `HF_TOKEN` were unset. Render CLI is not installed, so the credit balance was not read.

Commit: `Record account and workflow access checks.`

Your side, still open from this step:

1. From the repository root, run `entire enable`, then `entire status`. The CLI is already installed and the GitHub login is already active. Commit `.entire/settings.json` if it is generated. Leave `.entire/settings.local.json` untracked.
2. Install the CodeRabbit GitHub App on `kernelKain/happen` if it is not already installed. After each phase pull request, let that review finish. Pull the remote branch, and test the app locally, before the next phase starts.
3. Done: `SERPAPI_API_KEY` is set in the ignored `.env`. It was not printed or committed.

### Prove SerpApi evidence shape

Status: **Done** on October 4, 2026.

The key worked. No raw provider payload was committed. Phone numbers and review text were not written down.

Account after the probe:

- Plan: Free Plan, 250 searches per month.
- Used by this probe: 5.
- Remaining: 245.
- That is enough for the planned budget. Live mode stays on.

Working query, and the one to keep:

- `engine=google_maps`
- `type=search`
- `q=restaurants in Indiranagar, Bengaluru`
- `hl=en`
- `gl=in`

The search returned 20 places in about 2.1 seconds. No second category was needed.

Place details for the first three results:

| Place | Hours | Popular times | Reviews on the place |
|---|---|---|---|
| Bombay Brasserie | 7 days | Missing | 9,859 |
| Chianti, Indiranagar | 7 days | 7 days, 126 points | 8,694 |
| Truffles - Indiranagar | 7 days | 7 days, 133 points | 21,018 |

Hours come back as a list of seven day entries. Popular times are not on every place. Chianti and Truffles both have a full week, so two candidates already have comparable time evidence. Bombay Brasserie is the missing-busyness case the product must keep as unknown, not as a good sign.

A separate reviews call for Chianti returned 5 excerpts. All 5 had text, a date, and a link. The longest excerpt was 1,217 characters, so later capture must keep only a short quote. Reviewer names were not saved.

Place results also include a `user_reviews` field. The live adapter should use that when it already has enough excerpts, and call the reviews endpoint only when it does not.

Commit: `Record the Indiranagar restaurant evidence probe.`

Your side after this step:

1. Nothing else is required for SerpApi. The remaining 245 searches still match the plan.
2. Do not paste the key anywhere, and do not commit `.env`.

### Prove Gemma and Render feasibility

Status: **Done** on October 4, 2026.

You accepted the Gemma terms. The model page did not ask for a token, and none is needed to run the demo.

What is free:

- Running Gemma on our own server does not send reviews to a paid model API and does not create a Google bill.
- The public quantized file downloaded with no account token. It is a 241.3 MB `Q4_K_M` GGUF of `google/gemma-3-270m-it` from `bartowski/google_gemma-3-270m-it-GGUF`.
- SHA-256: `c866c9f113f2e9aa2225c5997ede437392b8fa844ba5db9e4c77e315ffe20800`. The file stays outside git.
- SerpApi remains on the free plan, with 245 searches left.
- The Render static site is $0. The $50 credit balance is already in the account.

What is not free if left running:

- The measured process used 372 MB after loading the model. Render’s $0 web service has only 512 MB, which is too small once the API is added.
- A backend with 1 CPU and 2 GB of RAM is listed at $25 per month. Two CPUs and 4 GB are listed at $85 per month. Render draws that from the $50 credits only while the service is on.
- $50 covers about 60 days of the smaller plan, or about 18 days of the larger plan, if the service stays on all day. Through the October 5 deadline, either plan is a few dollars of credits, not a new card charge, if you suspend it afterward.
- Do not buy Colab compute, a Hugging Face inference endpoint, or a larger Render plan.

Measured runtime on this machine:

- Python 3.13.15 and `llama-cpp-python` 0.3.36 built from source. PyPI has no prebuilt wheel, so the Render build must have a compiler. Docker stays the fallback only if that native build fails on Render.
- Model load: 0.5 seconds. One extraction: 2.3 to 2.9 seconds. Memory: 372 MB.
- Both replies were JSON. The exact-span check rejected every quote because the small model did not copy the review. That is a quality gap for later tuning or a stricter decoder. It is not a reason to switch to a paid model.

A Hugging Face token is still not required. Create a free read token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens) only if a later Colab download of the official `google/gemma-3-270m-it` weights says the model is restricted. Accepting the terms in the browser does not by itself authorize a script. Creating the token does not start billing. Do not paste it into chat.

Commit: `Record the free Gemma runtime proof and Render credit limit.`

Your side after this step:

1. Nothing else is required before the app scaffold.
2. Before the first Render service exists, set the workspace spend limit so usage cannot charge a card after the $50 credits. Do not add a payment method if Render lets you skip it.
3. After judging, suspend the paid web service. The static site can stay.
4. Skip Colab for now. Tuning stays optional and only on a free T4.

---

## Public walking skeleton

Branch: `walking-skeleton`, created from the access-proof branch.

Goal: a public HTTPS frontend and a health/metadata API. Planned budget: hours 1.5–4.

### Scaffold the locked monorepo

Status: **Done** on October 4, 2026.

The installable backend and the production frontend build both succeed. Python is 3.13.15. Empty feature folders were not created.

What exists now:

- `backend/` installs the locked API packages, including `llama-cpp-python` 0.3.36. `import happen_api` works. Ruff reports no issues in the new Python files.
- `frontend/` builds with Vite 8.3.2, React 19.3.0, and TypeScript 7.0.2. The page currently shows the name and tagline only. The planner screen is the next UI step.
- React 19.3.0 does not ship TypeScript declarations. `@types/react` 19.3.0 and `@types/react-dom` 19.3.0 were added. Both are MIT. No other package moved off the locked versions.
- `ml/model-manifest.json` records the public Q4_K_M file and its checksum. `python scripts/download-model.py` prints `checksum-ok` for the local copy. The model file stays ignored.
- `.env.example` has empty secrets and the public model checksum. `AGENTS.md` points agents at the locked plan.

Commit: `Scaffold the backend, frontend, and model manifest.`

Your side after this step: nothing. Do not create a Render service yet.

### Build health, metadata, and safe config

Status: **Done** on October 4, 2026. Not committed. Autonomy for this chat is A1, so the change is only in the working tree on `walking-skeleton`.

The API process starts from the existing `.env`, which only needs `SERPAPI_API_KEY`. Other settings use the development defaults from `.env.example`. Model identity and checksum come from `ml/model-manifest.json`. The model file is not opened.

What exists now:

- `GET /healthz` returns HTTP 200 in under one second with `status=degraded`, `model_status=not_loaded`, and `fixture_status=unavailable`.
- `GET /api/v1/meta` returns contract `1.0.0`, the Indiranagar dinner preset, scoring policy `v1`, and `live_available=false` until live mode is explicitly enabled.
- Production CORS rejects wildcards and local origins. Development allows only `localhost` and `127.0.0.1`.
- Errors use the public envelope. A body over 16 KB returns `REQUEST_TOO_LARGE`. Unexpected failures return `INTERNAL_ERROR` without a stack trace, path, or secret.
- Invalid configuration raises `ConfigError` and the message does not include secret values.

Commit when you ask: one short sentence for this step. Do not push unless you ask.

Your side after this step: nothing. The frontend shell is next.

### Build the frontend shell

Status: **Done** on October 4, 2026. Not committed.

The dark planner loads `/api/v1/meta`, shows the Indiranagar preset, and does not invent a recommendation. **Find the moment** stays off while the model is not ready. A failed metadata request keeps the page and offers Retry. A contract major other than `1` disables submission and asks for a refresh.

Checks that passed:

- `npm test` — 3 unit tests.
- `npm run build` — TypeScript and the Vite production build.
- `npx playwright test` — 5 shell tests, including 1280×720 and 390×844 with no horizontal overflow, plus axe on the initial and service-error states.
- A live browser run against the local API showed Indiranagar, restored the preset from the keyboard, and reported no console errors.

Your side after this step: optional. Open `http://127.0.0.1:5173` with the API running and say if the first screen is unclear.

### Establish CI and first public deployment

Status: **Ready for you** on October 4, 2026. Not committed. Not deployed.

GitHub Actions and `render.yaml` are in the working tree. The same checks CI runs passed locally. GitHub has not run the workflow, and no Render service exists yet.

The workflow installs the locked backend and frontend, checks formatting, runs the backend tests and frontend unit tests, builds the frontend, and scans tracked files and `frontend/dist` for credential material. It prints a path and a rule name, never a secret value. Browser tests stay local. The Hook characterization test is not in the tree yet; the backend test job will run it when it arrives.

`render.yaml` defines a free static site, `happen-web`, and one Python web service, `happen-api`, on `1c-2g` in Singapore. The static site has no region because Render serves it from its CDN. Both track `walking-skeleton` and deploy only after CI checks pass. The build does not download the model. `HAPPEN_LIVE_ENABLED` is false. Production CORS and `VITE_API_BASE_URL` come from the other service's public HTTPS URL. `SERPAPI_API_KEY` is prompted in the dashboard and is not written in the blueprint.

Checks that passed locally:

- `uv run ruff format --check` and `uv run ruff check` for `backend/src`, `backend/tests`, and `scripts/scan-secrets.py`.
- `uv run pytest` — 21 tests.
- `npm run check`, `npm test` — 3 tests, `npm run build`, and `npx playwright test` — 5 shell tests.
- `python3 scripts/scan-secrets.py` and the same command with `--extra frontend/dist`.
- `render.yaml` parses, and the installed app imports.

Your side after this step:

1. Ask for a commit if you want one, then push `walking-skeleton` and open or update the draft pull request. Wait until the `ci` workflow is green. The first backend run compiles `llama-cpp-python` and can take several minutes.
2. In Render, create a Blueprint from this repo's `render.yaml`. Do not create a second copy by hand.
3. When Render prompts, set `SERPAPI_API_KEY`. Leave `HF_TOKEN` unset. This public model does not need it.
4. After both services are live, open the frontend URL and `https://<api-host>/healthz`. Paste those two URLs back here. Do not paste secret values.
5. Suspend `happen-api` after that smoke check if you are not ready to leave it running. `1c-2g` is $25/month from the existing $50 credits and does not sleep. A later green push can deploy it again and resume billing. The static site is free.

If the API deploy fails because the frontend origin is not ready, set `CORS_ALLOWED_ORIGINS` in the dashboard to the exact `https://` frontend origin and redeploy once. If the native build cannot compile `llama-cpp-python`, stop and say so. Do not keep retrying paid builds. The next coding step waits for those URLs.

---

## Fixture vertical slice

Branch: `fixture-hook`, created when fixture work starts.

Goal: the Hook works locally on a labeled synthetic fixture, through the real extraction and scoring path. Planned budget: hours 4–9.

### Implement domain contracts and scoring

Status: **Done** on October 4, 2026.

Hours parsing, 30-minute windows, temporal multipliers, scoring policy v1, and tie-breaking are in `backend/src/happen_api/domain/`. The same inputs produce the same decision across repeated runs. Missing evidence stays unknown and does not rescale the remaining score. Thresholds are unchanged.

`uv run pytest` passed, 51 tests. Ruff format and lint passed.

Your side after this step: nothing. The public Render URL is still separate.

### Implement fixture schema and adapter

Status: **Done** on October 4, 2026.

The Indiranagar dinner fixture is synthetic and labeled. The loader checks the scenario checksum, rejects a missing file, a checksum mismatch, and an invalid schema with different error codes, and marks evidence older than seven days stale without treating it as live. It does not contain a precomputed winner. Metadata still reports the fixture as unavailable so the page does not call this file a captured SerpApi fixture.

`uv run pytest` passed, 60 tests.

Your side after this step: nothing.

### Implement Gemma extraction and validation

Status: **Done** on October 4, 2026.

The local adapter loads the pinned GGUF, checks its checksum, and validates one excerpt before scoring can see it. Invalid signals are dropped. A malformed document gets one retry. Health still reports the model as not loaded until a later request uses it.

One real run on the synthetic north-gallery excerpt finished as partially accepted on the first attempt: zero signals kept, two signals rejected, and conversation, short wait, and seating all unknown. No quoted span was accepted, so there is nothing to judge as a fair quote. That result does not become a recommendation.

`uv run pytest` passed, 68 tests.

Your side after this step: nothing. The public Render URL is still separate.

### Assemble fixture recommendation API

Status: **Done** on October 4, 2026.

`POST /api/v1/demo-recommendations` loads the synthetic fixture, validates excerpts, scores windows, and returns three timelines. With accepted evidence it selects one moment and a different fallback. With no accepted review evidence it returns insufficient evidence and no winner. The same idempotency key and payload reuse the decision. Metadata still reports the fixture as unavailable, so the current page does not call this file a captured SerpApi fixture.

`uv run pytest` passed, 77 tests.

Your side after this step: nothing. The public Render URL is still separate.

### Build planner, matrix, and evidence UI

Status: **Done** on October 4, 2026.

The result screen shows three restaurant timelines, a recommended moment, a fallback at another restaurant, separate fit and confidence labels, provenance, and an evidence panel. The ordinary page stays empty. The sample layout is labeled and does not claim that Find the moment has scored the visit.

`npm test` passed, 4 tests. `npm run test:shell` passed, 8 tests, including the 1280px and 390px result checks.

Your side after this step:

1. Open `http://127.0.0.1:5173/?layout=sample` at a 1280px-wide window. Start the frontend with `npm run dev` from `frontend/` if it is not already running.
2. Say whether you can tell the primary moment from the fallback without extra explanation.

### Prove the fixture Hook end to end

Status: **Done** on October 4, 2026.

Find the moment posts the planner draft to `POST /api/v1/demo-recommendations` with a new idempotency key. The page shows Gathering evidence, then the returned timelines. Start over clears the result. A failed request keeps the inputs and Retry sends a new key. The badge says Synthetic fixture. Metadata still reports the fixture as unavailable, so the page does not call this file a SerpApi capture.

The automated winner proof uses a mocked contract response: Courtyard Lantern recommended, North Gallery Supper as fallback, Platform Seats as the third timeline. A real local submit on October 4 returned `insufficient_evidence` in 13.9 seconds: three timelines, no winner, no accepted evidence, and six rejected signals. That is the honest result of the installed model.

`npm test` passed, 6 tests. `npm run test:shell` passed, 11 tests. A Chromium pass against the local API and dev server submitted the preset, showed the three restaurants and “No moment selected,” opened evidence with no accepted quotes, and Start over restored the empty matrix.

Your side after this step:

1. The API is on `http://127.0.0.1:8000` and the page is on `http://127.0.0.1:5173`. If either has stopped, start them with the commands above.
2. Load `http://127.0.0.1:5173/` fresh, submit the Indiranagar dinner preset, and confirm three timelines and “No moment selected.” This path does not show a recommended winner.
3. The winner layout is still the labeled sample at `http://127.0.0.1:5173/?layout=sample`.
4. Say what you saw if you try it. The next backend step uses fake HTTP, so this check does not block it.

---

## Live sponsor Hook

Branch: `live-sponsor`, created when live sponsor work starts.

Goal: one real SerpApi run, a sanitized fixture, and a checked Gemma path. Planned budget: hours 9–14.

### Implement bounded SerpApi client

Status: **Done** on October 4, 2026.

The client sends search, place, and review calls to `https://serpapi.com/search.json`. One client is one recommendation: 7 attempts and 14 seconds, with 8 seconds as the cap for a single attempt. Connection failures, timeouts, and HTTP 5xx retry once. Other 4xx responses, including HTTP 429, do not. An authentication failure or a monthly quota error disables later calls on that client. Returned documents, errors, and logs omit the API key. Redirects are not followed.

`uv run pytest` passed, 97 tests. Ruff format and lint passed for the new files. The secret scan reported nothing. No live search was spent.

Your side after this step: nothing. The page is unchanged.

### Normalize and select candidates

Status: **Done** on October 4, 2026.

Search rows become place records only from fields the provider sent. A row needs a name, a usable id, a restaurant type, and a provenance URL. The URL is a supplied Google Maps link, or the Maps search link built from a safe `place_id`. Phone numbers and reviewer names are dropped. Hours use the existing parser. Popular times become visit-day observations. At most three excerpts are kept, each capped at 400 characters. Missing hours, busyness, or reviews stay missing and produce warnings. A place that is closed on the visit date is rejected. Completeness is ranked ahead of search order. The result is three candidates, or no candidates plus reason codes. When place details are supplied, only rows that match those details can be selected.

`uv run pytest` passed, 102 tests. Ruff format and lint passed for the normalizer. The secret scan reported nothing. No live search was spent.

Your side after this step: nothing. Live orchestration is next.

### Assemble live orchestration and protections

Status: **Done** on October 4, 2026.

`POST /api/v1/recommendations` retrieves the allowlisted Indiranagar search, normalizes it, and scores it. The route keeps the existing idempotency key, rate limit, and active-request cap. A shared 28-second deadline covers validation, SerpApi, Gemma, and scoring. The process search budget defaults to 42. Three transient failures inside five minutes open a two-minute circuit, then one probe is allowed. An authentication or quota failure disables later live calls in this process. A snapshot cache keeps normalized evidence for 15 minutes. An empty or incomplete search returns HTTP 200 with `insufficient_evidence`. A provider failure returns the public error envelope with `fixture_available` false. The fixture route is not called from this path. Live responses use mode `live`, data label `live`, fixture version `none`, and the planning disclaimer. The page still calls the demo endpoint.

`uv run pytest` passed, 113 tests. Ruff format and lint passed. The secret scan reported nothing. No live search was spent.

Your side after this step: nothing until the live capture. Reply `ok` before any SerpApi credit is spent.

### Capture and verify canonical fixture

Status: **Not started.**

Cursor runs one bounded live Indiranagar request, removes reviewer identities, writes the sanitized fixture, and checks that replay matches the live decision.

Your side before Cursor spends credits:

1. Reply `ok` to the single live capture. The plan allows up to 14 searches for this capture and the canonical run.

Your side after Cursor finishes:

1. Skim the sanitized fixture for names, keys, or reviewer identities.
2. Say if anything private must be removed before it is committed.

### Evaluate and optionally tune Gemma

Status: **Not started.**

Cursor builds the held-out set, measures the base 270M model, and keeps a tuned adapter only if it is better. If tuning does not improve the locked scores, the untuned model ships.

Your side after Cursor finishes:

1. For the training attempt, open a free Colab T4 notebook from `ml/` and let it run, or say that Colab is unavailable.
2. Read the evaluation numbers. Do not publish a score that is not in the evaluation report.

### Deploy and smoke the sponsor vertical slice

Status: **Not started.**

Cursor prepares the model download and the live/fixture wiring. Deployment itself waits for you.

Your side after Cursor finishes:

1. Deploy or redeploy the backend and frontend on Render.
2. Open the public fixture path in a fresh browser.
3. Allow one bounded live run, then paste the public URL and whether the page showed SerpApi sources, the Gemma version, and live-or-fixture labeling.

---

## Complete demo experience

Branch: `demo-experience`, created when the demo polish starts.

Goal: every visible state, the evidence view, and the 1280px and 390px layouts. Planned budget: hours 14–17.

### Complete all visible result states

Status: **Not started.**

Cursor adds specific copy and a next action for loading, partial, insufficient evidence, timeout, quota, model failure, and fixture mode.

Your side after Cursor finishes: click one error state if a local page is running, and say if the next action is unclear.

### Finish evidence and methodology experience

Status: **Not started.**

Cursor finishes the evidence drawer or an inline panel: exact quotes, source links, conflicts, rejected-span count, and model version.

Your side after Cursor finishes: open evidence from the keyboard only, if the notes say the browser check could not be completed here.

### Finish reveal, responsive, and reduced motion

Status: **Not started.**

Cursor checks 1280×720 and 390×844. Reduced motion shows the result immediately.

Your side after Cursor finishes:

1. Look at the 1280px screenshot or the local window.
2. Say if the recommended moment is obvious. Decorative motion can be removed. The three timelines stay.

### Conduct friend walkthrough

Status: **Not started.**

This step is yours. Cursor only records what you report. It will not invent feedback.

Your side:

1. Ask your friend to plan the Bengaluru dinner from a fresh page. Five minutes is enough.
2. Ask whether fit and confidence felt different, and whether the fallback was clear.
3. Send a short paraphrase. Do not send their name, contact details, or account data.
4. Cursor will adjust only the approved wording.

---

## Harden and freeze

Branch: `harden-freeze`, created when hardening starts.

Goal: required tests are green and the MVP can be merged. Planned budget: hours 17–19. After freeze, new features stop.

### Harden security and failure paths

Status: **Not started.**

Cursor adds the size, CORS, injection, rate, and checksum checks, then scans for secrets.

Your side after Cursor finishes: if a secret is found, rotate it yourself. Cursor will not print the value.

### Meet performance and reliability gates

Status: **Not started.**

Cursor measures three warm fixture runs and three warm live runs against the 2-second and 30-second limits.

Your side after Cursor finishes: if a live timing run needs the deployed service, say when Render is awake so the three runs are not wasted on a cold start.

### Run complete pre-freeze verification

Status: **Not started.**

Cursor runs the backend tests, frontend tests, model eval, browser checks, and the secret scan.

Your side after Cursor finishes: read the pass/fail list. Reply `ok` only if you accept the recorded limitations.

### Resolve review and freeze the MVP

Status: **Not started.**

Cursor fixes required review findings on the branch. You control the merge.

Your side after Cursor finishes:

1. Open the pull request and read CodeRabbit, or the manual checklist if CodeRabbit did not run.
2. Merge the green branch into `main` when you are satisfied.
3. Tell Cursor the merge commit. That moment is feature freeze.

---

## Production release

Branch: `production`, created from the merged `main` revision.

Goal: the public fixture journey works, and one live path is verified or honestly limited. Planned budget: hours 19–20.5.

### Deploy the frozen production revision

Status: **Not started.**

Cursor checks the Render config against the merged revision. You deploy.

Your side after Cursor finishes:

1. Deploy the exact merged commit.
2. Confirm `/healthz` returns HTTP 200 on the public URL.
3. Paste the frontend URL and the backend URL.

### Run final production smoke tests

Status: **Not started.**

Cursor prepares the smoke checklist. The public browser run needs the deployed URL.

Your side after Cursor finishes:

1. Open a fresh browser session and complete the fixture journey.
2. Approve one live run.
3. Tell Cursor if the page showed the wrong mode, a missing source, or a console error.

### Prove rollback and judge runbook

Status: **Not started.**

Cursor writes the judge-day runbook from the behavior that actually shipped: 60-second script, fixture path, live path, and what to do if the public URL fails.

Your side after Cursor finishes:

1. Name the last healthy Render revision you can roll back to.
2. Confirm you have a backup recording, or say that it still needs to be captured with the demo recording.
3. Do not delete services or databases. Nothing destructive is required.

---

## Submission evidence

Branch: `submission`, created when submission writing starts.

Goal: README, media, and a DEV draft that match the measured product. Planned budget: hours 20.5–23.

### Finish README, diagrams, and attribution

Status: **Not started.**

Cursor updates the README, architecture diagram, setup, results, limitations, and attributions so every claim points at a measurement or an official source.

Your side after Cursor finishes: read the README once and mark any sentence that sounds stronger than the evidence.

### Capture hero media and demo

Status: **Not started.**

Cursor captures the hero screenshot and checks that it shows the mode label and no secrets. The 60-second recording uses the production URL.

Your side after Cursor finishes:

1. Watch the recording once.
2. If the live path is unstable, approve a labeled fixture recording instead.
3. Say if the recording shows anything private.

### Curate Entire and DevRelay sessions

Status: **Not started.**

Cursor lists candidate sessions. It does not publish one until you approve that exact session.

Your side after Cursor finishes:

1. Pick the sessions that explain a decision, a bug, or the Gemma evaluation.
2. Reject any session that contains a secret, a local path you dislike, or private feedback.
3. Reply with the ones that may be saved.

### Draft the DEV submission article

Status: **Not started.**

Cursor drafts the official DEV template with `#hf26challenge`, partner use, open-model rationale, and an AI-use disclosure. It stays a draft.

Your side after Cursor finishes:

1. Edit anything that does not sound like you.
2. Do not publish yet. Publishing happens in the final submit step.

### Assemble final submission packet

Status: **Not started.**

Cursor fills the submission checklist with the repo, demo, and draft links.

Your side after Cursor finishes:

1. Open every link in a private window.
2. Say which links fail or which category claims are not proven.
3. Approve the docs branch for merge when the links match.

---

## Submit and buffer

Branch: `submit`, created when the final submit work starts.

Goal: you submit a verified entry before the deadline. Planned budget: the last hour, with a buffer.

### Audit and release the exact submission revision

Status: **Not started.**

Cursor audits links, secrets, the license, and tests. You merge and, if you want, tag the release.

Your side after Cursor finishes:

1. Merge the docs branch into `main`.
2. Say whether you want a git tag. Cursor will not tag unless you ask.
3. Stop if any secret or broken required link remains.

### Publish, submit, and verify

Status: **Not started.**

This step is yours. Cursor records the confirmation. It does not publish or submit unless you give a direct instruction for that action.

Your side:

1. Publish the DEV article.
2. Submit the Hacktoberfest Weekend Challenge entry with the public repo, demo, and article links.
3. Paste the submission confirmation here.
4. Stop. No last-minute features.

---

## Step log

| Step | Status | Commit | Your remaining action |
|---|---|---|---|
| Verify accounts and workflow controls | Done | `Record account and workflow access checks.` | Optional: Entire and CodeRabbit. |
| Prove SerpApi evidence shape | Done | `Record the Indiranagar restaurant evidence probe.` | Nothing else for SerpApi. |
| Prove Gemma and Render feasibility | Done | `Record the free Gemma runtime proof and Render credit limit.` | Before deploy, cap Render spend at the credits and suspend the paid service after judging. No token needed now. |
| Scaffold the locked monorepo | Done | `Scaffold the backend, frontend, and model manifest.` | Nothing. |
| Health, metadata, and safe config | Done, merged | `6b0f3c5` | Nothing. |
| Frontend shell | Done, merged | `6b0f3c5` | Optional: say if the first screen is unclear. |
| CI and first public deployment | Code merged in pull request 4. Public URL still open | `6b0f3c5` | Create the Render services and paste both URLs. |
| Domain contracts and scoring | Done | `Score synthetic fixture evidence through validated extraction.` | Nothing. |
| Fixture schema and adapter | Done | `Score synthetic fixture evidence through validated extraction.` | Nothing. |
| Gemma extraction and validation | Done | `Score synthetic fixture evidence through validated extraction.` | Nothing. No accepted quote to review. |
| Fixture recommendation API | Done | `Score synthetic fixture evidence through validated extraction.` | Nothing. |
| Planner, matrix, and evidence UI | Done | `Show the synthetic fixture result from Find the moment.` | Nothing unless the sample looks wrong. |
| Prove the fixture Hook end to end | Done | `Show the synthetic fixture result from Find the moment.` | Optional: load the local page and confirm three timelines and no winner. |
| Scoring, fixtures, extraction, and fixture API | Local fixture steps are done | — | Nothing unless a note asks. |
| Matrix UI and fixture Hook proof | Done | `Show the synthetic fixture result from Find the moment.` | Same local check as the fixture Hook proof. |
| Bounded SerpApi client | Done | `Add a bounded SerpApi client with retries and key redaction.` | Nothing. |
| Normalize and select candidates | Done | `Normalize provider places into three candidates or an insufficiency result.` | Nothing. |
| Live orchestration | Done | `Serve live recommendations without substituting fixture evidence.` | Nothing until the live capture. Reply `ok` before any credit is spent. |
| Capture and verify canonical fixture | Not started | — | Approve the live capture, then skim the fixture. |
| Evaluate and optionally tune Gemma | Not started | — | Colab T4, then read the scores. |
| Deploy and smoke the sponsor slice | Not started | — | Deploy and open the public URL. |
| Result states, evidence, and responsive reveal | Not started | — | Look at the states and the 1280px screen. |
| Friend walkthrough | Not started | — | Friend walkthrough. You send the paraphrase. |
| Security, performance, and pre-freeze verification | Not started | — | Read the verification list. Rotate a secret if one is found. |
| Review and freeze the MVP | Not started | — | Review and merge. That is feature freeze. |
| Production deploy, smoke, and runbook | Not started | — | Deploy, smoke the public page, name the rollback revision. |
| README, media, sessions, article, and packet | Not started | — | Read claims, approve media and sessions, keep the article as a draft. |
| Audit, publish, and submit | Not started | — | Merge, publish, submit, and paste the confirmation. |
