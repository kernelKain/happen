# Happen execution notes

This is the running notebook for the build. It is for you and for Cursor.

`docs/HANDOFF.md` is the locked plan from Prompt 1. Do not edit it to track progress. When this file and `HANDOFF.md` disagree about what has been done, believe this file plus the git history. When they disagree about the product, believe `HANDOFF.md`.

Deadline: October 5, 2026 at 06:59 UTC (12:29 PM IST). Feature freeze is build hour 19 of 24. Spend cap: $0 out of pocket. Existing free credits may be used.

## Right now

| | |
|---|---|
| Status | P0 in progress |
| Last finished step | P0.2 — Prove SerpApi evidence shape |
| Next step | P0.3 — Prove Gemma and Render feasibility |
| Branch | `phase/p0-prove-access` |
| Live URL | Not deployed |
| Spend | $0 |
| Biggest blocker | Gemma access and the Render credit balance are still unread |

## How branches and commits work

You asked for this on October 4, 2026. It replaces the earlier single-branch, no-commit rule for the coding agent.

- One branch per phase, created when that phase starts.
- One commit per step. The message is one plain sentence. It does not include a phase name or a step id.
- `docs/HANDOFF.md` and `docs/HANDOFF2.md` stay in git so the process is public.
- Secrets, `.env`, model binaries, and raw provider payloads stay ignored.
- Cursor does not push, merge, deploy, or publish unless you explicitly ask.

| Phase | Branch | When it is created |
|---|---|---|
| P0 Prove access | `phase/p0-prove-access` | Created for P0.1 |
| P1 Walking skeleton | `phase/p1-walking-skeleton` | At P1.1 |
| P2 Fixture Hook | `phase/p2-fixture-hook` | At P2.1 |
| P3 Live sponsor Hook | `phase/p3-live-sponsor` | At P3.1 |
| P4 Demo experience | `phase/p4-demo-experience` | At P4.1 |
| P5 Harden and freeze | `phase/p5-harden-freeze` | At P5.1 |
| P6 Production release | `phase/p6-production` | At P6.1 |
| P7 Submission evidence | `phase/p7-submission` | At P7.1 |
| P8 Submit and buffer | `phase/p8-submit` | At P8.1 |

## What you do versus what Cursor does

Cursor edits the repo, runs local checks, and updates this file. You handle accounts, secrets, dashboards, a real friend walkthrough, and any public publish or challenge submit. Never paste a secret into chat. Put keys in a local ignored `.env` file or in the host's secret settings.

---

## P0 — Prove access and feasibility

Branch: `phase/p0-prove-access`

Goal: measure SerpApi coverage, Gemma inference, and Render cost before building the app. Planned budget: 90 minutes. Done when every architecture-critical assumption has a measured result.

### P0.1 — Verify accounts and workflow controls

Status: **Done** on October 4, 2026.

Cursor checked the public repo, toolchain, GitHub Actions, Entire, CodeRabbit, and DevRelay. No secret values were printed. Evidence is in `docs/BUILD_LOG.md`.

What is true now:

- Repo `kernelKain/happen` is public on `main` at `a45880a`.
- Python on PATH is 3.14.4. The locked backend is Python 3.13, which `uv` can install as 3.13.15 during P1.1.
- Node 22.14.0, npm 10.9.2, uv 0.12.5, Entire CLI 0.11.3, Docker 29.8.2.
- GitHub Actions is enabled. Workflows have read permission.
- Entire is installed and not enabled. No `.entire/` directory was created.
- CodeRabbit has no config file, which matches the plan. The GitHub token cannot list installed Apps.
- DevRelay is connected to DEV user `kernelkain`. No session was published.
- `SERPAPI_API_KEY` and `HF_TOKEN` were unset. Render CLI is not installed, so the credit balance was not read.

Commit: `P0.1: record account and workflow access checks.`

Your side, still open from this step:

1. Optional, not blocking: in this repo run `entire enable` and choose the agent you are actually using (this build is running in Cursor).
2. Optional, not blocking: install the CodeRabbit GitHub App on `kernelKain/happen` if it is not already installed.
3. Done: `SERPAPI_API_KEY` is set in the ignored `.env`. It was not printed or committed.

### P0.2 — Prove SerpApi evidence shape

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

### P0.3 — Prove Gemma and Render feasibility

Status: **Not started.**

Cursor will load quantized Gemma 3 270M locally, run one schema prompt, and record memory, latency, and the native-or-Docker path. Training stays on free Colab only if a T4 session is actually available.

Your side after Cursor finishes:

1. Read the measured memory and latency. Say if the recorded Render plan is acceptable.
2. From the Render dashboard, report the credit balance and the current price of the chosen plan. Do not send payment details.
3. On Hugging Face, accept the Gemma model terms if the download says the model is gated.
4. If you want the tuning branch checked now, open a free Colab T4 session and say that it started. Otherwise the build keeps the untuned model until P3.5.

Your side before the model download:

1. Set `HF_TOKEN` in the ignored `.env` if the model is gated.

---

## P1 — Public walking skeleton

Branch: `phase/p1-walking-skeleton`, created at P1.1 from the P0 branch tip.

Goal: a public HTTPS frontend and a health/metadata API. Planned budget: hours 1.5–4.

### P1.1 — Scaffold the locked monorepo

Status: **Not started.**

Cursor creates the backend, frontend, `ml/`, scripts, `.env.example`, and lockfiles from the locked layout. Python 3.13.15 is installed with `uv`. Empty decorative folders are not added.

Your side after Cursor finishes:

1. Nothing is required if the install and import check pass.
2. If a package version has to move inside the locked range, read the one-line note in this file and object only if you disagree.

### P1.2 — Build health, metadata, and safe config

Status: **Not started.**

Cursor adds the FastAPI app, `/healthz`, `/api/v1/meta`, CORS, safe errors, and tests. The model is not loaded yet.

Your side after Cursor finishes: run nothing unless a check fails and the notes ask for a missing local tool.

### P1.3 — Build the frontend shell

Status: **Not started.**

Cursor builds the dark planner frame and the initial, loading, and service-error states. It checks the production build at 1280 and 390 widths.

Your side after Cursor finishes:

1. Optional: open the local page and say if the first screen is unclear.
2. Required only if the browser check cannot be run here. In that case the notes will name the exact command and what to look at.

### P1.4 — Establish CI and first public deployment

Status: **Not started.**

Cursor adds GitHub Actions and `render.yaml` for the static site and the web service. Cursor does not deploy unless you explicitly allow it.

Your side after Cursor finishes:

1. Push `phase/p1-walking-skeleton` when you want the draft PR and CI to run.
2. In Render, create the static site and the Python web service from this repo.
3. Set `SERPAPI_API_KEY` in Render's secret environment. Add `HF_TOKEN` only if the model download needs it.
4. Paste the public frontend URL and the health URL back here. Do not paste secret values.
5. Leave the services asleep or on the cheapest verified plan. Out-of-pocket spend stays $0.

---

## P2 — Fixture vertical slice

Branch: `phase/p2-fixture-hook`, created at P2.1.

Goal: the Hook works locally on a labeled synthetic fixture, through the real extraction and scoring path. Planned budget: hours 4–9.

### P2.1 — Implement domain contracts and scoring

Status: **Not started.**

Cursor implements hours, arrival windows, scoring policy v1, and tie-breaking, with repeated deterministic tests.

Your side after Cursor finishes: nothing, unless a test shows the locked threshold cannot be met. Cursor will stop and ask before relaxing a rule.

### P2.2 — Implement fixture schema and adapter

Status: **Not started.**

Cursor adds a labeled synthetic development fixture, checksums, and specific errors for a corrupt or missing fixture. This is not the final captured fixture.

Your side after Cursor finishes: nothing.

### P2.3 — Implement Gemma extraction and validation

Status: **Not started.**

Cursor adds the prompt, local llama.cpp adapter, schema parser, exact-span check, and one bounded retry.

Your side after Cursor finishes:

1. If the local model file is not on disk yet, the notes will name the download command. Run it only after `HF_TOKEN` is set, or tell Cursor the token is already in `.env`.
2. Read the one real extraction result and say if the quoted spans look fair. Cursor will not treat a failed extraction as a successful recommendation.

### P2.4 — Assemble fixture recommendation API

Status: **Not started.**

Cursor exposes the fixture recommendation endpoint. A successful body has three rows, one primary, and a different fallback, or an honest "not enough evidence" result.

Your side after Cursor finishes: nothing.

### P2.5 — Build planner, matrix, and evidence UI

Status: **Not started.**

Cursor builds the form, three timelines, the selected moment, the fallback, fit and confidence as separate labels, and the evidence panel.

Your side after Cursor finishes:

1. Open the local success screen at a 1280px-wide window.
2. Say whether you can tell the primary moment from the fallback without extra explanation.

### P2.6 — Prove the fixture Hook end to end

Status: **Not started.**

Cursor connects the page to the fixture endpoint and runs the keyboard path plus the Hook characterization test.

Your side after Cursor finishes:

1. Load the local page fresh, submit the Bengaluru dinner preset, and confirm you see three timelines, one highlighted moment, and a fallback at another restaurant.
2. If that path fails, say what you saw. Do not continue to live SerpApi until this passes.

---

## P3 — Live sponsor Hook

Branch: `phase/p3-live-sponsor`, created at P3.1.

Goal: one real SerpApi run, a sanitized fixture, and a checked Gemma path. Planned budget: hours 9–14.

### P3.1 — Implement bounded SerpApi client

Status: **Not started.**

Cursor adds search, place, and review calls with redaction, deadlines, one retry, and credit counting. Tests use fake HTTP, not your live key.

Your side after Cursor finishes: nothing unless the notes say the local key is still missing.

### P3.2 — Normalize and select candidates

Status: **Not started.**

Cursor maps provider fields into the internal place records and selects three candidates, or returns insufficiency with a reason. Missing fields are not invented.

Your side after Cursor finishes: nothing.

### P3.3 — Assemble live orchestration and protections

Status: **Not started.**

Cursor adds the live endpoint, deadlines, and the rule that a failure never silently switches to fixture data.

Your side after Cursor finishes: nothing.

### P3.4 — Capture and verify canonical fixture

Status: **Not started.**

Cursor runs one bounded live Indiranagar request, removes reviewer identities, writes the sanitized fixture, and checks that replay matches the live decision.

Your side before Cursor spends credits:

1. Reply `ok` to the single live capture. The plan allows up to 14 searches for this capture and the canonical run.

Your side after Cursor finishes:

1. Skim the sanitized fixture for names, keys, or reviewer identities.
2. Say if anything private must be removed before it is committed.

### P3.5 — Evaluate and optionally tune Gemma

Status: **Not started.**

Cursor builds the held-out set, measures the base 270M model, and keeps a tuned adapter only if it is better. If tuning does not improve the locked scores, the untuned model ships.

Your side after Cursor finishes:

1. For the training attempt, open a free Colab T4 notebook from `ml/` and let it run, or say that Colab is unavailable.
2. Read the evaluation numbers. Do not publish a score that is not in the evaluation report.

### P3.6 — Deploy and smoke the sponsor vertical slice

Status: **Not started.**

Cursor prepares the model download and the live/fixture wiring. Deployment itself waits for you.

Your side after Cursor finishes:

1. Deploy or redeploy the backend and frontend on Render.
2. Open the public fixture path in a fresh browser.
3. Allow one bounded live run, then paste the public URL and whether the page showed SerpApi sources, the Gemma version, and live-or-fixture labeling.

---

## P4 — Complete demo experience

Branch: `phase/p4-demo-experience`, created at P4.1.

Goal: every visible state, the evidence view, and the 1280px and 390px layouts. Planned budget: hours 14–17.

### P4.1 — Complete all visible result states

Status: **Not started.**

Cursor adds specific copy and a next action for loading, partial, insufficient evidence, timeout, quota, model failure, and fixture mode.

Your side after Cursor finishes: click one error state if a local page is running, and say if the next action is unclear.

### P4.2 — Finish evidence and methodology experience

Status: **Not started.**

Cursor finishes the evidence drawer or an inline panel: exact quotes, source links, conflicts, rejected-span count, and model version.

Your side after Cursor finishes: open evidence from the keyboard only, if the notes say the browser check could not be completed here.

### P4.3 — Finish reveal, responsive, and reduced motion

Status: **Not started.**

Cursor checks 1280×720 and 390×844. Reduced motion shows the result immediately.

Your side after Cursor finishes:

1. Look at the 1280px screenshot or the local window.
2. Say if the recommended moment is obvious. Decorative motion can be removed. The three timelines stay.

### P4.4 — Conduct friend walkthrough

Status: **Not started.**

This step is yours. Cursor only records what you report. It will not invent feedback.

Your side:

1. Ask your friend to plan the Bengaluru dinner from a fresh page. Five minutes is enough.
2. Ask whether fit and confidence felt different, and whether the fallback was clear.
3. Send a short paraphrase. Do not send their name, contact details, or account data.
4. Cursor will adjust only the approved wording.

---

## P5 — Harden and freeze

Branch: `phase/p5-harden-freeze`, created at P5.1.

Goal: required tests are green and the MVP can be merged. Planned budget: hours 17–19. After freeze, new features stop.

### P5.1 — Harden security and failure paths

Status: **Not started.**

Cursor adds the size, CORS, injection, rate, and checksum checks, then scans for secrets.

Your side after Cursor finishes: if a secret is found, rotate it yourself. Cursor will not print the value.

### P5.2 — Meet performance and reliability gates

Status: **Not started.**

Cursor measures three warm fixture runs and three warm live runs against the 2-second and 30-second limits.

Your side after Cursor finishes: if a live timing run needs the deployed service, say when Render is awake so the three runs are not wasted on a cold start.

### P5.3 — Run complete pre-freeze verification

Status: **Not started.**

Cursor runs the backend tests, frontend tests, model eval, browser checks, and the secret scan.

Your side after Cursor finishes: read the pass/fail list. Reply `ok` only if you accept the recorded limitations.

### P5.4 — Resolve review and freeze the MVP

Status: **Not started.**

Cursor fixes required review findings on the branch. You control the merge.

Your side after Cursor finishes:

1. Open the pull request and read CodeRabbit, or the manual checklist if CodeRabbit did not run.
2. Merge the green branch into `main` when you are satisfied.
3. Tell Cursor the merge commit. That moment is feature freeze.

---

## P6 — Production release

Branch: `phase/p6-production`, created at P6.1 from the merged `main` revision.

Goal: the public fixture journey works, and one live path is verified or honestly limited. Planned budget: hours 19–20.5.

### P6.1 — Deploy the frozen production revision

Status: **Not started.**

Cursor checks the Render config against the merged revision. You deploy.

Your side after Cursor finishes:

1. Deploy the exact merged commit.
2. Confirm `/healthz` returns HTTP 200 on the public URL.
3. Paste the frontend URL and the backend URL.

### P6.2 — Run final production smoke tests

Status: **Not started.**

Cursor prepares the smoke checklist. The public browser run needs the deployed URL.

Your side after Cursor finishes:

1. Open a fresh browser session and complete the fixture journey.
2. Approve one live run.
3. Tell Cursor if the page showed the wrong mode, a missing source, or a console error.

### P6.3 — Prove rollback and judge runbook

Status: **Not started.**

Cursor writes the judge-day runbook from the behavior that actually shipped: 60-second script, fixture path, live path, and what to do if the public URL fails.

Your side after Cursor finishes:

1. Name the last healthy Render revision you can roll back to.
2. Confirm you have a backup recording, or say that it still needs to be captured in P7.2.
3. Do not delete services or databases. Nothing destructive is required.

---

## P7 — Submission evidence

Branch: `phase/p7-submission`, created at P7.1.

Goal: README, media, and a DEV draft that match the measured product. Planned budget: hours 20.5–23.

### P7.1 — Finish README, diagrams, and attribution

Status: **Not started.**

Cursor updates the README, architecture diagram, setup, results, limitations, and attributions so every claim points at a measurement or an official source.

Your side after Cursor finishes: read the README once and mark any sentence that sounds stronger than the evidence.

### P7.2 — Capture hero media and demo

Status: **Not started.**

Cursor captures the hero screenshot and checks that it shows the mode label and no secrets. The 60-second recording uses the production URL.

Your side after Cursor finishes:

1. Watch the recording once.
2. If the live path is unstable, approve a labeled fixture recording instead.
3. Say if the recording shows anything private.

### P7.3 — Curate Entire and DevRelay sessions

Status: **Not started.**

Cursor lists candidate sessions. It does not publish one until you approve that exact session.

Your side after Cursor finishes:

1. Pick the sessions that explain a decision, a bug, or the Gemma evaluation.
2. Reject any session that contains a secret, a local path you dislike, or private feedback.
3. Reply with the ones that may be saved.

### P7.4 — Draft the DEV submission article

Status: **Not started.**

Cursor drafts the official DEV template with `#hf26challenge`, partner use, open-model rationale, and an AI-use disclosure. It stays a draft.

Your side after Cursor finishes:

1. Edit anything that does not sound like you.
2. Do not publish yet. Publishing is P8.2.

### P7.5 — Assemble final submission packet

Status: **Not started.**

Cursor fills the submission checklist with the repo, demo, and draft links.

Your side after Cursor finishes:

1. Open every link in a private window.
2. Say which links fail or which category claims are not proven.
3. Approve the docs branch for merge when the links match.

---

## P8 — Submit and buffer

Branch: `phase/p8-submit`, created at P8.1.

Goal: you submit a verified entry before the deadline. Planned budget: the last hour, with a buffer.

### P8.1 — Audit and release the exact submission revision

Status: **Not started.**

Cursor audits links, secrets, the license, and tests. You merge and, if you want, tag the release.

Your side after Cursor finishes:

1. Merge the docs branch into `main`.
2. Say whether you want a git tag. Cursor will not tag unless you ask.
3. Stop if any secret or broken required link remains.

### P8.2 — Publish, submit, and verify

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
| P0.1 | Done | `P0.1: record account and workflow access checks.` | Optional: Entire and CodeRabbit. |
| P0.2 | Done | `Record the Indiranagar restaurant evidence probe.` | Nothing else for SerpApi. |
| P0.3 | Next | — | Gemma terms, `HF_TOKEN` if gated, Render balance. |
| P1.1–P1.3 | Not started | — | Review only if a check needs you. |
| P1.4 | Not started | — | Push, Render services, secrets, public URLs. |
| P2.1–P2.4 | Not started | — | Nothing unless a note asks. |
| P2.5–P2.6 | Not started | — | Look at the local Hook once. |
| P3.1–P3.3 | Not started | — | Nothing unless the key is missing. |
| P3.4 | Not started | — | Approve the live capture, then skim the fixture. |
| P3.5 | Not started | — | Colab T4, then read the scores. |
| P3.6 | Not started | — | Deploy and open the public URL. |
| P4.1–P4.3 | Not started | — | Look at the states and the 1280px screen. |
| P4.4 | Not started | — | Friend walkthrough. You send the paraphrase. |
| P5.1–P5.3 | Not started | — | Read the verification list. Rotate a secret if one is found. |
| P5.4 | Not started | — | Review and merge. That is feature freeze. |
| P6.1–P6.3 | Not started | — | Deploy, smoke the public page, name the rollback revision. |
| P7.1–P7.5 | Not started | — | Read claims, approve media and sessions, keep the article as a draft. |
| P8.1–P8.2 | Not started | — | Merge, publish, submit, and paste the confirmation. |
