# 🌙 Happen

### *Evidence-First Evening Planning That Is Allowed To Say It Doesn't Know*

[![Hacktoberfest 2026](https://img.shields.io/badge/Hacktoberfest-Weekend_Challenge_2026-ff7a59?style=for-the-badge)](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01)
[![Gemma](https://img.shields.io/badge/Model-Gemma_3_270M-00e599?style=for-the-badge)](https://ai.google.dev/gemma)
[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=for-the-badge&logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/Frontend-React_19_%2B_TS-61dafb?style=for-the-badge&logo=react)](https://react.dev)
[![SerpApi](https://img.shields.io/badge/Data-SerpApi-ff7a59?style=for-the-badge)](https://serpapi.com/search-api)
[![License: MIT](https://img.shields.io/badge/License-MIT-00e599?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  <img src="https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/cover.png" alt="Happen — turn your evening into a checked plan" width="100%">
</p>

> **Built for a Friend:** Handcrafted for **Arun**, a friend who plans every evening the same way — ten browser tabs, a screenshot of opening hours that might be from last year, and a chatbot paragraph that reads finished. Last month one of those answers sent him to a bar that was shut that weekday, because the text had sounded sure of itself. So I built him a planner that is allowed to say "I don't know."

> **Challenge Categories Submitted:**
> * 🏆 **Best Use of Gemma** (Google open-weight model, run locally and gated in code)
> * 🏆 **Best Use of SerpApi** (the only place-data provider, with a hard per-plan budget)
> * 🏆 **Best Use of Entire** (agent sessions checkpointed throughout the build)
> * 🏆 **Best Use of Render** (one-click blueprint, both services defined in `render.yaml`)

---

## 📌 The Problem

Every evening planner will confidently give you three places and a paragraph about the lighting. The problem isn't that there are no options. It's that **you cannot tell which details anyone actually checked.** A place gets recommended because its listing said nothing about the thing you asked for, and a made-up walking time is printed with the same confidence as a phone number.

So I built the opposite: a planner that would rather show you a blank than invent a detail. Every claim is either backed by a source link and a retrieval time, or it is visibly marked **Couldn't confirm.**

## ⚡ Key Features

1. **Evidence-first planning.** Every fact on screen traces to a Google Maps listing, an official website, or community text, with the retrieval time attached.
2. **Explicit unknowns.** Each stop carries one **Couldn't confirm** line generated from whatever was actually *missing* — not from a template. Missing evidence never counts in a place's favour.
3. **Ambiguity gets a question, not a guess.** "At 9" could mean 9am or 9pm. Happen stops and asks before spending a single credit, rather than quietly picking one.
4. **A hard, server-enforced request budget.** Eight billed SerpApi requests per plan maximum. The ninth is refused before it is sent. Identical searches cache for 15 minutes.
5. **Change without losing the current plan.** Type a refinement and choose **Review this change**. The plan stays on screen until you press **Apply**.
6. **The open model is gated in code, not promised.** A local Gemma build was measured against held-out gates and failed, so a deterministic parser reads the prompt instead. The gate is enforced by hash at startup, and `/healthz` reports `model_claims_enabled` honestly.
7. **No accounts, no database, no tracking.** Close the tab and it's gone.

---

## 🏗️ Architectural Overview

```
   "Drinks in Lisbon on Friday at 9 for two."   (or anything natural)
                            │
                            ▼
        ┌──────────────────────────────────────┐
        │  Brief  (deterministic parser)      │
        │  place · date · time · stops · party │
        │  ONE question if anything is unclear │
        │  → 0 requests spent so far           │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │  SerpApi  (only data source)         │
        │  Google Maps · official sites ·      │
        │  community text                      │
        │  hard cap 8 billed requests / plan   │
        │  15-minute cache                     │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │  Feasibility + evidence scoring     │
        │  open that day at that time?         │
        │  does any listing support the ask?   │
        │  MISSING EVIDENCE = NO CREDIT        │
        └──────────────────┬───────────────────┘
                           ▼
        ┌──────────────────────────────────────┐
        │  One plan, at most two stops         │
        │  ├── why each stop was chosen        │
        │  ├── one "Couldn't confirm" line     │
        │  ├── sources + audit trail           │
        │  └── NO pad to look complete         │
        └──────────────────────────────────────┘
```

---

## 📁 Repository Structure

```
happen/
├── backend/                   # Python + FastAPI
│   ├── src/happen_api/
│   │   ├── planning/          # prompt → brief → evidence → itinerary
│   │   │   ├── interpret.py   # deterministic parser + ambiguity rules
│   │   │   ├── itinerary.py   # plans, checks, provenance contracts
│   │   │   ├── evidence.py    # one fact, one source, one timestamp
│   │   │   └── limits.py      # the 8-request per-plan allowance
│   │   ├── recommendations/   # scoring and ranking
│   │   ├── providers/serpapi/ # the only external data provider
│   │   ├── ai/                # extraction, quality gates, measurement
│   │   └── readiness.py       # model hash + gate enforcement
│   ├── tests/                 # 466 tests, no credit is ever spent
│   └── pyproject.toml
├── frontend/                  # React 19 + TypeScript + Vite
│   ├── src/app/landing/       # describe → review → result flow
│   ├── src/app/result/        # plan view + sources/audit panel
│   ├── src/lib/               # API client, result state, evidence view
│   └── tests/                 # unit + Playwright/axe
├── ml/
│   ├── reports/               # model-quality.json  ← the gate
│   ├── extraction/            # held-out + train jsonl
│   └── tune_extraction.ipynb  # the QLoRA experiment that failed
├── docs/
│   ├── HANDOFF.md             # the product contract
│   ├── Dev-post.md            # the DEV submission
│   └── press/                 # screenshots used by the README + post
├── scripts/
│   ├── download-model.py      # pinned, SHA-256 verified
│   └── scan-secrets.py        # runs in CI
├── render.yaml                # both services, one-click deploy
└── LICENSE                    # MIT
```

---

## 🧪 Why the Open Model Is Gated Off

This is the part I'd rather explain than let you assume, because a planner built on "never claim what you didn't check" shouldn't ship an unchecked model.

The original design had **Gemma 3 270M** extracting structured evidence from listings and reviews, running locally on CPU through `llama.cpp` from a pinned public quantized build, verified by SHA-256 before load, at temperature 0 with a fixed seed. No GPU, no hosted inference, no Hugging Face token.

I wrote a held-out set — 30 review excerpts and 24 planning prompts — and set gates before letting any of its output reach a user:

| Gate | Required | Gemma 3 270M | Gemma 3 1B |
|---|---:|---:|---:|
| Valid JSON on review extraction | 95% | **6.7%** | 100% |
| Right dimension + polarity on reviews | 80% | **4.4%** | 67.8% |
| Valid JSON on planning prompts | 95% | 91.7% | 100% |
| Essential planning fields correct | 90% | 66.7% | 79.2% |

The 270M model mostly couldn't produce valid JSON for my schema. I tried to fix it the way open weights allow: 100 training examples with no overlap with the held-out set, then a short QLoRA adapter on a free Colab T4. It came back **worse** than the untuned baseline. My rule was that an adapter ships only if it beats baseline by five points without adding invalid output, so it didn't ship.

The 1B build was a real step up — about 1.3 GB peak RSS, 0.7s to load — but it still got review polarity wrong about a third of the time. For this product that's worse than no model at all.

So the deterministic parser reads the prompt, and the gate is **code, not a promise**. [`ml/reports/model-quality.json`](ml/reports/model-quality.json) records the verdict and the measured SHA-256. At startup the backend hashes the model file and only permits model-derived claims when the report for *that exact hash* says it passed. It currently says it didn't, and `/healthz` reports `model_claims_enabled: false`.

The open path is still what shaped the product: it's the reason there's a schema, a validator, a held-out set, and a gate at all. The moment a Gemma build clears those gates, turning it on is a config change.

---

## 🚀 Quickstart

Requires **Python 3.13** (3.14 isn't supported yet) and **Node.js 20.19+ or 22.12+**, which is what Vite 8 asks for.

```bash
git clone https://github.com/kernelKain/happen.git
cd happen
cp .env.example .env
# set SERPAPI_API_KEY and HAPPEN_LIVE_ENABLED=true
```

**Backend** — http://127.0.0.1:8000

```bash
cd backend
uv sync
uv run uvicorn happen_api.main:app --host 127.0.0.1 --port 8000
```

**Frontend** — in a second terminal, http://127.0.0.1:5173

```bash
cd frontend
npm install
npm run dev
```

Then type an evening, or tap a starter:

> *Drinks in Lisbon on Friday at 9 for two.*

The model file is optional and only used for evaluation: `python3 scripts/download-model.py`. Do not commit `*.gguf` files.

### Tests

All mocked and fixture-backed, so they never spend a SerpApi credit:

```bash
cd backend
uv run ruff format --check src tests ../scripts/scan-secrets.py
uv run ruff check src tests ../scripts/scan-secrets.py
uv run pytest
cd ../frontend
npm run check
npm test
npm run build
npm run test:shell   # Playwright and axe at 1280px and 390px
cd ..
python3 scripts/scan-secrets.py
```

466 backend tests · 68 frontend unit tests · 22 Playwright tests with automated accessibility checks.

---

## ☁️ Deploying on Render

`render.yaml` defines both services, so the app deploys straight from the repository:

- **`happen-web`** — the built frontend as a static site.
- **`happen-api`** — the FastAPI backend in `singapore`.

Both track `main` and deploy only after CI passes. The backend build downloads the pinned public Gemma build and verifies its SHA-256 — no Hugging Face token needed.

To deploy your own:

1. Push or fork this repository.
2. Create a new Blueprint in the Render dashboard and point it at the repo.
3. Set `SERPAPI_API_KEY` in the dashboard. Never put it in `render.yaml`.
4. Render builds both services and serves them over HTTPS.

---

## 📸 Screenshots

| Landing | Review | Result |
|---|---|---|
| ![Landing page](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/landing.png) | ![Review step](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/review.png) | ![A checked Lisbon plan](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/plan.png) |

The middle screenshot is from a mid-build run, and it caught a real bug: that build read "at 9" as 9 **in the morning** and "Friday" as the coming **Wednesday**, then carried both forward silently. The parser now treats a bare time as ambiguous and stops to ask. That one fix is most of the difference between a confident plan and a true one.

---

## 🚫 What It Deliberately Doesn't Do

A smaller plan that is true beats a bigger one you have to double-check yourself.

- One evening, two stops at most — and it won't pad to look complete.
- No travel time. A second stop shows its own hours and a directions link, not a made-up arrival.
- No live crowd levels, reservations, capacity checks, or price conversion. Those are exactly what the Lisbon plan refuses to invent.
- No stop swapping once a plan is built.
- The request count and cache live in one process and reset when it restarts.
- Production never serves captured fixtures. They exist only for tests.

---

## 🤝 Contributing

Issues and pull requests are welcome. Please read [`docs/HANDOFF.md`](docs/HANDOFF.md) first — it's the product contract, and changes are checked against it. Small pull requests with one clear purpose are easiest to review.

Please never commit a SerpApi key, and do not add a database, an authentication layer, or a hosted model API. Run the full check suite above before opening a pull request.

## 🛡️ Security

Don't open a public issue for a leaked credential — report it privately to the maintainer. Keys are read from the environment only, and `scripts/scan-secrets.py` runs over tracked files *and* the production bundle in CI.

## 🙏 Acknowledgements

- [SerpApi](https://serpapi.com/search-api) — the only place-data provider.
- [Gemma](https://ai.google.dev/gemma) — Google's open-weight models, evaluated locally.
- [Entire](https://entire.io/) — agent sessions checkpointed throughout the build.
- [Render](https://render.com) — hosting for the live app.

## 📄 License

This project is licensed under the [MIT License](LICENSE).

*Disclaimer: Happen is an experimental open-source project built for Hacktoberfest 2026. Plans reflect what its sources actually said at the time of retrieval. It is not a booking service and does not guarantee that a place will be open, available, or suitable.*

---

**Author:** Kshitij Jain ([@kernelKain](https://github.com/kernelKain))

*Built for Arun, who now has one fewer reason to open ten tabs and still end up at the usual place.*
