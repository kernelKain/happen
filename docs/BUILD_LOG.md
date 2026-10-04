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

