---
title: Arun plans every evening like a research paper. So I built him a planner that is allowed to say it doesn't know.
published: false
tags: devchallenge, weekendchallenge, hf26challenge
cover_image: https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/cover.png
---

*This is a submission for the [Hacktoberfest Weekend Challenge: Build for a Friend](https://dev.to/challenges/hacktoberfest-weekend-2026-10-01)*

## What I Built

Arun is the friend who plans. I am the friend who says "anything is fine" and then has opinions later.

He has a system. Ten Google Maps tabs. A screenshot of opening hours that might be from last year. A chatbot paragraph that reads finished. Last month he asked one for drinks in Lisbon, for two, around nine. It came back in seconds: three bars, a note about the lighting, a walking time nobody had measured. One of those bars was shut that weekday. Arun still went, because the answer had sounded sure of itself.

What got me wasn't that the answer was wrong. It was that there was no way to tell which parts anyone had actually checked.

So I spent the weekend building him a planner that is allowed to say "I don't know."

**Happen** takes one evening, written the way you'd text a friend, and returns one plan where every claim is either sourced or visibly blank.

You type something like:

> Drinks in Lisbon on Friday at 9 for two.

Then three things happen.

1. **Describe.** You write the evening in your own words.
2. **Review.** Happen turns it into a short brief: place, date, time, stop order, group size. If something essential is missing or ambiguous, it asks exactly one question. Every field is editable before anything gets searched.
3. **Plan.** You press **Check live places**. Happen searches live listings, checks the opening hours for *that* day against *your* time, and picks at most two stops.

![Happen landing: type an evening, or pick a starter like drinks in Lisbon](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/landing.png)
*The landing. One box, three starter evenings, and three promises: live listings, feasibility first, no hidden guesses.*

That middle step matters more than I expected, and the screenshot below is the reason I trust it.

![Review step before any search: the brief on the left, what happens next on the right](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/review.png)
*Review, mid-build. The brief on the left had resolved "at 9" to 9:00 AM and "Friday" to Wednesday. Nothing had been searched yet, so the mistake cost nothing.*

I'm showing that screenshot because it caught a real bug, not because it flatters the product. That build read "at 9" as 9 in the morning and "Friday" as the coming Wednesday, then carried both forward without complaint. A planner built on "never claim what you didn't check" was quietly inventing two of its own fields.

So the parser now treats a bare time as ambiguous and stops to ask, rather than picking one:

> What time should the evening start? — **09:00** or **21:00**

Nothing is billed until Arun answers. That one fix is most of the difference between a confident plan and a true one.

Each stop then shows its time, why it was chosen, the listing details, and one line most planners never show you:

**Couldn't confirm.**

If the listing doesn't say whether a place seats two, Happen doesn't guess. If that day's hours are missing, the stop doesn't get the benefit of the doubt. Missing evidence never counts in a place's favour.

![A finished Lisbon plan: Agave Cocktail Lab at 9pm, open, with one Couldn't confirm line](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/plan.png)
*A finished plan. One stop, open at 9, live listings retrieved at 4:30 AM GMT+1. Couldn't confirm: price, current crowd level, or seating for two.*

Note the date in that screenshot is the Wednesday, carried over from the same mid-build parse. The lookups, the hours check, the evidence, and the blank line are all real; only the date was wrong, and only for that one run.

**View sources** opens what was checked, the planned day's hours, the links, and a full audit with the time each fact was retrieved. If Arun wants to know why Ágave made the cut, the answer is a link rather than a paragraph about the ambience.

And if the plan isn't right, he types the change and chooses **Review this change**. The current plan stays on screen until he presses **Apply**.

### What it deliberately doesn't do

I cut a lot on purpose, and I'd rather say so than let a screenshot imply otherwise:

- One evening, two stops at most.
- No travel time. A second stop shows its own hours and a directions link, not a made-up arrival.
- No live crowd levels, reservations, or price conversion. Those three are exactly what this Lisbon plan refused to invent.
- No accounts, no saved history, no database. Close the tab and it's gone.

### Handing it over

I sent Arun the live URL and asked him to plan the Lisbon evening himself. He typed the prompt, answered the 9 PM question, changed nothing else, and pressed **Check live places**.

He read the Ágave card twice. The thing he pointed at first wasn't the five-star rating. It was the last line.

> "Okay. So it's open at 9, and it's not pretending to know the price. That's actually useful. I keep getting paragraphs. I wanted the gap."

He got the distinction without me explaining it. **Why it fits** is what the listings supported: hours covering 9 PM, an official site, a Maps rating. **Couldn't confirm** is what they didn't: price, how busy it is right now, seating for two. He said he'd still go, and that he'd text the bar about a table, which is the decision Happen is supposed to leave with him.

What confused him was there being only one stop. He expected a second place, because the landing page says up to two. I gave him the honest version: a second stop only appears if a second place also clears the hours check. Happen won't pad the evening to look complete. His response was that this belongs on the result screen, not just in my explanation. He was right.

## Demo

**Try it:** [happen-web.onrender.com](https://happen-web.onrender.com/)

Type an evening, or tap one of the three starters. **Drinks in Lisbon on Friday at 9 for two** is the one in the screenshots.

No login. The first search spends live SerpApi credits; asking for the same evening again within 15 minutes doesn't.

## Code

{% github kernelKain/happen %}

MIT licensed. Python backend (FastAPI), React and TypeScript frontend.

## How I Built It

Here's the path one evening takes:

```plaintext
"Drinks in Lisbon on Friday at 9 for two."
   │
   ▼
Brief  ── place, date, time, stop order, group size
   │       (one question if something essential is missing or ambiguous)
   ▼
SerpApi ── Google Maps listings, official sites, community text
   │       (hard cap: 8 billed requests per plan, 15-minute cache)
   ▼
Python checks ── open on that day at that time?
   │              does the listing support what was asked for?
   │              missing evidence = no credit
   ▼
One plan, at most two stops
   ├── why each stop was chosen
   ├── one "Couldn't confirm" line per stop
   └── sources + audit with retrieval times
```

**SerpApi is the only data source.** Every fact on screen traces back to a Google Maps listing, an official website, or community text that SerpApi fetched. The server counts billed requests and refuses the ninth one before it's sent, so a single plan can never cost more than eight. A retry that actually reaches the network stays counted; a cancelled one costs nothing. Identical searches are cached for 15 minutes.

**Python makes the call, not a model.** Scoring is plain code you can read. It checks feasibility (is this place open at 9 PM that day?) and evidence (does anything actually say this place fits?). Where two sources agree on hours, that's agreement, not a conflict. Where they disagree, you see it.

**Every claim carries its receipt.** Each fact has a source link and a retrieval time. The "Couldn't confirm" line is generated from what was *missing*, not picked from a template. On this plan it's price, crowd, and seating for two, because the listings never said those things.

### The open model, and the result I didn't expect

This is the part I want to be straight about, because it's the most interesting thing that happened all weekend.

The original design had **Gemma** reading the messy text, the community reviews, and the user's prompt, then handing structured evidence to the Python scorer. I picked Gemma 3 270M because it runs on CPU on the same box as the API, with no GPU and no hosted inference. It runs locally through `llama.cpp`, from a public quantized build, pinned to an exact revision and verified by SHA-256 before it loads. Temperature 0, fixed seed, so the same input gives the same output.

Then I did the thing you can really only do with an open model: I measured it myself, on my own task, before letting it anywhere near the product.

I wrote a held-out set (30 review excerpts, 24 planning prompts) and set gates the model had to clear before any of its output could reach a user:

| Gate | Required | Gemma 3 270M | Gemma 3 1B |
|---|---|---|---|
| Valid JSON on review extraction | 95% | **6.7%** (2 of 30) | 100% |
| Right dimension and polarity on reviews | 80% | **4.4%** | 67.8% |
| Valid JSON on planning prompts | 95% | 91.7% | 100% |
| Essential planning fields correct | 90% | 66.7% | 79.2% |

The 270M model mostly couldn't produce valid JSON for my schema. So I tried to fix it the way open weights let you: 100 training examples, no text shared with the held-out set, and a short QLoRA adapter trained on a free Colab T4. It came back at 6.7% parse and 3.3% accuracy — *worse* than the untuned model. My rule was that an adapter ships only if it beats baseline by five points without adding invalid output, so it didn't ship. With about eight hours left, I asked my agent whether to pivot the whole project. It said no: the product was already built to refuse when evidence is thin, so a weak model makes it quieter, not wrong.

The 1B model was a real step up. About 1.3 GB of memory, under a second to load. But it still got review polarity wrong about a third of the time, and for a product whose entire promise is "we only tell you what we checked," a model that's wrong a third of the time about whether a review is positive is worse than no model.

So it ships **gated off**, and the gate is code rather than a promise. There's a checked-in quality report (`ml/reports/model-quality.json`). At startup the backend hashes the model file and compares it against the hash in that report; model-derived claims are only permitted if the report for *that exact file* says it passed. Right now it says it didn't, so a deterministic parser reads the prompt instead, and the health endpoint openly reports `model_claims_enabled: false`.

I wanted to write "Gemma powers Happen." Better headline. But building a tool about not overclaiming and then overclaiming in the write-up felt wrong. What I can say is that the open model shaped the design: it's the reason there's a schema, a validator, a held-out set, and a gate at all. The moment a Gemma build clears those gates, turning it on is a config change.

### How I worked

I built this over the weekend in Cursor, with Grok 4.7 High as my coding agent. I wrote the product contract first — what it does, what it must never claim, what the request budget is — and checked every change against it.

I used **Entire** to checkpoint the agent sessions into the git history, so the reasoning sits next to the code it explains. The public log is here: [entire.io/gh/kernelKain/happen/sessions](https://entire.io/gh/kernelKain/happen/sessions).

![Entire dashboard for Happen: 31 checkpoints, 8 PRs merged, token usage over the weekend](https://raw.githubusercontent.com/kernelKain/happen/main/docs/press/entire.png)
*The weekend on Entire. 31 checkpoints across 62 commits, 8 PRs merged, about 5.7 million tokens. The spike is October 4th, when the live planner and the evidence-first UI landed.*

What the test suite covers right now:

- 466 backend tests, all on mocks and captured fixtures. They never spend a SerpApi credit.
- 68 frontend unit tests.
- 22 Playwright tests at 1280px and 390px, with automated accessibility checks (axe) on each one.
- A secret scanner across the whole tree, plus a check of the production bundle for keys, hosts, and test fixtures.

One bug I'm quietly pleased about catching: a typed follow-up answer was occasionally cleared before it was sent. It failed roughly 1 run in 28, and never when the test ran alone on an idle machine. I only found it by running the suite dozens of times and tallying failures. After the fix it passed 40 runs in a row, and the test now asserts the typed answer actually arrives in the request body, so it can't creep back in.

## Why Does Open Innovation Matter?

**Because I could check the model instead of trusting it.** With open weights I downloaded the exact file, pinned its hash, ran it on my own laptop, and scored it against my own task. A closed API would have given me a good demo and a changelog. It wouldn't have let me prove, file by file, that the thing running in production is the thing I tested — and it certainly wouldn't have told me this precisely that the model wasn't ready.

**Because "no" was an option.** With a hosted model, the model *is* the product, and if it isn't good enough you're stuck. Here it's one swappable piece behind a gate. When the 270M failed I tried the 1B by changing a few lines of config. When a larger Gemma clears the bar, it's the same change. No vendor, no new contract, no new API key.

**Because it costs nothing to run.** The model shares a CPU with the API. There's no per-token bill, which matters for something I want to hand to a friend and leave running.

**Because the evidence trail is open too.** The scoring, the request cap, the quality report, and the gate are all in the repo. If you don't believe a plan, you can read exactly how it was made.

And because the open path was measurable in a way a hosted one wouldn't be. Gemma ran locally on a CPU, fine-tuned on a free Colab T4, and scored against gates I wrote myself. That's the whole reason the model section above exists at all.

What did open cost me? Quality, at this size. A large hosted model would probably have cleared my gates on day one. But I'd have had no way to keep checking it, and no way to know when it quietly changed underneath me.

## My Agent Session

I made the product calls: two stops at most, missing evidence never helps a place, eight requests per plan, and shipping the model gated off rather than pretending otherwise. The agent wrote and tested most of the code against that contract.

The session I'd point a judge at is the one where the model failed. It walks through running the QLoRA notebook on a free Colab T4, getting 6.7% parse and 3.3% accuracy back, and then asking, with eight hours left, whether the project should be thrown away. The answer was to keep the refusal behaviour, stop tuning, and ship the deploy.

The full checkpoint trail is on Entire: [entire.io/gh/kernelKain/happen/sessions](https://entire.io/gh/kernelKain/happen/sessions).

## Prize Categories

I'm entering four.

- **Best Use of Gemma.** Gemma is the open-weight model at the centre of this build. I download a pinned public quantized build of Gemma 3 270M, verify its SHA-256 before load, run it locally through `llama.cpp` on CPU with no hosted inference, and QLoRA fine-tuned an adapter against it on a free Colab T4. Every one of those steps is only possible because the weights are open.
- **Best Use of SerpApi.** SerpApi is the only data source in Happen. Google Maps listings, official websites, and community text all come through it, and every fact in a plan links back to the SerpApi result it came from, with a retrieval time. The server enforces a hard budget of eight billed requests per plan — the ninth is refused before it's sent — and caches identical searches for 15 minutes.
- **Best Use of Entire.** Agent sessions were checkpointed with Entire throughout the build. The public log is [here](https://entire.io/gh/kernelKain/happen/sessions). This weekend: 31 checkpoints, 8 merged PRs, and the reasoning sitting next to the commits it produced.
- **Best Use of Render.** The live app is [happen-web.onrender.com](https://happen-web.onrender.com/). Frontend as a static site, backend as a Python web service in Singapore, both defined in `render.yaml` and deployed from `main` only after checks pass. The SerpApi key lives in the Render dashboard, never in the repo. The backend build downloads the pinned Gemma file and verifies its hash on Render, with no Hugging Face token and no hosted inference.

---

*Built for Arun, who now has one fewer reason to open ten Maps tabs and still end up at the usual place.*