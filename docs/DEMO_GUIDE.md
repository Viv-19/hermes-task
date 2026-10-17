# Demo guide

Your cheat sheet for the final review: what to say, what to click, where things are in the code, and how to make a live change.

## 1. The 60-second pitch

> Hermes gets many emails. This tool reads one, decides what it is about, pulls out the freight details, shows what is missing, and drafts a reply. A person approves or rejects it. It never sends email.
>
> The AI reads and writes. Plain Python checks everything the AI says: every detail must be quoted from the email, the mode is never guessed, and what is missing comes from a fixed list.

## 2. The 5-minute demo

1. **Open the site.** Show the Dashboard: counters (last 24 hours and total) and the latest emails.
2. **Send email → Test 1 → Analyse.** Say what you see in the workflow:
   - "The **router agent** picks one of six categories."
   - "Then only that category's **skill** is loaded, and the **skill agent** extracts and drafts."
   - "The steps show **which model** answered. If a model is busy, it is skipped and the next one is used."
   - "Then **plain Python validates** the result."
3. **Review draft.** Walk down the panel: classification → mode AIR ("from 'air freight'") → extracted fields with quotes → missing (dimensions, Incoterm) → the reply.
4. **Test 4 (the ambiguous one).** Mode is **UNKNOWN** on purpose. "Urgent" is not a date. Pharma triggers a question about temperature control.
5. **Test 3.** It is **Documentation**, not freight, even though it mentions a shipment.
6. **Their unseen email.** Run it. Show what is found, missing and unclear.
7. **Approve one, reject one.** Show the counters and the green and red rows. Open a category page.
8. **CI/CD.** "Every `git push` runs the tests, then deploys to Render."

## 3. Where each requirement lives

| The brief asks for | Where it is |
|---|---|
| Subject and body input | `static/index.html` (form), `static/app.js` (`onAnalyzeClick`) |
| Six categories | `app/schemas.py` (`CATEGORIES`), router prompt in `app/skills.py`, instructions in `skills/*.md` |
| AIR / OCEAN / UNKNOWN | `app/validators.py` → `detect_mode`, `_AIR_PATTERNS`, `_OCEAN_PATTERNS` |
| Field extraction | field list in `skills/freight_quotation.md` and `app/schemas.py` (`FIELDS`); checked in `validators._clean_fields` |
| Missing, ambiguous, conflicting | `validators.compute_missing`, `_freight_checks`, `detect_mixed_intent` |
| Unclear wording | the playbook `skills/_shared/ambiguity.md`; the "Reading unclear…" and "Example" parts of each `skills/*.md`; checked in `validators._read_ambiguities` |
| Do not invent values | grounding in `validators._clean_fields` (a value needs a quote that is in the email) |
| Draft reply | the skill's "Reply policy" in `skills/*.md`; safety check in `validators._draft_problems`; fallback `_template_body` |
| Reviewable output | `static/app.js` → `renderDrawer` |
| Do not send emails | there is no sending code anywhere |
| Hosted free | Render (`render.yaml`), deploys from `.github/workflows/ci-cd.yml` |
| AI models and fallback | `app/llm.py` (`run_chain`, circuit breaker), `MODEL_CHAIN` in `app/config.py` |

## 4. What happens to one email

```
browser (static/app.js)
  → POST /api/analyze/stream                    app/main.py
  → analyze_events()                            app/pipeline.py
      strip_quoted()      cut off reply history           app/preprocess.py
      router agent        llm.run_chain + router prompt   app/llm.py, app/skills.py
      load skill          skills/<category>.md
      skill agent         llm.run_chain + skill prompt
      build_result()      grounding, mode, missing, draft guard   app/validators.py
  → events stream back, one per step → the workflow view → dashboard
```

## 5. Questions you may get

**Why two agents instead of one call?** The router only sees short descriptions, so its job is small and fast. The skill agent gets only the instructions for its category, which keeps the prompt focused. It also lets the screen show real steps. It costs 2 requests per email, and `ROUTER_MODE=single` switches to 1 request.

**How do you stop the AI inventing values?** Every value must come with a quote, and the quote must really appear in the email. Numbers must match their quote. Otherwise the value is removed and reported. There is a test for it.

**How does it handle unclear emails ("around 100-120 kg", "same terms as last time")?** The skills teach the AI a playbook: never guess, keep the customer's words, say what is unclear, and ask. The AI returns each unclear point with an exact quote and a question. Python checks that the quote really is in the email (otherwise the point is dropped), then adds the question to the reply. Rules back the AI up: a range like "4 or 5" is flagged even if the AI missed it.

**Isn't it risky to trust the AI's judgement?** The AI only proposes. Quotes are verified, signals are combined with word lists, replies that promise prices, attachments or statuses are replaced by a safe template, and a person approves every draft.

**Why is the mode UNKNOWN for Test 4?** The brief says not to assume it. The mode is set only from clear words like "air freight", "FCL" or "40HC", never from the route or city names.

**Who decides what is missing?** Python, from a fixed table for each mode. That makes it repeatable and testable. The AI only extracts and writes.

**What if the AI makes a mistake?** A person reviews every draft. Validation catches invented values, prices, delivery promises and status claims, but it cannot prove the AI understood the email. Say this openly.

**What happens when a model fails or the free quota ends?** The next model in the chain is used. A model that just failed is skipped for 5 minutes. When the free daily limit is used up, the paid models (about $0.001 per email) take over. If everything fails, the screen says "OpenRouter API is not working".

**What about security?** The API key lives only on the server. The email is treated as data, and text that tries to give the AI instructions is ignored and flagged. There is a size limit and a rate limit.

**Why no database?** Free hosting has no permanent disk. The dashboard is saved in the browser, so each person sees their own. A real version would use a database.

**How is it tested?** 94 automated tests run in GitHub Actions on every push. They use a fake AI, so they need no key.

**What would you do next?** A database and logins, a real mailbox connection, tracking and accounting integrations, a larger set of test emails to measure accuracy, and a per-field confidence score.

**Honest limitations:** free models can be busy or slow; replies only acknowledge or ask, they never quote a price or a status; tested mostly on English emails.

## 6. Live changes to rehearse

Rehearse two or three of these until you can do them without looking. Run the app locally with `uvicorn app.main:app --reload`, so Python changes load by themselves. Browser files only need a refresh.

**A. Change the reply sign-off** (easy)
- Edit the line `Best regards,` / `Hermes Team` in `app/skills.py` (inside `REPLY LAYOUT`) and the `sign = ...` line in `_template_body` in `app/validators.py`.
- Check: analyse Test 1 and look at the end of the reply.

**B. Show more history, or a shorter counter window** (easy, no Python)
- In `static/app.js`, change `const HISTORY_SIZE = 5;` or `const DAY_MS = 24 * 60 * 60 * 1000;`.
- Check: refresh the page.

**C. Teach it a new mode word** (medium)
- In `app/validators.py`, add `r"\bair\s*express\b"` to `_AIR_PATTERNS`.
- Check: send "Please quote air express from Pune to Dubai, 40 kg" and the mode shows AIR.
- Add a one-line test in `tests/test_validators.py` next to `test_mode_air_from_explicit_wording`.

**D. Add a new field** (medium), for example `hs_code`
1. `skills/freight_quotation.md`: add `- hs_code — the customs HS code of the goods, if stated` to the fields list.
2. `app/schemas.py`: add `("hs_code", "HS code", "HS code of the goods")` to `FIELDS[FREIGHT]`.
3. `app/validators.py`: in `compute_missing`, add `"hs_code"` to the `core` list if it should be required.
- Check: analyse Test 1 and the field appears, with "missing" if you made it required.
- Run `python -m pytest`. Two tests list the exact missing items for Tests 1 and 2, so they fail on purpose. Update their expected sets.

**E. Change the models** (easy, no code)
- Edit `MODEL_CHAIN` in `.env` (or in Render → Environment) and restart.

**F. Add a seventh category, "Customs"** (harder)
1. New file `skills/customs.md` with the three frontmatter lines (`name`, `category: Customs`, `description`) and the same sections as `skills/other.md`.
2. `app/schemas.py`: add `CUSTOMS = "Customs"`, add it to `CATEGORIES`, add `FIELDS[CUSTOMS] = [("topic", "Topic", "what you need help with")]`, and add `if "customs" in v: return CUSTOMS` to `canonical_category`.
3. `static/app.js`: add `{ id: 'Customs', short: 'Customs', file: 'customs.md' }` to the `CATS` list.

**G. Teach the AI a new way to read unclear emails** (easy, no code)
- Add a numbered rule to `skills/_shared/ambiguity.md`, for example: *"13. Weights given in pounds ("lbs") are kept as written; do not convert them."*
- Check: send an email that uses the new wording. The change applies on the next request, with no restart.

After any change: `python -m pytest -q`, then `git add -A`, `git commit -m "..."`, `git push`. Watch the **Actions** tab. It tests, deploys, and waits until the new version is live.

## 7. If something goes wrong during the demo

- **Red "OpenRouter API is not working" box:** click **Retry**. Models usually recover within a minute. Open "Details" to show which models failed and why. This is the fallback working as designed.
- **The page loads slowly:** the free Render plan may have been asleep. A keep-alive job normally prevents it. Wait about a minute.
- **An answer looks wrong:** say so plainly. Point to the "Missing, unclear or conflicting" panel and the evidence quotes. That honesty is part of the design.
- **Everything is slow:** in Render → Environment, set `ROUTER_MODE` to `single`. The app restarts and uses 1 request per email.
- **Do not claim 100% accuracy.** Say that a person reviews every draft.

## 8. Numbers to remember

- 6 categories, 3 modes (AIR, OCEAN, UNKNOWN), 12 freight fields.
- Models: free 550B, free 120B, paid 120B (about $0.001 per email), paid 550B, free Gemma.
- Free tier: 50 requests a day. Each email uses 2.
- 94 automated tests. CI/CD: GitHub Actions to Render.
- Live URL: https://hermes-email-assistant.onrender.com
