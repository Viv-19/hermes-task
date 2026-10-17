# Hermes Email Assistant

A review-first web app for **Hermes Travel & Cargo Pvt Ltd**. Click **Send email**, paste a customer email, and watch the assistant:

1. route it (**router agent**) to one of six categories — Freight Quotation Enquiry · Shipment Status · Documentation · Payment · General Business Email · Other,
2. load that category's skill and let the **skill agent** extract the details (for freight: origin, destination, commodity, gross weight + unit, pieces, dimensions / CBM, Incoterm, cargo-ready date, and the mode **AIR / OCEAN / UNKNOWN** — never assumed from the route),
3. **validate** everything with plain Python (nothing is invented; missing, ambiguous and conflicting details are listed),
4. draft a reply for a human to **Approve or Reject**.

**No email is ever sent and no mailbox is connected.** "Send email" simulates a customer email arriving; "Approve" only updates the dashboard (it is a simulation). Only sample data is used.

## The dashboard

* **Left sidebar** — Dashboard plus one page per category (Freight, Shipment status, Documentation, Payment, General, Other), with pending counts.
* **Dashboard** — counters (Received, Pending, Approved, Rejected, each with **Last 24 h** and **Total**) and the **latest emails across all categories**.
* **Category pages** — the workflow of that category's latest email and a **history of its last five emails** (green = approved, red = rejected, amber = pending). Lists never show the full draft; click a row to open it.
* **Send email** (top right) opens a popup. After **Analyse**, the **live workflow runs inside the popup** — Email received → Router agent → Classified → Skill loaded → Skill agent → Validation → Draft ready — and then you choose **Go to dashboard**, **Review draft** or **Analyse another**.
* **Review drawer** — full editable draft, what needs attention, extracted fields with their quotes from the email, the workflow with timings, then **Approve** / **Reject** (optional reason) / Undo. Decided drafts are locked until you reopen them.
* Day / night theme, Hermes logo, phone-friendly layout.
* If every AI model fails, a red **"OpenRouter API is not working"** banner names the failing step and lists each model's error, with Retry.

All dashboard data lives in the browser (`localStorage`), so counters are per browser.

## Run it locally

Requires Python 3.11+.

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env   — then put your key in .env
uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>.

No key yet, or saving the free-model quota? Run in **mock mode** — canned answers replayed as a real workflow, zero API calls:

```bash
set MOCK_LLM=1                    # macOS/Linux: export MOCK_LLM=1
uvicorn app.main:app --reload
```

Run the tests (no network needed): `python -m pytest -q`

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | – | OpenRouter key. **Server-side only**; never sent to the browser, never committed (`.env` is git-ignored). |
| `MODEL_CHAIN` | see `.env.example` | Comma-separated models, tried in order. |
| `ROUTER_MODE` | `two_stage` | `two_stage` = router agent, then the chosen skill (2 AI calls per email, real step-by-step workflow). `single` = one call with all six skills. |
| `LLM_TIMEOUT_S` / `LLM_DEADLINE_S` | 40 / 85 | Per-model timeout / total time for one stage's model chain. |
| `LLM_MAX_TOKENS` / `LLM_ROUTER_MAX_TOKENS` | 4000 / 600 | Output budgets. |
| `MOCK_LLM` / `MOCK_DELAY_S` | 0 / 0.7 | `1` = canned answers, OpenRouter is never called; pause between mock workflow steps. |
| `MAX_BODY_CHARS` | 8000 | Longest email accepted. |
| `RATE_LIMIT_PER_MIN` | 10 | Analyses per minute per IP. |

## Deploy free on Render, with CI/CD from GitHub

**One-time setup**

1. Push the repo to GitHub (done: `Viv-19/hermes-task`).
2. Render dashboard → **New → Blueprint** → connect the GitHub repo (allow Render's GitHub app to see a private repo) → Render reads `render.yaml` → when asked, paste `OPENROUTER_API_KEY` → **Apply**. The first deploy starts by itself (about 3–5 minutes).
3. Open the service → **Settings → Deploy Hook** → copy the URL (it is a secret).
4. GitHub repo → **Settings → Secrets and variables → Actions**:
   * **Secrets** tab → *New repository secret* → name `RENDER_DEPLOY_HOOK_URL`, value = the hook URL.
   * **Variables** tab → *New repository variable* → name `RENDER_URL`, value = your service URL, e.g. `https://hermes-email-assistant.onrender.com`.

**Every change after that**

```bash
git add -A
git commit -m "what you changed"
git push
```

`.github/workflows/ci-cd.yml` then runs automatically: **tests → deploy to Render → wait until the new commit is live** (`/api/health` reports the commit). A red run means the tests failed (nothing is deployed) or the new version did not come up. Pull requests only run the tests.

Manual setup instead of a Blueprint: **New → Web Service**, build `pip install -r requirements.txt`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health check `/api/health`, auto-deploy **Off**, plus the `OPENROUTER_API_KEY` environment variable.

Free Render services sleep after ~15 minutes of inactivity and take about a minute to wake up — open the URL a few minutes before a demo.

## How it works

```
Send email ─▶ POST /api/analyze/stream  (newline-delimited JSON events, one per step)
              │
              │ received
              │ router_start ─▶ ROUTER AGENT: sees only each skill's name + description ─▶ router_done (category)
              │ skill_loaded ─▶ loads ONLY that skill's Markdown (skills/<name>.md)
              │ skill_start  ─▶ SKILL AGENT: extracts fields (with quotes) and drafts the reply ─▶ skill_done
              │ validation   ─▶ Python checks (no AI): grounding, mode, missing info, rules, draft guard
              ▼ done(result)        ... or error(stage, code, attempts)

Browser: workflow stepper (live, in the popup) ─▶ dashboard / category page ─▶ history row ─▶ drawer ─▶ Approve / Reject
```

* **Skills** (`skills/*.md`): one Markdown file per category with frontmatter (`name`, `category`, `description`) and instructions (fields to extract, reply policy, "never" rules). They are read on every request, so **editing a skill changes behaviour with no code change or restart**.
* **Two AI calls per email** (router, then skill). The model that answered the router is tried first for the skill stage, so an overloaded model is not retried every time. Identical emails are answered from an in-memory cache (shown as "from cache").
* **Models** (OpenRouter, all free): `nvidia/nemotron-3-ultra-550b-a55b:free` first, then `nvidia/nemotron-3-super-120b-a12b:free`, `google/gemma-4-31b-it:free`, `nvidia/nemotron-3.5-super-vl:free`. A model is skipped on rate limit, overload, timeout, empty reply or unusable JSON. Free models are often overloaded — the workflow view shows which model answered.
* **State** lives in the browser (`localStorage`) — free hosts have ephemeral disks and the brief needs no persistence.

### Validation (`app/validators.py`)

| Check | What it does |
|---|---|
| Grounding | Every extracted value needs a quote that really appears in the email; numbers must match their quote. Unsupported values are removed and reported. |
| Mode | AIR / OCEAN from explicit wording only (`air freight`, `AWB`, `FCL`, `40HC`, `B/L`…, tolerant of typos like "frieght"). Route/city/port never decides it. Both → UNKNOWN + conflict. |
| Missing info | Computed from a required-field table per mode (AIR, OCEAN-FCL, OCEAN-LCL, UNKNOWN) — not guessed by the AI. Urgency adds a "delivery deadline" ask; pharma/chemicals/batteries add a "special handling" ask. |
| Rules | Weight units, several different weights (conflict), Incoterms 2020 list, sea-only Incoterm with air freight, no invented year, past dates. |
| Prompt injection | Email text is treated as data; "ignore previous instructions"-style text is flagged and no reply is drafted. |
| Draft guard | A draft with a price, transit-time promise, "attached", shipment/payment status claim, or that forgets to ask for a required missing item is replaced by a safe template. |

`information_verified` and `action_available` are always **false** — no tracking, pricing, accounting or document system is connected — and the UI says so.

## Project layout

```
app/        main.py (API + stream) · pipeline.py (workflow events) · llm.py (OpenRouter + fallback) · validators.py · skills.py · schemas.py · mock.py · config.py
skills/     six Markdown skills
static/     index.html · styles.css · app.js · assets/hermes-logo.png
samples/    emails.json (4 assessment tests + 10 edge cases)
tests/      pytest — validators, API, workflow (all in mock mode / fake OpenRouter)
```

## Limitations

* Free models are rate limited (**50 requests/day** unless the OpenRouter account has bought ≥ $10 of credits; 20/minute) and sometimes overloaded or slow. Two-stage mode uses 2 requests per email (about 25 emails a day); `ROUTER_MODE=single` uses 1.
* No real rates, tracking, accounting or documents — replies only acknowledge or ask for information.
* Dashboard data is per-browser (`localStorage`), not shared between users or devices.
* Evidence matching is textual: the AI could quote real text and still misread it, so a human reviews every draft.
* Mixed-intent emails are only flagged when the AI notices; prompt-injection defence is mitigated, not guaranteed.
* Tested mainly on English emails.

## Versions

* `v2.2` — the workflow shows which model is picked (live "trying …", failures and fallbacks, model + time per agent); GitHub Actions CI/CD with automatic deploy to Render.
* `v2.1` — sidebar navigation, full-width layout, Dashboard of the latest emails, workflow runs inside the Send email popup, much less on-screen text; replies greet the sender by name and ask for an exact date when the ready date is vague.
* `v2.0` — Send email modal, 24 h / total counters, live router→skill workflow, last-5 history, review drawer with Approve / Reject / Undo.
* `v1.0` — single-page analyser, model chain, validation layer, six skills, tests.

See `hermes_email_assistant_plan_v2.md` for the design plan and roadmap.
