# Agent notes

`docs/HANDOFF.md` is the product contract. `docs/HANDOFF2.md` is the progress log. This file cannot override either one.

- Python is the only backend language. The frontend is React and TypeScript.
- SerpApi is the only external place-data provider. Gemma extracts evidence. Python scoring chooses the recommendation.
- Do not add a paid service, a database, authentication, or another model API.
- Keep secrets in an ignored `.env` file. Do not print them or commit them.
- Do not commit `*.gguf` files. Download the pinned model with `python scripts/download-model.py`.
- The public quantized model does not need `HF_TOKEN`. Do not call a hosted inference API.
- One branch per phase. Branch names, commit messages, and code comments do not use phase or step numbers.
- Do not push, deploy, or publish unless the user asks.
