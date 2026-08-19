# CLAUDE.md

Context for working on this repo. `API_PROTOCOL.md` is the current,
authoritative REST contract — this file is about *why* it's shaped this way,
so a future change doesn't accidentally undo a deliberate decision.

## What this project is

A backend for a classroom game (Kahoot-esque). A professor starts a
"server" (session), students join with a name, and each picks predictor
variables to build a logit ("likelihood of a Shark Tank deal") model against
real reality-TV negotiation data. Everyone races to find the best-scoring
variable combination before the professor ends the round; final scores are
revealed against a hold-out nobody could see while playing.

## The original plan (professor's spec, paraphrased)

- Professor sends an authenticated request to start a "server" and gets back
  a join code (Kahoot-style) to share with students.
- Students join with their full name and get a unique token back.
- Students repeatedly POST a list of variable names to try. If those
  variables are usable, the backend checks a model cache first; on a miss it
  fits a logit model, caches it, and either way returns the % of actual
  yes-deals predicted correctly and % of actual no-deals predicted correctly
  (never raw accuracy alone — the dataset skews toward deals happening, so
  accuracy alone rewards always guessing "yes").
- A separate "finalize" call locks in a student's choice. It's one-shot:
  calling it again, or calling explore again afterward, returns a distinct
  `already_submitted` response instead of recomputing.
- Every 5 seconds the professor polls a dashboard: leaderboard, who's
  online, average variable count across finalized submissions. **This is a
  deliberate polling design, not push** — the professor is expected to be
  screen-sharing this dashboard live while students race to find good
  variables (think a Minecraft-server-style reconciliation loop), so a
  5-second refresh cadence is plenty and there's no need for
  WebSockets/SSE here.
- Professor stops the server; the backend scores every finalized submission
  against seasons 11+ (a genuine hold-out, never scored until this point)
  and returns two leaderboards: one by seasons 8-10 accuracy, one by
  seasons 11+ accuracy.

## Significant design decision: individual one-hot categories are selectable

Students pick out individual categories (e.g. `Industry_Travel`), **not**
the parent field (`Industry`) toggling every category on at once. This
applies to every one-hot-encoded field. Naming convention:
`<OriginalHeader>_<DiscreteValue>` (e.g. `Pitchers Gender_Female`).

Consequence: `dataset.USABLE_COLUMNS` is a flat list where every one-hot
category is its own first-class, individually selectable entry — there's no
"logical name that expands to N dummy columns" indirection. A variable name
a student sends is *always* a literal column in the prepared dataset. An
earlier version of this code had that expansion layer (`PreparedDataset
.expand()`); it's gone on purpose, and shouldn't come back without a reason
to reintroduce the whole-field toggle behavior.

The one thing this reintroduces: if a student selects **every** category of
the same original field at once, those dummies sum to 1 for every row and
are exactly collinear with the model's intercept — unsolvable.
`dataset.validate_variable_selection()` guards against exactly that case
(and against unusable column names generally). It's called both by the API
layer (for a clean 400) and inside `modeling.fit_logit_model()` itself, so
the guard holds even if you call the modeling code directly, outside the
API — don't remove either call site.

## Module responsibilities (keep this modular)

- `dataset.py` — the only place that knows about the raw CSV,
  `USABLE_COLUMNS`, and one-hot encoding. Owns the derived/prepared CSV file
  (raw CSV is never touched — see below). Exposes `load_prepared_dataset()`
  as the one entry point everything else should use.
- `modeling.py` — pure functions: fit a logit model on seasons 1-7, score
  any fitted model's coefficients against any slice of data. No knowledge of
  sessions, caching, or HTTP. **This is the module to import directly if you
  just want to try a variable combination from a plain script** — see
  "Running a model standalone" below.
- `cache.py` — `ModelCache`, keyed by the exact (order-independent) set of
  variables. One fit per distinct variable set per process, shared across
  all game sessions.
- `sessions.py` — in-memory game state: join codes, students,
  explore/finalize semantics, the professor's dashboard snapshot, and
  closing a session (the only place `modeling.score_final_test` gets
  called).
- `schemas.py` / `server.py` — the FastAPI HTTP layer. Should stay thin; if
  you're writing real logic here instead of in the modules above, it
  probably belongs in one of them instead.
- `main.py` — CLI entry point. Runs the server by default; `--demo` runs a
  quick console sanity check using only `dataset.py` + `modeling.py`.

## Running a model standalone (no server, no session, no cache)

```python
from economicsproject.dataset import load_prepared_dataset
from economicsproject.modeling import fit_logit_model

dataset = load_prepared_dataset()
fitted = fit_logit_model(
    ["Original Ask Amount", "Industry_Food and Beverage", "Pitchers Gender_Female"],
    dataset,
)
print(fitted.equation)
print(fitted.basic_test)  # seasons 8-10 only; final test (11+) is deliberately not exposed here
```

This is exactly what `cache.ModelCache.get_or_fit()` and the API do under
the hood — there's no server-only logic hiding in the model-fitting path.
Verified working as of this writing by actually running it, not just
asserting it.

## Testing

One test file per module in `tests/`. Run with `pytest`. `tests/test_server.py`
exercises the full join → explore → finalize → already_submitted →
dashboard → stop flow through FastAPI's `TestClient`, which is the fastest
way to sanity-check a change to the API layer end to end.

## Known simplifications

See `API_PROTOCOL.md`, "Scope and limitations," for the full list — in
short: in-memory single-process state only, shared-secret auth rather than
real accounts, no rate limiting on `/explore`, and students only see their
own final rank rather than a fully public leaderboard.
