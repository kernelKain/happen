# Happen execution notes

This is the running notebook for the build. A new chat must read this file before doing anything else.

`docs/HANDOFF.md` sections 1–29 are the historical product plan approved on October 3, 2026. Section 30, approved on October 4, 2026, is the current product contract. Do not edit `HANDOFF.md` to track progress. When this file and `HANDOFF.md` disagree about what has been done, believe this file plus the git history. When they disagree about the product, believe section 30. Use sections 1–29 only where section 30 is silent.

## Resume for the next chat

The current branch is `global-live-experience`. The current work is the Global Live Experience redesign. Section 30 of `docs/HANDOFF.md` is the approved contract: a global, prompt-led, live evening planner, one evening, at most two stops, SerpApi as the only external place and supporting-web source, Python validation and selection, and live retrieval only. Captured fixtures stay test data.

The planning records, a deterministic prompt parser, and destination resolution are in `backend/src/happen_api/planning/`. A prompt becomes a brief with at most one follow-up. Relative dates stay pending until a destination timezone is known. Destination resolution uses the existing SerpApi client: the free Locations API first, then at most one billed Maps lookup when coordinates are still missing. That lookup shares the eight-request plan budget. Timezones come from coordinates through `timezonefinder` offline, and date arithmetic uses `zoneinfo`. The parser does not load Gemma.

Local Gemma was measured and missed the planning and review gates. Model claims stay off. The customer page does not score a captured fixture. The deterministic parser remains the planning reader.

Global place discovery is in `backend/src/happen_api/planning/discovery.py`. It builds up to two Maps queries from the resolved destination and the ordered intents and keeps up to five valid places per intent. Duplicates are dropped by place id, then data id, then a normalized name and address. A pin more than 80 km from the destination is rejected. Missing optional fields stay unknown. Python ranks the pool from listed evidence: open hours, a website, a Maps link, a rating, and a requested constraint only when retrieved text verifies it. Unknown evidence adds nothing. Open hours outrank a preference. An accessibility or dietary contradiction is not selected, and an unknown accessibility or dietary need is not presented as verified. A price symbol is compared only with a budget tier, and a numeric amount only with the same currency. Party size is kept and shown, and it stays unknown without capacity evidence. The customer response names those checks and does not include a numeric score. Provider order is only the tie-breaker when that evidence is equal; an equal rank then uses the name and the place id. Details are fetched only for feasibility or a close comparison, reviews only when they can affect a requested constraint, and at most two web searches only for missing hours. A definitely closed finalist is replaced while budget remains. Those calls share the same eight billed requests as destination resolution. `POST /api/v2/plans` carries party size, budget, preferences, and accessibility needs, then Python selects one or two stops. Gemma stays off. The customer page is the landing composer. It interprets a prompt, shows one follow-up when needed, resolves the destination, and calls place discovery only after Find the plan. The result is a vertical timeline of at most two stops. A later change shows a diff and waits for Apply or Cancel. A change that keeps the destination, date, time, and intents does not search again. A change to party size, budget, preferences, or accessibility asks Python to score the stored pool again. It does not offer a fixture or a sample plan. A layout query stays on that page. When `APP_ENV` is production, the process does not mount the historical recommendation routes, and metadata does not publish the Indiranagar preset or a fixed timezone. Development still mounts those routes so tests can replay captured fixtures. A live failure does not tell the visitor to use captured evidence. Planning requests are limited to 16 KB and 2,000 characters. The normalized candidate pool is cached in memory for 15 minutes under a hash key. One process admits at most three billed plans at once and returns HTTP 429 when the rate window is full. A cancelled search is not sent. The HTTP client and any loaded model are released when the process stops. Production plan errors do not contain fixture names, a model prompt, or a stack trace. `README.md` explains the prompt-led workflow, the measured Gemma fallback, the eight-request cap, local setup, and the remaining user-owned work.

`global-live-experience` started from `c0bc793`, the merge of pull request 8. `origin/main` is at that same commit. This branch has no upstream. Do not push, merge, deploy, or publish unless asked.

Section 27 of `docs/HANDOFF.md` still says the build has not started. That section is the October 3 planning snapshot. This file is the progress log.

| | |
|---|---|
| Current phase | Global live experience |
| Phase complete | No. Five audited defects are repaired. Latency and concurrency are bounded by one shared monotonic deadline. The landing now states one outcome above the fold and keeps methodology behind a disclosure. The model quality gate failed, so claims stay off. |
| Last finished step | Refine the evening planning entry. |
| Next step | live SerpApi latency measurement, which needs explicit approval for credits |
| Branch | `decision-ready-evenings`, created from the local `8be4ab9` |
| Pull request | None for this branch. Pull request 8 merged `demo-experience` into `main` at `c0bc793`. |
| Remote | `origin/main` is at `c0bc793`. This branch has no upstream. |
| Live URL | Not deployed |

Still open from the walking skeleton, and not the current step:

1. Create the Render services from `render.yaml`, then paste the frontend URL and the health URL back here.
2. Let CodeRabbit finish on the merged walking-skeleton pull request before the next phase pull request.

## Working rules for every later chat

- Branch names, commit messages, and code comments do not use phase or step numbers.
- Each step gets one short commit message that says what the change does. Do not name the coding tool.
- One branch per phase: `walking-skeleton`, then `fixture-hook`, `live-sponsor`, `demo-experience`, `harden-freeze`, `production`, `submission`, and `submit`. The current branch is `global-live-experience`.
- After each phase pull request, wait for the CodeRabbit review. Before the next phase, fetch and pull the latest remote branch so review edits are included.
- Before the next phase, also stop so the app can be tested by hand. Give the exact frontend and backend commands for what exists at that moment.
- Do not push, merge, deploy, or publish unless asked.
- Keep secrets out of git, notes, and logs.

## How to run what exists today

The page can be opened. The customer page interprets one evening of at most 2,000 characters, keeps the original wording on an editable brief, and retrieves live places only after Find the plan. If the place, date, or time is missing, it asks one question. An ambiguous destination stays a choice. A failure stays on the page and does not substitute a sample plan. A `layout` query does not open another page. The customer page does not link to the repository, show a neighbourhood preset, or offer captured evidence. The API serves health, metadata, `POST /api/v2/briefs/interpret`, `POST /api/v2/destinations/resolve`, `POST /api/v2/plans`, and `POST /api/v2/plans/refine`. A development process also mounts `POST /api/v1/demo-recommendations` and `POST /api/v1/recommendations` so tests can replay fixtures. Production does not mount those routes. `model_status` is file integrity: `ready` when the pinned GGUF is present and its checksum matches, otherwise `not_loaded` or `unavailable`. `model_quality` and `model_claims_enabled` are separate. The checked-in report marks the pinned 270M artifact `failed` and leaves claims off. Overall health stays `ok` when the file and the captured fixture are both ready. Health can report that the fixture file verifies. That report is not a user-facing plan.

Frontend, from the repository root:

```bash
cd frontend
npm install
npm run dev
```

Open the local address Vite prints, usually `http://127.0.0.1:5173`. The page is the evening landing. **Plan this evening** sends the written evening for interpretation. **Find the plan** starts live place retrieval and shows the timeline. **Review this change** prepares a diff and does not replace the timeline until **Apply**. **Cancel** drops the diff. An example fills the composer and does not send it. Stop it with Ctrl+C.

Backend, from the repository root:

```bash
cd backend
uv sync
uv run uvicorn happen_api.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/api/v1/meta`. Health returns HTTP 200. On this default development process, `fixture_status` is `ready` and metadata `fixture_available` is true when the captured fixture file verifies. Production metadata sets `fixture_available` to false and does not publish a neighbourhood or a fixed timezone. `model_status` is `ready` when `ml/.cache/google_gemma-3-270m-it-Q4_K_M.gguf` matches the manifest checksum, and `not_loaded` when that file is absent. `model_quality` is `failed` for that pinned checksum because `ml/reports/model-quality.json` records a missed gate, and `model_claims_enabled` is false. A different checksum is `unmeasured` and also leaves claims off. Overall `status` is `ok` only when the artifact and the fixture file are ready. Neither response includes a secret. `render.yaml` points both services at `main`, turns live mode on, and leaves `SERPAPI_API_KEY` as a dashboard secret. Stop the server with Ctrl+C.

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
| Status | Audited and verified. The whole branch passes 464 backend, 62 frontend, and 21 shell tests with formatting, lint, the secret scan, and the production build clean. Three silent defects were found and fixed: the plans route was given the destination attempt cap, a stage could begin with too little budget left to finish, and a typed follow-up answer could be wiped before it was sent. Swaps, cached alternatives, why-won comparison, calculated arrivals, departures, and route distance do not exist and are documented as absent. One monotonic 14s deadline governs provider work, the eight-attempt allowance is charged per attempt, and cached plans spend zero requests. Warm p50/p95 against live SerpApi is unmeasured. Gemma claims stay off. |
| Last finished step | Verify the decision-ready evening experience. |
| Next step | A manual local test of one real evening, which only the user can run |
| Branch | `decision-ready-evenings`, created from the local `8be4ab9` |
| Live URL | Not deployed |
| Spend | $0 |
| Biggest blocker | Render services are still not created, and that deploy is not the current step. |

## Provider hours

`happen_api.domain.hours` is the only hours parser. It runs at the SerpApi boundary in `planning.discovery` and the historical `domain.timing` path calls the same functions, so there is no second parser to drift.

`normalize_hours` accepts the shapes already observed in this repository:

- a weekday dictionary under `operating_hours` or `hours`
- a list of single-key weekday dictionaries
- a list of `{"day": ..., "hours": ...}` records
- a list of `Monday: 6:00 PM–11:00 PM` strings

It returns a `ProviderHours` schedule keyed by `DayOfWeek`, plus the provider's own text on `original_text` and in `unrecognized`. The text also stays on `DiscoveredPlace.hours` and is emitted as Maps evidence for each stop.

Supported interval text: `6:00 PM–11:00 PM`, `18:00-23:00`, `6 PM – 11 PM`, `6:00pm-11:00pm`, `6:00 PM to 11:00 PM`, several intervals on one day separated by commas, `Open 24 hours`, `Closed`, and any hyphen, en dash, em dash, or minus sign. Weekday labels are case-insensitive and accept the usual short forms. An interval is half-open, so `6:00 PM–1:00 AM` is open from 18:00 through 00:59 and the previous day is checked for that coverage.

Rules the parser holds to:

- Feasibility reads the canonical schedule. It never parses a display string.
- A place that is definitely closed for that arrival is excluded. Hours that could not be read stay unknown and are kept, with lower confidence.
- An unrecognized weekday label or time string is never translated into a day or an interval. It stays unknown and raises a structured reason.
- A place assembled outside the provider boundary still normalizes its own display lines, so no caller silently loses its hours.

`hours_reason` returns the reason behind each decision: `hours_covers_arrival`, `hours_closed`, `hours_outside_listed_hours`, `hours_day_not_listed`, `hours_missing`, `hours_unparseable`, `hours_day_value_unrecognized`, `hours_day_label_unrecognized`, `hours_shape_unrecognized`, or `hours_contradictory`. The stop's `hours` component carries that code, so an unreadable listing is reported as unreadable rather than as missing.

The second stop no longer claims a verified arrival. Only the first stop asserts a planned arrival time; the second says that a separate arrival was not planned.

Coverage lives in `tests/unit/test_hours_normalization.py` and the 12-hour strings in `tests/unit/test_scoring.py`. Test fixtures across the planner, discovery, and contract suites now use 12-hour SerpApi-shaped text instead of `17:00-22:00`.

## Destination phrases

`planning.interpret` reads the destination as the phrase that follows a location marker. There is no city catalog gate and no ASCII, capitalization, or word-count requirement.

Recognized markers are `in`, `near`, `around`, `close to`, and `outside of`. The phrase runs until a boundary word, not until a word count, so a name as long as `Ho Chi Minh City` or `Santiago de los Caballeros` survives intact.

Boundaries that stop the phrase:

- temporal words and weekdays, so `tomorrow`, `Friday`, `tonight`, and `on 2026-10-05` stay out;
- clock words such as `at`, `on`, `by`, `from`, `until`, plus any digit or currency symbol;
- budget words such as `under`, `about`, `max`, and currency names;
- party words such as `two` and `four`, plus `for`;
- intent words such as `dinner`, `coffee`, `show`, and `museum`;
- connectives and articles such as `of`, `to`, `the`.

Text is kept as written. Accents, apostrophes, hyphens, and abbreviation periods survive, so `São Paulo`, `St. John's`, `N'Djamena`, `Aix-en-Provence`, `Kraków`, and `Washington, D.C.` all read correctly. A comma continues the phrase, so a state, region, or country stays attached: `Austin, Texas`, `London, Ontario`, `Mexico City, Mexico`.

The known-city list still exists, but only as an optional ambiguity hint. A shared name such as an unqualified `London` raises the same question as before; SerpApi resolution stays authoritative, and a qualified phrase such as `London, Ontario` proceeds without asking.

Two things Happen does not do: it does not decide whether an arbitrary phrase names a real place, and it does not add a geocoder or a model call. An unknown phrase such as `somewheretown, nowherecounty` is passed to the resolver, which returns its own unsupported or ambiguous outcome. A prompt with no location marker still asks the destination question.

`tests/unit/test_planning_destination_phrase.py` covers this behavior. The gold label for `plan-019` was updated: `dinner in reykjavik` now reads as `reykjavik` rather than as no destination.

## Refinements

The proposal and diff interaction is unchanged. **Review this change** prepares a proposal and the current plan stays on the page. **Cancel** drops the proposal and leaves both the brief and the timeline as they were. **Apply** now always sends the complete proposed brief to `POST /api/v2/plans`.

Before this step Apply compared the two briefs in the browser and, when it decided nothing needed rescoring, committed the new brief and closed the diff without contacting the server. The visible brief changed and the recommendation did not. A preference-only Apply was also the one case that was guaranteed to look like it worked while doing nothing.

Apply now behaves like this:

1. The current plan stays visible. Nothing is committed yet.
2. A destination change resolves the new place first, so the local zone is known.
3. The whole proposed brief is sent to `POST /api/v2/plans`.
4. On a response the brief, the plan, and the diff are all updated together.
5. On a failure the previous brief and the previous plan both stay, and the error is shown.

### Evidence refresh and recomputation

The two questions are separate, and the server owns both.

`discovery_cache_key` is built from the resolved destination, the local date, the local time, and the intents. Constraints are deliberately not part of it, so a stored pool can be scored against any set of constraints. The key therefore describes what evidence must be retrieved, not how it is judged.

| Change | Retrieval | Recomputation |
|---|---|---|
| destination, local date, local time, intents | new search | yes |
| preferences, accessibility needs, budget, party size | reuse the cached pool | yes |

`needsAnotherSearch` answers the first question and `refinementRefresh` names both. Neither is a licence to skip the server: Apply sends the brief regardless, and Python rebuilds and revalidates the constraints from the request body. Nothing about scoring is trusted from the browser.

A cached rescore can still change the answer. A better-evidenced place may now outrank the one that was previously selected, and it does. When the cached evidence cannot verify a new constraint, the result is `insufficient_evidence` with that constraint reported as unknown, which is an explicit outcome rather than a stale success.

`tests/contract/test_plan_refinement.py` covers the cache behavior with a counting in-memory provider.

## Evidence provenance

`happen_api.planning.evidence` holds the typed claim. Everything a user can be shown goes through it first.

```python
EvidenceClaim(
    kind=ClaimKind.maps | ClaimKind.official | ClaimKind.community,
    field=ClaimField.hours | place_identity | constraint | contact | description | provenance,
    text="monday: 6:00 PM–11:00 PM",
    url=HttpUrl("https://maps.example/kura"),   # only when the link is safe
    retrieved_at=datetime,
    matched_by=MatchMethod.place_record,
    verification=Verification.verified,
)
```

`PlanEvidence` carries the same fields into the response, so the frontend can label a claim without re-deriving anything.

### What was wrong

Three defects, all reproduced before the fix:

- An official-domain search result was classified by *what it mentioned*, not by *where it came from*. A snippet from the place's own website was dropped on the floor unless hours were missing, in which case it was filed into `community_notes`.
- The exact result URL was discarded at the boundary. `_apply_web` read the link only to classify the host, so `PlanEvidence.url` was `None` for every community claim and the reader could not follow a citation.
- Any community text that merely mentioned hours became a conflict. `The ramen at Kura is great, we went at 7pm` produced "an official hours statement and a community statement disagree."

### Rules now

- A result is classified by its own domain. `_row_kind` asks whether the host is a community host, or the place's official domain. Nothing about the wording changes the answer.
- The exact safe URL survives to the response. `safe_link` returns the URL verbatim, or `None`.
- `safe_link` drops a non-HTTP scheme, a missing host, a local or `.local` host, embedded credentials, and any query carrying `api_key`, `token`, `secret`, and similar. An unsafe link yields no link at all; the claim keeps its text.
- Maps hours stay Maps evidence even when an official site exists. The official site is added as its own claim.
- A conflict is recorded only when normalization proves the claims incompatible: community text asserting closure *and* the record listing that day closed. Otherwise the claim stays secondary and unverified.
- Official normalized hours take precedence. `ClaimsConflict.resolved` returns the Maps record, never the community text.
- A row is claimed only when its provider id appears in the link, or it is on the official domain *and* names the place, or it names the place together with an address, locality, or destination anchor. An official-domain page that never names the place is not claimed.

### Reviews

`place_reviews` is called only when a requested preference is one `review_phrases` recognizes and is still unverified for that place. No preference, or a wording a review cannot check, skips the request entirely. Retained snippets still feed `assess` as unverified context, so a community passage can verify a constraint while staying community.

Snippets stay short, carry no reviewer identity, and a `_PHONE` pattern drops anything that looks like a phone number.

### UI

The evidence drawer shows the source kind, the supported field, the match method, the retrieval time, and a `Not verified.` or `Conflicts with another source.` line where that applies. Each claim carries `data-verification` and a source class, so official, Maps, and community are visually distinct.

`tests/unit/test_evidence_provenance.py` covers classification, URL preservation, entity mismatch, unsafe-link filtering, real conflicts, non-conflicting secondary text, and review skipping.

## The evening planning entry

This step reshapes the landing into a decision product. It follows the latency work and changes presentation only, not behaviour, contracts, or the plan-selection logic.

### What is above the fold

Measured in a real browser, and asserted by a Playwright test at both sizes:

| Viewport | Hero bottom | Viewport height | Above the fold | Horizontal overflow |
|---|---|---|---|---|
| 1280 × 720 | 676 px | 720 px | yes | none |
| 390 × 844 | 829 px | 844 px | yes | none |

The order is deliberate and is what the tests assert:

1. the Happen identity
2. the headline **Your evening, checked.**
3. one supporting sentence, capped at 140 characters by a test
4. the prompt composer
5. three example chips
6. a trust strip: live places, checked timing, source-backed decisions

The headline replaced **One evening, held to two stops.** The old line described a constraint; the new one describes the outcome the visitor gets.

### What moved out of the primary journey

The **Try an evening** section became the chips inside the hero. **How it works** was removed as a section. The **Live evidence** footer became a closed `Methodology` disclosure with an `aria-expanded` toggle, so the explanation of how Happen decides is available without competing with the decision itself.

Every mention of SerpApi, Gemma, Python, and the quality gates now lives inside that disclosure. Three tests assert this: one scans the hero text for implementation language, one asserts the disclosure is closed on load, and one asserts the model wording still cannot overstate what the model does once opened.

### What was deliberately kept

- The prompt-led interaction is untouched. Reading the prompt, asking one follow-up, resolving the destination, and searching only after Find the plan all behave exactly as before.
- Chips fill the composer and never submit it. A chip also moves focus to the composer, so a keyboard user can start editing immediately.
- No chat bubbles or transcript styling were introduced.
- No UI framework was added. React and hand-written CSS remain the only dependencies.
- No remote stock asset was fetched. The only imagery is the existing inline `Mark` SVG.

### Layout notes

The 1280 px layout places the headline, sentence, and chips in the left column and the composer in the right, with the trust strip as a three-across row beneath. Below 640 px a tighter vertical rhythm and a shorter composer are what keep the trust strip on screen at 390 × 844; without them it fell to 919 px and pushed below the fold.

`prefers-reduced-motion: reduce` still disables the entrance animation. A Playwright test asserts `animationName` is `none` under reduced motion, and the reduced-motion block now also covers the chip and disclosure transitions.

### Tests

| Suite | Before | After |
|---|---|---|
| `npm test` | 55 | 61 |
| `npm run test:shell` | 15 | 21 |

New Vitest coverage: the new headline and strip, absence of implementation language above the fold, the disclosure's closed and open states, the short-sentence cap, exactly three chips each under 70 characters, chip fill without submit, and keyboard reachability with correct `aria-expanded`.

New Playwright coverage: the above-the-fold contract at both sizes, the methodology disclosure, keyboard chip fill, a visible focus ring on primary controls, and the fold-height assertion.

The existing axe check runs on the new landing at both viewports and reports no serious or critical violations. The palette was not changed, so contrast is unchanged from the previously audited tokens.

### Not done

The warm p50 and p95 targets remain unmeasured against live SerpApi, as recorded in the latency section above. This step changed no backend code and spent no provider credit.

## Planning latency and concurrency

This step bounds planning latency without changing what a plan says. It starts from `8be4ab9`.

**Honest status of the baseline.** `8be4ab9` is a local commit on `global-live-experience` that has never been pushed, never had a pull request, and therefore never received a CodeRabbit review. The manual checks for the earlier repair have not been confirmed as run. This branch is built on that unreviewed baseline because the alternative was to write no code at all. Nothing here has been validated against live SerpApi.

### The one shared deadline

`happen_api.planning.deadline` owns the wall-clock budget for one request.

- `PlanningDeadline` is monotonic, so a host clock change cannot extend or shorten it. The budget is the contract's 14 seconds.
- `budget_for(cap)` hands a stage its own cap clipped to what the request has left. A stage that arrives late is never given a fresh full cap, so concurrent work cannot overrun the deadline between them.
- `allow_send()` runs immediately before every outbound send. A cancelled or expired attempt returns `False`, so it is never sent and never charged.
- `StageTiming` records only a stage name, elapsed milliseconds, and an outcome. `stage_timings_are_safe` exists so a test can prove no prompt, destination, URL, credential, or review text can reach a log line.

Per-stage ceilings are declared in the module: destination 6s, search 8s, details 4s, reviews 4s, web 4s, directions 4s, extraction 6s, cached read 0.3s.

### Ordering of the send gate and the allowance gate

The two gates are ordered, and the order is the safety property:

1. `set_send_gate` — the shared deadline and the caller's disconnect state. May stop the attempt.
2. `set_attempt_gate` — the plan's eight-request allowance, claimed inside `SerpApiClient._billed_attempts` just before each send.

The send gate runs first, so a request the deadline or a disconnection stopped is never charged. The allowance gate still runs once per attempt, so a retry spends its own request.

### What was deliberately not changed

Enrichment order, `_sort_pool`, and `selection_key` were left alone. `selection_key` already ends in `(-fit, provider_rank, casefolded_name, place_id_or_data_id)`, which is a total order over the pool. Two tests were written against the wrong premise and were corrected rather than the code:

- A test asserting that reversing provider rows leaves the pool order unchanged was wrong. `provider_rank` is the provider's own order and is the documented first tie-breaker, so reversing input legitimately reverses it. The test now asserts that repeated runs of one fixed input are byte-identical, and that the documented chain is what settles the order.
- A test asserting equal-fit candidates sort by name regardless of input was also wrong, for the same reason. Provider rank is consulted first.

Sorting after concurrent retrieval is therefore already deterministic, which is why no new ordering layer was added.

### Benchmark

`backend/scripts/benchmark_planning.py` measures the planner against local fakes only.

```bash
cd backend && uv run python scripts/benchmark_planning.py
cd backend && uv run python scripts/benchmark_planning.py --json
```

Fixture-derived results from this machine, 40 runs per case after 3 warmups:

| Case | p50 | p95 | Provider calls |
|---|---|---|---|
| Cached plan, no provider call | 0.166 ms | 0.200 ms | 0 |
| Metered billed call, 25 ms scripted delay | 25.2 ms | 25.4 ms | 1 |

**These are not live numbers.** The script states this in its own output and in its JSON (`"measures_live_serpapi": false`). It excludes real network latency, SerpApi response time, and cold-start model loading. The only honest claims from it are relative: the cached path performs zero provider calls and completes far inside the 300 ms target, and one metered call costs one attempt.

The contract's warm targets of p50 <= 5s and p95 <= 12s are **not** met by this evidence and are **not** claimed. They remain unmeasured against live SerpApi.

### Still to do, and it needs a live run

- Measure warm p50 and p95 against real SerpApi for a real destination. That spends credits and needs explicit approval.
- Confirm the 14-second deadline holds under real latency, including the retry path.
- Confirm the per-stage ceilings are generous enough that ordinary calls are not cut short.
- A full plan has not been timed end to end. Only the cached read and one metered call are covered.

### Test totals after this step

| Suite | Result |
|---|---|
| `cd backend && uv run ruff format --check src tests ../scripts/scan-secrets.py` | 86 files already formatted |
| `cd backend && uv run ruff check src tests ../scripts/scan-secrets.py` | All checks passed |
| `cd backend && uv run pytest` | 461 passed (448 before, 13 new) |
| `cd backend && uv run python scripts/benchmark_planning.py` | ran, fixture-derived |
| `python3 scripts/scan-secrets.py` | exit 0 |

## Independent repair audit

Five defects were reported and repaired on October 5, 2026. Each was reproduced first, then fixed, then covered by a regression test. No product contract was changed to legitimize any of them, no provider, database, hosted model, or auth was added, and no live SerpApi request was made.

### What was wrong, and what it is now

| Defect | Before | Now |
|---|---|---|
| SerpApi accounting | `MeteredProvider` claimed one request per wrapper call, then reconciled afterwards from a count the failure carried. One call that retried could send twice on one claim, and the accounting lagged the network. | The allowance is claimed atomically at the outbound-attempt boundary. `SerpApiClient.set_attempt_gate` installs a gate that runs once per network send, so every retry spends its own request. |
| Follow-up token | A follow-up answer produced a brief with no `plan_token`, so resolving a missing destination left the session unusable. | `follow_up` copies the plan identity from the brief the server already issued. The answer continues on the same plan. |
| Two actions, one behaviour | Both answering a question and accepting a post-result change used the same refinement call, and the page kept spending the previous plan's allowance. | `RefinementPurpose` is an explicit typed field on the route and in the TypeScript client. `follow_up` preserves the token and allowance; `plan_refinement` is issued a new token with a fresh eight-request allowance. |
| Hours conflicts | Agreement was reported as disagreement. A record listing Monday closed plus community text saying closed Monday produced a conflict warning. | `reconcile_hours` returns `agreement`, `conflict`, or `unverifiable`. Only provably incompatible claims about the same weekday conflict. Text that cannot be aligned stays unverified. |
| Destination qualifiers | The qualifier alternatives were concatenated without `\|` separators, so `quiet`, `vegetarian`, `we`, `evening`, `indoor`, and `hearing` never matched a boundary and were swallowed into the place name. | Each alternative is separated. `Amsterdam quiet` reads `Amsterdam`, `Tokyo vegetarian` reads `Tokyo`, and `Lisbon we` reads `Lisbon`. |

### Why a `plan_refinement` gets a new token

Section 30.9 says a refinement the user submits is a new submitted plan with its own maximum of eight billed requests, and that unused requests from the previous plan do not raise that maximum. A `follow_up` is not that: it is the same submitted plan asking its one outstanding question, so it keeps both its identity and its remaining allowance.

The previous identity is forgotten once a refinement is applied, so the old allowance cannot be spent afterwards. The page uses the token that came back with the proposal rather than the one it was holding.

Nothing about the allowance is trusted from the browser. `RefineRequest` accepts a `plan_token` for symmetry, but the server resolves the plan identity from the brief it already issued, and a test asserts that a browser-chosen token is neither adopted nor honoured.

### Accounting rules now held to

- One claim per real outbound attempt, including each retry.
- A request cancelled before it reaches the network costs nothing.
- A ninth attempt is refused before it is sent, not after.
- The claim is atomic, so concurrent callers cannot jointly exceed eight.
- A provider without the attempt gate, which is how the scripted test fakes are built, is charged per billed call instead.

### Test totals after this repair

| Suite | Result |
|---|---|
| `cd backend && uv run ruff format --check src tests ../scripts/scan-secrets.py` | 84 files already formatted |
| `cd backend && uv run ruff check src tests ../scripts/scan-secrets.py` | All checks passed |
| `cd backend && uv run pytest` | 448 passed (380 unit, 68 contract) |
| `cd frontend && npm run check` | 36 files checked, no fixes applied |
| `cd frontend && npm test` | 55 passed across 9 files |
| `cd frontend && npm run build` | built |
| `cd frontend && npm run test:shell` | 15 passed |
| `python3 scripts/scan-secrets.py` | exit 0 |

The backend total rose from 404 to 448. The new coverage is the five allowance scenarios, hours reconciliation across positive, negative, agreement, ambiguous, and cross-day text, the destination qualifier regressions, and both refinement purposes.

### Known limits of the hours comparison

Free-text reconciliation only reads a weekday that the sentence names, a closure, or an interval that carries an hours cue with both ends. An opening time on its own is too little to contradict an open schedule, but enough to contradict a weekday the record lists as closed. Anything else is `unverifiable` and stays unverified.

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
| Global live experience | `global-live-experience` | Created for the approved redesign. Current branch. |

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

Status: **Done** on October 4, 2026.

One bounded live retrieval saved three restaurants: Bombay Brasserie, Truffles - Indiranagar, and Chianti, Indiranagar. The visit date is 2026-10-04. The file is `backend/data/fixtures/captured/v1/scenarios/indiranagar-dinner.json`, with its checksum in that directory's manifest. Reviewer identities and phone numbers are omitted. Raw provider documents were not saved. Scoring the snapshot and scoring the reloaded fixture produced the same decision: `insufficient_evidence` and no winner. The installed model still kept no review spans. The page still scores the synthetic fixture. This capture is not wired to Find the moment.

The provider recorded 4 searches. The plan for this capture and the canonical run allowed 14. No second live request was sent.

`uv run pytest` passed, 115 tests. Ruff format and lint passed. The secret scan reported nothing for the fixture and the capture module.

Your side after this step:

1. Skim `backend/data/fixtures/captured/v1/scenarios/indiranagar-dinner.json` for names, keys, or reviewer identities.
2. Say if anything private must be removed before it is committed.

### Evaluate and optionally tune Gemma

Status: **Done** on October 4, 2026. The extraction gate did not pass. No adapter was selected.

The held-out set has 30 authored examples, and the training set has 100. They do not share text. At least 20% of the held-out examples are negative, unsupported, conflicting, or injection-oriented. The installed untuned `google_gemma-3-270m-it-Q4_K_M.gguf` was measured with temperature 0, seed 0, and one schema retry. It parsed 2 of 30 excerpts (6.7%) and scored 4 of 90 dimension-plus-polarity pairs (4.4%). The required gate is 95% parse and 80% accuracy. The two parsed excerpts still missed one pair each. Replies that failed were not valid schema JSON. The report is `ml/reports/baseline-270m.json`. The shipping artifact stays the untuned 270M file. A measured adapter is selected only if a later local held-out run improves accuracy by at least five percentage points without increasing invalid outputs.

`uv run pytest` passed, 118 tests. Ruff passed. No SerpApi search was spent.

The free Colab T4 run of `ml/tune_extraction.ipynb` finished and printed:

```text
Colab estimate parse rate 6.7%
Colab estimate dimension-plus-polarity accuracy 3.3%
```

The baseline printed in that same cell is parse rate 6.7% and accuracy 4.4%. The estimate does not meet the five-point gain, so the adapter was not saved into the repo and the shipping model was not replaced.

Your side: disconnect the Colab runtime. Nothing else for tuning.

### Deploy and smoke the sponsor vertical slice

Status: **Blocked on you** as of October 4, 2026. The model download, captured-fixture route, and live route are already on `main` at `91b7b94`. Cursor cannot create the Render services under the current autonomy.

Local evidence from this check:

- `uv run pytest` in `backend` passed, 119 tests.
- `npm test` in `frontend` passed, 7 tests.
- `python3 scripts/scan-secrets.py` passed.
- GitHub Actions run `37219473378` on `main` succeeded.
- `ml/.cache/google_gemma-3-270m-it-Q4_K_M.gguf` is present locally. A local `.env` has `SERPAPI_API_KEY` set. The shell environment does not. The value was not printed.

`render.yaml` still names branch `live-sponsor`. That branch and `main` have the same files. `HAPPEN_LIVE_ENABLED` is false in the blueprint, so the first public load uses the captured fixture. The API key is not in the blueprint.

Your side:

1. In Render, create a Blueprint from this repo's `render.yaml`. Do not create a second copy by hand. After the services exist, point both at `main`.
2. When Render prompts, set `SERPAPI_API_KEY` from the local ignored `.env`. Leave `HF_TOKEN` unset.
3. Leave `HAPPEN_LIVE_ENABLED` false for the first check. Open the frontend URL and `https://<api-host>/healthz`. Paste those two URLs back here. Do not paste the key.
4. For one bounded live run, set `HAPPEN_LIVE_ENABLED` to `true`, redeploy the API, and submit once from the public page. Then paste whether the page showed SerpApi sources, the Gemma version, and a live or captured label.
5. `happen-api` on `1c-2g` is $25/month from the existing $50 credits and does not sleep. Suspend it after the smoke check if you are not ready to leave it running. The static site is free.

---

## Complete demo experience

Branch: `demo-experience`, created when the demo polish starts.

Goal: every visible state, the evidence view, and the 1280px and 390px layouts. Planned budget: hours 14–17.

### Complete all visible result states

Status: **Done** on October 4, 2026. Not committed.

Loading says to wait for the request. An insufficient result tells the user to start over and restore the demo preset. A partial result keeps three timelines and says Unknown intervals are not a recommendation. A captured-fixture result says it is saved evidence, not a live search. Quota and invalid-input errors keep Retry off. A model-unavailable page names that dependency and retries metadata. Contract mismatch still asks for a refresh.

Checks that passed:

- `npm test` — 9 tests.
- `npm run check` and `npm run build`.
- `npx playwright test` — 16 tests, including partial, quota, invalid input, model unavailable, the fixture Hook, and the 1280 and 390 shell checks.

Your side after this step: optional. If a local page is running, trigger one error and say if the next action is unclear. The public Render deploy is still waiting.

### Finish evidence and methodology experience

Status: **Done** on October 4, 2026. Not committed.

Why this moment stays an inline panel. It shows exact quotes, underlined source links, a conflict note when one priority both supports and conflicts, the rejected-span count, the model and adapter, the scoring policy, and the planning disclaimer. Escape closes it and returns focus to Why this moment. Unsafe source addresses are not linked.

Checks that passed:

- `npm test` — 11 tests.
- `npm run check` and `npm run build`.
- `npx playwright test` — 17 tests. The new one opens the panel from the keyboard, checks the methodology, and closes it with Escape. The open panel had no serious accessibility violations.

Your side after this step: optional. Open Why this moment with the keyboard and say if the explanation is unclear.

### Finish reveal, responsive, and reduced motion

Status: **Done** on October 4, 2026. Not committed.

The three restaurant rows slide into place in under one second. The selected interval keeps its border, the word Selected, and a static amber outline. There is no glow pulse. When the browser asks for reduced motion, the rows are visible immediately and do not move. At 390 pixels the planner, recommendation, fallback, and evidence stack, and each restaurant timeline is a two-column card. At 1280 pixels the timeline stays six columns wide. Neither width scrolls sideways.

Checks that passed:

- `npx biome check .`
- `npm run build`
- `npx playwright test` — 18 tests, including 1280×720, 390×844, and reduced motion.

Your side after this step:

1. Open the local page at 1280 pixels wide, or use the layout sample at `/?layout=sample`.
2. Say if the recommended moment is obvious. The slide can be removed. The three timelines stay.

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
| Live orchestration | Done | `Serve live recommendations without substituting fixture evidence.` | Nothing. |
| Capture and verify canonical fixture | Done | `Save the sanitized Indiranagar capture and verify its replay matches the live decision.` | Skim the sanitized fixture and say if anything private must be removed. |
| Evaluate and optionally tune Gemma | Done. Baseline and Colab estimate both miss the gate. No adapter selected. | `Keep the untuned model after the adapter estimate missed the baseline.` | Disconnect the Colab runtime. |
| Deploy and smoke the sponsor slice | Blocked on Render. Code is on `main` at `91b7b94`. Local tests passed. | `91b7b94` | Create the Blueprint, paste both public URLs, then allow one live run. |
| Result states | Done locally. Not committed. | — | Optional: say if one error's next action is unclear. |
| Evidence methodology | Done locally. Not committed. | — | Optional: open Why this moment from the keyboard. |
| Responsive reveal | Done locally. Not committed. | — | Say if the recommended moment is obvious at 1280 pixels. |
| Friend walkthrough | Not started | — | Friend walkthrough. You send the paraphrase. |
| Security, performance, and pre-freeze verification | Not started | — | Read the verification list. Rotate a secret if one is found. |
| Review and freeze the MVP | Not started | — | Review and merge. That is feature freeze. |
| Production deploy, smoke, and runbook | Not started | — | Deploy, smoke the public page, name the rollback revision. |
| README, media, sessions, article, and packet | Not started | — | Read claims, approve media and sessions, keep the article as a draft. |
| Audit, publish, and submit | Not started | — | Merge, publish, submit, and paste the confirmation. |
| Global live planning contract | Recorded | `Update the contract for global live planning.` | Nothing for that record. |
| Planning prompt parser | Done. v1 API unchanged. No SerpApi or Gemma call. | `Parse planning prompts into structured briefs.` | Nothing. Do not push. |
| Destination resolution | Done. Not on a user-facing route. Provider calls are mocked in tests. | `Resolve destinations in their local time.` | Nothing. Do not push. |
| Local model quality | Done. Both measured models missed a gate. Claims stay off. | `Measure local model quality for planning.` | Nothing. Do not push. Do not commit a GGUF. |
| Global place discovery | Done in tests. Used by `POST /api/v2/plans`. Provider calls are mocked. | `Generalize live place discovery.` | Nothing. Do not push. |
| Source-backed evening plans | Done. v2 routes are live locally. The landing does not call them yet. Provider calls are mocked. | `Assemble source-backed evening plans.` | Nothing. Do not push. |
| Happen landing | Done. Customer page is the composer. Earlier planner remains on `?layout=planner`. | `Create the Happen landing experience.` | Nothing. Do not push. |
| Prompt-led planning | Done. The landing interprets, asks one question, resolves a destination, and retrieves only after Find the plan. | `Build the prompt-led planning flow.` | Nothing. Do not push. |
| Live timeline and refinement | Done. The result is a two-stop timeline. A change shows a diff before Apply. `?layout=sample` is no longer the old winner. | `Present and refine live evening plans.` | Nothing. Do not push. |
| Demo paths removed from production | Done. Production does not mount the historical recommendation routes. The customer page has no sample layout or captured-evidence action. | `Remove demo-only production paths.` | Nothing. Do not push. Do not deploy. |
| Global live planning hardened | Done. Body and prompt limits, explicit CORS, in-memory throttling, cancellation, cache bounds, and fixture isolation are covered by tests. | `Harden the global live planning workflow.` | Nothing. Do not push. Do not deploy. |
| Global live experience verified | Done. README, automated checks, secret scan, and one Jaipur live smoke. | `Document and verify the global live experience.` | Ranking fix below. Do not push. Do not deploy. |
| Rank live candidates | Done. Python compares up to five places per intent. Provider order is only the tie-breaker. | `Rank a bounded set of live candidates.` | Constraint scoring below. Do not push. Do not deploy. |
| Planning constraints | Done. Party size, budget, preferences, and accessibility reach Python scoring. Unknown evidence adds nothing. | `Apply planning constraints to deterministic scoring.` | Manual test of one evening. Do not push. Do not deploy. |

| Recomputed refinements | Done. Apply sends the whole proposed brief to the server, the cached pool is rescored without a new billed request, and a failure keeps the previous plan. | `Recompute refinements from cached evidence.` | Manual test of one evening. Do not push. Do not deploy. |

| Evidence provenance | Done. Every displayed claim carries its kind, field, safe URL, match method, and verification state. Official evidence is no longer filed as community. | `Preserve evidence provenance and useful review signals.` | Manual test of one evening. Do not push. Do not deploy. |

## Verification of the audit repairs

Final automated verification across `a679660..HEAD`. Nothing was deployed.

### The twelve audit failures, reproduced

| # | Original failure | Result now |
|---|---|---|
| 1 | Lowercase Amsterdam did not parse | `amsterdam` parsed |
| 2 | São Paulo did not parse | `são paulo` parsed |
| 3 | Ho Chi Minh City was truncated | `ho chi minh city` intact |
| 4 | `6:00 PM–11:00 PM` was not recognized | Monday open, Wednesday closed, Friday `6 PM–12 AM` open at 19:00 |
| 5 | Only the first provider result could win | Loud Room first, `quiet` selects Quiet Room |
| 6 | Constraints did not reach scoring | budget, party size, accessibility, preferences each change the score |
| 7 | "Make it quieter" did not recompute | rescore from cache, 0 new billed requests |
| 8 | Official evidence was filed as community | official stays official and keeps its safe URL |
| 9 | Reviews were fetched needlessly | reviews skipped unless a constraint needs them |
| 10 | A caller could reset the allowance | `prior_billed_requests` is a 422; repeated calls do not raise the budget |
| 11 | A forged token reached the provider | 403 `PLAN_TOKEN_INVALID`, zero provider calls |
| 12 | Copy claimed Gemma reads the request | corrected and guarded by tests |

### Commands and results

| Command | Result |
|---|---|
| `uv sync` | Resolved 51, checked 49 packages |
| `ruff format --check src tests ../scripts/scan-secrets.py` | 84 files already formatted, exit 0 |
| `ruff check src tests ../scripts/scan-secrets.py` | All checks passed |
| `uv run pytest` | **404 passed** in 9.56s |
| `python3 scripts/scan-secrets.py` | exit 0 |
| `git diff --check a679660..HEAD` | exit 0, no whitespace errors |
| `git ls-files '*.gguf'` | 0 files |
| `npm ci` | 0 vulnerabilities |
| `npm run check` | 36 files, no fixes needed |
| `npm test` | **50 passed** |
| `npm run build` | built in 320ms |
| `npm run test:shell` | **15 passed** |

### Bounded Jaipur live smoke

One run, one server-issued plan token, 43 characters long.

- Destination resolution: HTTP 200, `Asia/Kolkata`, 0 billed requests. The free
  Locations API resolved the city without a paid lookup.
- Plan: HTTP 200, outcome `planned`, **3 billed requests** of 8.
- **5 candidates compared**, 1 selected. Selection was not the first result.
- Hours evaluated on the selected stop: `open`. Sources seen: 3 Maps, 1 official.
- Cached rescore with an added preference: 0 new billed requests.

No raw payload, review text, phone number, or key was printed. The temporary
smoke script was deleted after the run and is not tracked.

### Known limitations

These are unchanged and still true.

- **The allowance store is process-local.** 512 tokens, 30-minute TTL. A restart
  clears every allowance. A second worker would hold its own copy, so the
  effective ceiling is eight per worker, not eight overall.
- **`quiet` stayed `unknown` in the live smoke.** Jaipur evidence did not verify
  it. That is the correct outcome, not a failure: unknown evidence adds nothing
  and no stop is presented as verified without a source.
- **Price was absent** on the selected live place, so budget stayed unknown.
- **No model runs in the customer path.** The pinned Gemma artifact remains
  measured, gated, and disabled.
- **This branch is not deployed** and has never been pushed.
- Travel time between stops stays unverified until a source states it.

### Next action

**Independent repair audit.** Not deployment, not manual testing.


## Public claims and measured behavior

Every shipped sentence about the model now matches `ml/reports/model-quality.json`.

### What runs in the customer path

Deterministic local parsing reads the prompt. SerpApi supplies live place
evidence. Python does feasibility, scoring, and selection. No model loads.

### What was experimentally evaluated

Local open-weight Gemma, measured on held-out planning and review sets. The
artifact, dataset, gates, and numbers are committed, so the evaluation is
reproducible.

### What failed its gate

Both candidates. The pinned 270M model parsed 22 of 24 planning examples
(0.9167, gate 0.95) and reached 0.6667 essential-field accuracy (gate 0.90). On
30 held-out review examples it parsed 2 (0.0667) with 0.0444
dimension-polarity accuracy (gate 0.80). The 1B candidate passed the schema gate
but reached 0.7917 essential-field accuracy and 0.6778 review polarity.
`claims_enabled` is false and the fallback is `deterministic_parser`.

### What SerpApi and Python actually do

SerpApi is the only place-data source. Python scores from retrieved evidence
only; unknown evidence adds nothing.

### Corrections made in this step

- The landing footer claimed "Gemma runs locally to read the request." It now
  states deterministic parsing, Python selection, and that the measured model
  stays switched off.
- `README.md` section "What Gemma does, and what Python decides" became "What the
  customer path actually runs."
- The DEV challenge story was split into the five subsections above.
- The README claimed a refinement gets a fresh cap of eight. It reuses the same
  plan token, so it shares one allowance; only a deliberately new plan gets a new
  cap.
- `GET /api/v1/meta` gained `planning_reader` and
  `planner_model_in_request_path`. `model_status` reports whether the artifact
  matches its checksum, which a reader could otherwise mistake for a model in the
  request path.
- `docs/HANDOFF.md` section 30 is the approved contract and keeps its permissive
  "may" language. It was not rewritten here.

### Guards

- `frontend/src/app/landing/Landing.test.tsx` asserts the corrected trust
  statement and rejects the old sentence.
- `backend/tests/unit/test_public_claims.py` reads the shipped README, landing
  copy, and docs as a reviewer would, and fails if a banned claim returns. It
  also asserts the quality report still records the failure, so the report cannot
  be edited into a pass.


## Plan allowance

The eight-request budget is counted on the server, not reported by the caller.

Reading a prompt issues an opaque `plan_token`. The token is 32 random bytes,
URL-safe, and means nothing to the client. Both billed routes require it:

- `POST /api/v2/destinations/resolve`
- `POST /api/v2/plans`

`PlanRequest.prior_billed_requests` is gone. It was a trusted field: a client
could send zero and reset its own budget.

### Accounting rules

- The store holds one allowance per token: `spent` and `reserved`.
- Each billed call claims one unit **before** it reaches the provider, under a
  lock. A claim that does not fit raises the provider's own
  `CREDIT_BUDGET_EXCEEDED`, so discovery and destination resolution stop
  gracefully instead of failing.
- On success, the claim becomes spent.
- On failure, the exception carries `billed_requests`, the number of requests
  the client actually sent. A retry that reached the network stays charged; a
  call cancelled before sending refunds its claim and consumes nothing.
- The free Locations API is not in the metered set. It never consumes budget.

### Why reserve before sending

Two simultaneous requests sharing one token would each pass a naive
read-then-write check and jointly exceed eight. Because a claim is taken under
the same lock that reads the total, the second caller sees the first claim and
stops. `test_two_simultaneous_plans_cannot_exceed_eight` runs two threads
against one token and asserts the total never exceeds the limit.

### Refinement rule

A refinement keeps the same token and the same allowance, so a cached
recomputation spends nothing. **A refinement that is treated as a new submitted
plan must be issued a fresh token deliberately** by re-reading the prompt; the
server never hands out a second allowance implicitly.

### Limitations, stated honestly

The store is process-local and bounded: 512 tokens, 30-minute TTL. A restart
clears every allowance, and a second worker would hold a separate copy. That is
a known limitation, not a hidden one. Adding a database is out of scope for
this project.

### Response shape

`DestinationResolution` and `EveningPlan` both carry `billed_requests` (the
plan-local real count) and `remaining_requests`. The landing page reads these
and keeps no counter of its own.

| Server-side plan budgets | Done. A prompt issues an opaque token. Both billed routes require it, atomic claims stop concurrent requests from jointly exceeding eight, and the caller no longer reports its own count. | `Enforce plan budgets on the server.` | Manual test of one evening. Do not push. Do not deploy. |

| Public claims aligned | Done. The landing, README, metadata, and submission guidance match the measured report. The model is described as measured and disabled. | `Align public claims with measured behavior.` | Read the README once more. Do not push. Do not deploy. |

| Repairs verified | Done. All twelve audit failures reproduced as fixed. 404 backend, 50 frontend, 15 shell tests pass. One bounded Jaipur smoke spent 3 of 8 billed requests and compared 5 candidates. | `Verify the repaired global planner.` | Independent repair audit. Do not push. Do not deploy. |

## Verification of the decision-ready evening experience

This step audited the whole branch, repaired two real defects, added regression
tests for them, and ran every command in the README test list. It spent zero
SerpApi credits and staged nothing under `.github/hooks/`.

### Two defects this audit found and fixed

Two backend defects were found by reading and by direct probe. A third, in the
frontend, was found only by running the suite repeatedly.

| Defect | What was wrong | Proof | Fix |
|---|---|---|---|
| Destination seconds applied to every route | `_metered` gave every metered client the destination-stage cap, so `/api/v2/plans` limited each SerpApi attempt to 6.0s instead of 8.0s. | A probe printed `cap=6.0 want=8.0 WRONG` for `/api/v2/plans` and `cap=6.0 want=6.0 OK` for `/api/v2/destinations/resolve`. | `_metered` takes an `attempt_cap`. The plans route passes `SEARCH_SECONDS`; the destination route passes `DESTINATION_SECONDS`. Both routes now report the cap the contract names. |
| A stage started even when it could not finish | `_StageScope.__enter__` computed `exhausted` and then discarded it, so a stage began with too little budget left and ran to completion anyway. | Six 2.5s stages finished at 15.0s against a 14.0s budget. | `can_start()` refuses a stage with less than `_MIN_USEFUL_SECONDS` remaining, and `__enter__` raises `DeadlineExceeded` instead of returning a scope. The overrun is now bounded to at most 1.0s, which is the one stage already in flight when the budget ends. |

Both defects were silent: tests passed while the behaviour was wrong. That is
why `test_the_plans_route_uses_the_search_stage_cap` and
`test_a_sequence_of_stages_cannot_run_past_the_planning_deadline` now exist.

### A third defect this audit found: a lost answer

| Defect | What was wrong | Proof | Fix |
|---|---|---|---|
| The first follow-up answer could be wiped before it was sent | An effect cleared `answerDraft` whenever `question` changed, including the very first time the question appeared. React may flush that effect after the field is already on screen and after an answer has been typed, so the typed answer was erased and the submit button stayed disabled. The click did nothing and the visitor was asked the same question again. | The follow-up test failed roughly 1 run in 28. The captured DOM showed the real cause: the input had `value=""` and the `Answer` button had `disabled=""`, which is the exact state after the draft is cleared, not a slow render. | The effect clears the draft only when the question actually differs from the one already shown, tracked in a ref. The draft starts empty, so the first question never needed clearing. |

The bug was intermittent because it depends on when React flushes the effect,
so a single green run proved nothing. It reproduced 1 run in 28 in isolation and
did not reproduce at all when the suite ran alone on an idle machine. It was
found by running the suite 20 times and accumulating output, then 28 more times
in isolation to confirm the rate. After the fix, 40 consecutive runs of the
follow-up tests failed zero times.

The new test also asserts the typed answer reaches the server body, so the
defect cannot come back silently.

### What was verified, and how

| Check | Command | Result |
|---|---|---|
| Formatting | `uv run ruff format --check src tests ../scripts/scan-secrets.py` | 86 files already formatted |
| Lint | `uv run ruff check src tests ../scripts/scan-secrets.py` | All checks passed |
| Backend tests | `uv run pytest` | 464 passed |
| Secret scan | `python3 scripts/scan-secrets.py` | clean, exit 0 |
| Frontend lint | `npm run check` | 36 files, no fixes needed |
| Frontend tests | `npm test` | 62 passed across 9 files |
| Frontend build | `npm run build` | built in 220ms |
| Shell tests | `npm run test:shell` | 21 passed, axe included, 1280px and 390px |

Contract items re-checked by reading the code, not by trusting the log: the
allowance is claimed at the outbound-attempt boundary so a retry that reaches
the network stays charged and a cancelled attempt costs nothing; the ninth
attempt is refused before the send; a `follow_up` keeps the caller's token and
allowance; a `plan_refinement` is issued a fresh token and the old one is
forgotten; hours agreement is not a conflict; and `model_claims_enabled()` still
returns false because the measured parse rate is 0.0667.

The production bundle was inspected directly. It contains no key, no host, no
fixture marker, and no development-only copy. The only occurrences of the string
`password` are React DOM's own input-type tables.

### Behaviour that does not exist

These were requested in conversation and are **not** in the product. The API
surface is `/briefs/interpret`, `/destinations/resolve`, `/plans`,
`/plans/refine`, `/healthz`, `/api/v1/meta`, plus the historical recommendation
routes that only a development process mounts.

- **No swap endpoint.** There is no way to change a stop after the plan is built.
- **No cached alternatives.** A plan response carries no runner-up and no
  alternative stop, so there is nothing to fall back to.
- **No why-won comparison.** The response carries no reason one stop beat
  another. Python picks; the page shows what was picked.
- **No calculated arrival, no departure time, no travel duration.** The timeline
  is the local start time and then each stop's own hours. The second stop says
  "A separate arrival was not planned for this stop."
- **No route mode, distance, or duration.** `PlanTransition` carries only the
  from-stop, to-stop, an `unverified` status, and a directions URL.
- **Warm p50 and p95 against live SerpApi are unmeasured.** The benchmark script
  is fixture-only and prints that warning itself.

### Remaining user-owned work

Nothing below was done here, and none of it can be done from this repository
alone.

1. Run the app locally and plan one real evening end to end. Read the brief, the
   timeline, and the diff as if you had never seen the code, and note anything
   you cannot explain.
2. Watch the network tab and confirm a single submitted plan sends at most eight
   billed requests, and that resubmitting the same evening sends none.
3. Try the follow-up path. A question about the plan must keep the same token
   and spend nothing. "Review this change" must produce a new plan with its own
   eight.
4. Optional, and only with approval: spend a few credits to measure real warm
   p50 and p95 for one destination. The fixture benchmark cannot tell you this.
5. Walk a friend through it and write down what they say is unclear.
6. Record a short demo. Keep it to one evening, one question, one change.
7. Review the diff, then decide separately whether to push, open a pull request,
   deploy, or publish. None of that was done here.
