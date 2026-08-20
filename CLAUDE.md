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
- Students POST a list of variable names to submit as an attempt. If those
  variables are usable, the backend checks a model cache first; on a miss it
  fits a logit model, caches it, and either way returns the % of actual
  yes-deals predicted correctly and % of actual no-deals predicted correctly
  (never raw accuracy alone — the dataset skews toward deals happening, so
  accuracy alone rewards always guessing "yes").
- Each student gets **3 attempts**, not 1 — see "Significant design
  decision: three attempts" below for the full reasoning and why an earlier
  unlimited-live-preview design was deprecated in favor of this.
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
are exactly collinear with the model's intercept. `dataset
.validate_variable_selection()` still guards against unusable column names
(and is still called both by the API layer and inside
`modeling.fit_logit_model()` itself — don't remove either call site).

**This case (the full-category selection) is now rejected in the actual
student game, not fit-and-warned.** Earlier this repo let a student submit
it anyway — the fit doesn't error, statsmodels hands back a completely
normal-looking equation, and the "lesson" was a `warning` string attached
to the response. In practice this taught nothing (nobody but the professor
reads a multicollinearity writeup mid-game) and cost the student one of
their three scored attempts for a model that was never a real answer. So
`sessions.Session.finalize()` now calls `dataset.fully_selected_categories()`
*before* attempting any fit and, if it's non-empty, rejects the submission
outright: `status: "invalid_selection"`, no attempt consumed, a short
message from `dataset.dummy_variable_trap_message()`. See "Rejected
selections: the dummy-variable trap" below and API_PROTOCOL.md, "Attempts,"
for the full contract.

`modeling.fit_logit_model()` itself is untouched and still allows the
full-category case when called directly, outside a game session (see
"Running a model standalone" below) — `modeling.describe_collinearity()`
still detects it numerically (rank deficiency, not "did they pick every
category" pattern-matching, so it also catches any other combination that
happens to be exactly collinear) and still attaches a plain-language
`warning` to `FittedModel`. That's a useful thing for a professor's own
script to demonstrate; it's just no longer something a student can spend an
attempt on in the actual game, and the old per-submission warning banner in
both clients was removed along with it.

**What "unsolvable" actually means in practice:** the design matrix has one
fewer independent direction than columns (verified: `numpy.linalg
.matrix_rank` comes back short by exactly 1), so there's a whole line of
equally-"correct" coefficient vectors — shift the intercept by any constant
`c` and every one of that field's coefficients by `-c`, and predictions are
identical, because exactly one dummy is always 1 and the `+c`/`-c` cancels
every time. Empirically (checked, not assumed): Newton, BFGS, and L-BFGS
converge to *different* numbers on identical data, standard errors come
back `NaN`, condition number ~10¹⁵. See `API_PROTOCOL.md`, "Degenerate
fits," for the full writeup and an example payload.

## Significant design decision: rejected selections, not just deprecated exploring

`sessions.Session.finalize()` has three outcomes now, not two: `"ok"`,
`"attempts_exhausted"`, and `"invalid_selection"` — a student selected
every category of one or more one-hot fields at once (the dummy-variable
trap; see the section above). Exhaustion is still checked first (same as
before, and for the same reason: an already-exhausted student's input is
never even looked at, since it wouldn't be used anyway); an
`invalid_selection` is then caught right after, before any fit is
attempted, and doesn't consume an attempt.

Both shipped clients also check this themselves, client-side, before ever
sending the request (`fullySelectedCategories()` in `client/static/js
/api.js`, mirrored byte-for-byte in `client_barebones/`) — so in the normal
case a student never gets to POST an invalid selection at all. But the
server enforces the same rule independently (`dataset
.fully_selected_categories()`, called from `Session.finalize()`), because
the client-side check can go stale or be bypassed (a direct API call, a
modified client, `categories` in `localStorage` from before a dataset
change) and this must not be trust-the-client-only.

Rejection is *logged*, not just returned: `Session.invalid_selection_for()`
holds each student's most recent rejection, surfaced through
`GET /sessions/{code}/status` as `last_invalid_selection`. This mirrors why
`GET /attempts` exists for successful submissions (see the attempts section
below) — if the `/finalize` POST's own response is lost (dropped wifi,
closed tab) before a student learns their selection was rejected, polling
`/status` is how the client eventually finds out anyway, stops waiting, and
shows the exact same banner it would have shown from the client-side check.
See API_PROTOCOL.md, "Attempts," for the field-by-field response contract.

## Significant design decision: three attempts, confirmed via polling, not one submission with live preview

The original design let students call `/explore` an unlimited number of
times before a one-shot `/finalize`, seeing basic-test accuracy update live
as they toggled checkboxes. That's gone. Current design: `/explore` is
**deprecated but not deleted** (still fully functional, `deprecated: true`
in the OpenAPI schema, unused by both shipped clients — a one-line revert
if this call turns out wrong), and `/finalize` now allows
`sessions.MAX_ATTEMPTS` (3) submissions per student per session instead of
one. There's no live pre-submission feedback any more; every submission is
real and counts.

**The two changes are linked, and the second one exists because of the
first.** Once submissions are scarce (3, not unlimited), a client can no
longer treat a lost HTTP response as harmless ("just try again") — the
attempt is recorded server-side the instant `Session.finalize()` computes
it, regardless of whether the response carrying that result ever reaches
the browser (dropped wifi, closed tab — real risks in a room full of
student laptops/phones). So `GET /sessions/{code}/attempts` exists as the
authoritative, idempotent source of truth: the documented client pattern is
POST to `/finalize` without trusting its response, then poll
`GET /attempts` every ~1 second until the new attempt shows up, and only
then re-enable submission. This is a **client-side convention**, not
something the server enforces — the server's only actual rule is the count
itself (a 4th `finalize` call returns `status: "attempts_exhausted"` with
the 3rd attempt's data unchanged, never a new fit). See API_PROTOCOL.md,
"Attempts," for the full endpoint contract; don't skip the polling pattern
when touching client code, it's the entire reason `/attempts` exists.

**"Current standing" is always the best attempt, not the latest.** A
student's position on the professor's dashboard and on both final
leaderboards (`Session.dashboard()`, `Session.close()`) is their
highest-`basic_test.accuracy` attempt so far — computed via
`Session.best_attempt_for()`, the one place this selection logic lives.
`GET /attempts` is the opposite: it always returns *every* attempt, which
is the whole point of the "check my previous submissions" ask this was
built for. On `close()`, every attempt from every student gets scored
against the final hold-out (not just each student's best) — that's what
lets a student later see, via `GET /attempts`, which of their 3 tries
would actually have scored best on the data nobody could see while playing.

## Module responsibilities (keep this modular)

- `dataset.py` — the only place that knows about the raw CSV,
  `USABLE_COLUMNS`, and one-hot encoding. Owns the derived/prepared CSV file
  (raw CSV is never touched — see below). Exposes `load_prepared_dataset()`
  as the one entry point everything else should use. Also owns
  `fully_selected_categories()` (detects the dummy-variable trap) and
  `dummy_variable_trap_message()` (the short, student-facing rejection
  text) — both pure, column-name-only functions, no fitting involved.
- `modeling.py` — pure functions: fit a logit model on seasons 1-7, score
  any fitted model's coefficients against any slice of data. No knowledge of
  sessions, caching, or HTTP. **This is the module to import directly if you
  just want to try a variable combination from a plain script** — see
  "Running a model standalone" below.
- `cache.py` — `ModelCache`, keyed by the exact (order-independent) set of
  variables. One fit per distinct variable set per process, shared across
  all game sessions.
- `sessions.py` — in-memory game state: join codes, students, the 3-attempt
  submission semantics (`MAX_ATTEMPTS`, `Session.finalize()`,
  `Session.attempts_for()`, `Session.best_attempt_for()`), rejected
  (dummy-variable-trap) selections (`InvalidSelection`,
  `Session.invalid_selection_for()`), the professor's dashboard snapshot,
  and closing a session (the only place `modeling.score_final_test` gets
  called, for every attempt).
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
exercises the full join → finalize ×3 → attempts poll → attempts_exhausted →
dashboard → stop flow through FastAPI's `TestClient`, which is the fastest
way to sanity-check a change to the API layer end to end. It also covers a
rejected full-category selection: `status: "invalid_selection"`, zero
attempts consumed, and the same rejection showing up in `GET /status`'s
`last_invalid_selection`.

## Known simplifications

See `API_PROTOCOL.md`, "Scope and limitations," for the full list — in
short: in-memory single-process state only, shared-secret auth rather than
real accounts, no rate limiting on the polling endpoints (fine at classroom
scale), and students only see their own final rank rather than a fully
public leaderboard.
