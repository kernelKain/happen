# BUILD_LOG.md

Execution evidence for Happen. No secret values belong in this file.

## P0.1 — Verify accounts and workflow controls

- Date: 2026-10-04
- Queue step: P0.1
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

Python 3.13 is the locked backend version. The system interpreter is 3.14.4. Installing 3.13.15 with `uv` is deferred to P1.1, when the backend environment is created. That is a toolchain observation, not a version-policy change.

### Access matrix

| Control | Evidence | Status |
|---|---|---|
| Repository | Public `https://github.com/kernelKain/happen`. Remote `origin` is `git@github.com:kernelKain/happen.git`. | Verified |
| Baseline | `main` at `a45880a` (`a45880a2d3b8d80d2265f0403905ae62bb2f2603`), tracking `origin/main`. Message: Initial commit, 2026-10-03 19:25 IST. | Verified |
| Working tree | Only untracked `docs/` before this step. No unrelated code changes. | Verified |
| Branch `build/happen-mvp` | `git branch --list` returned no match. | User action required before implementation |
| GitHub Actions | Actions enabled, all actions allowed, default workflow permission `read`, reviewers cannot be approved by workflows. | Verified |
| Pull requests | None. | Expected |
| `SERPAPI_API_KEY` | Unset in the process environment. No repository `.env`. | Blocked for P0.2 |
| SerpApi balance | Not queried. | Unverified |
| `HF_TOKEN` | Unset. No local Hugging Face token file. | Blocked for gated model download |
| Gemma terms and artifact | Not checked. | Unverified until P0.3 |
| Render balance and plan price | No Render CLI and no Render API key in the environment. Dashboard was not opened. | Unverified user-dashboard check |
| Colab T4 | Not checked in this step. | Unverified until P0.3 |
| Entire | `entire status` reports not set up. `.entire/` was not created. | User action: `entire enable` |
| CodeRabbit | No `.coderabbit.yaml`, which matches the locked default. The current GitHub token cannot list App installations (HTTP 403). | Time-boxed unverified |
| DevRelay | MLH account is connected with `dev:read:all` and `dev:write:all`. DEV profile `kernelkain` (id 3953019) resolves. No session was saved. | Connection verified |
| Live URL | Not deployed. | Expected |
| Spend | $0. | Verified |

### HANDOFF and repository

Git matches the locked baseline: branch `main`, commit `a45880a`, public remote, no execution branch, no deployment. `docs/HANDOFF.md` remains the uncommitted planning artifact and is now ignored.

The active execution harness is Cursor. When Entire is enabled, select the agent that is actually used. The planning note that expected Codex applies only if that agent performs the work.

### Verification

- `git status`, `git branch -vv`, `git log`, and `git remote -v` match the matrix.
- `gh repo` metadata: `visibility=public`, `default_branch=main`.
- `gh api repos/kernelKain/happen/actions/permissions` and workflow-permission endpoints match the matrix.
- `entire status` printed `not set up`.
- DevRelay `mlh_connection_status` reported connected, and `get_authenticated_user` returned DEV user `kernelkain`.
- No secret value was printed or written.

### Blockers carried forward

1. `SERPAPI_API_KEY` is now set locally. Resolved on October 4, 2026.
2. Configure `HF_TOKEN` locally, after Gemma terms are accepted, before a gated download in P0.3.
3. Read the Render credit balance and current plan price from the Render dashboard before the P0.3 cost decision.
4. Phase branches replace `build/happen-mvp`. `phase/p0-prove-access` exists.
5. Run `entire enable` when ready. Runtime proofs take priority over this setup.
6. Confirm the CodeRabbit GitHub App is installed on this repository. This does not block the runtime proofs.

## P0.2 — Prove SerpApi evidence shape

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
