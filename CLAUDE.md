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
applies to every one-hot-encoded field (currently just `Industry` — see
"Pitchers Gender is continuous, not one-hot" below for the one field that
deliberately isn't encoded this way). Naming convention:
`<OriginalHeader>_<DiscreteValue>` (e.g. `Industry_Travel`).

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
message from `dataset.one_hot_collinearity_message()`. That message
deliberately avoids the term "dummy variable" — to a student reading it
mid-game, "dummy" reads as "this doesn't matter," which is backwards: every
one-hot column still has a real, meaningful coefficient on its own, it's
only selecting *all* of them at once that breaks the fit. "One-hot
encoding" says the same thing without that risk. See "Significant design
decision: rejected selections, not just deprecated exploring" below and
API_PROTOCOL.md, "Attempts," for the full contract.

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

## Significant design decision: Pitchers Gender is continuous, not one-hot

`Pitchers Gender` is the one field in `CATEGORY_VALUES`'s original spot
that got pulled back out and is no longer one-hot encoded. It's now a
single numeric column in `NUMERIC_USABLE_COLUMNS`, encoded via
`dataset.PITCHERS_GENDER_VALUES`: `Male -> 0.0`, `Mixed Team -> 0.5`,
`Female -> 1.0`. A student picks one variable, `"Pitchers Gender"` —
`Pitchers Gender_Male` / `_Female` / `_Mixed Team` no longer exist as
columns at all.

**Why this one field, when `Industry` stays one-hot.** One-hot encoding is
the right choice for genuinely unordered categories — there's no
meaningful sense in which `Industry_Travel` is "between" `Industry_Health
/Wellness` and `Industry_Automotive`, so a single numeric code for
"industry" would impose a false ordering the data doesn't have. Gender, as
recorded in this dataset (`Male` / `Female` / `Mixed Team`), is different:
a mixed team is genuinely a blend of the other two, not an unrelated third
category off to the side — 0.5 sitting exactly halfway between 0 (Male)
and 1 (Female) reflects that literally, not just conveniently. Treating it
as a single continuous range is a real, defensible modeling choice here,
not a shortcut.

**Consequences worth knowing:**
- `USABLE_COLUMNS` dropped from 34 to 32 entries (`NUMERIC_USABLE_COLUMNS`
  gained one, `CATEGORY_VALUES` lost three) — `client/app.py`'s
  `USABLE_COLUMN_COUNT` constant is updated to match; recompute it the
  same way if the dataset changes again (see the comment above it).
- `dataset.fully_selected_categories()` / the one-hot-collinearity
  rejection in `Session.finalize()` (see below) no longer has anything to
  do with gender — `CATEGORY_VALUES` only has `Industry` in it now, so
  that entire mechanism is scoped to `Industry` alone. There's no
  equivalent "select every gender value" failure mode any more, because
  there's only one gender column to select.
- The raw CSV has a handful of missing `Pitchers Gender` values (verified:
  9 rows, out of ~1,480). `_build_prepared_frame()` maps those to `NaN`
  same as any other missing numeric predictor -- `fit_logit_model()`
  mean-imputes them from the training split, exactly like a missing
  `Valuation Requested` would be. This is different from how a *missing*
  one-hot category used to behave (all dummies simply 0), which is an
  intentional side effect of no longer being one-hot, not an oversight.
- The raw CSV itself is still never touched — this is a decode-time choice
  in `dataset.py`, same as one-hot encoding is.

## Significant design decision: rejected selections, not just deprecated exploring

`sessions.Session.finalize()` has three outcomes now, not two: `"ok"`,
`"attempts_exhausted"`, and `"invalid_selection"` — a student selected
every category of one or more one-hot fields at once (see the one-hot
section above). Exhaustion is still checked first (same as
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

**Polling alone doesn't cover the POST itself getting lost, only its
response.** The pattern above assumes `/finalize` was received and only
the reply back to the browser went missing — polling then finds the
already-recorded attempt. If the POST never reached the server at all
(the more common failure on flaky classroom wifi), nothing ever shows up,
and a student would be stuck staring at "Submitted — confirming…"
forever. Both shipped clients now resend the same `POST /finalize` after
**3 consecutive polls** (~3 seconds) show no change, and keep doing so
until something does. This is deliberately just a resend of the identical
request, not a different code path — `Session.finalize()` has no
idempotency key, so a resend that finds the *original* POST actually did
land (just slower than 3 polls, not truly lost) creates a genuine second
attempt with the same variables.

**That rare duplicate is then actively cleaned up, not just accepted.**
`Session.collapse_duplicate_attempt()` removes a student's most recent
attempt if it has *identical* variables to the one right before it,
submitted within `sessions.DUPLICATE_COLLAPSE_WINDOW_SECONDS` (30s) — and
is a no-op otherwise. Both clients call this automatically, right after a
resend-triggered poll resolves, and it's deliberately **not** wired to any
button in either UI. That's not an oversight: a *general* "withdraw my
last attempt" tool, even one with no client button, is still reachable by
any student who calls the API directly (their own token is a legitimate
credential regardless of which button — if any — got it used), and would
let them cycle finalize → look at the result → withdraw → finalize again
for effectively unlimited real attempts, defeating the entire point of
`MAX_ATTEMPTS`. Collapsing an *exact* duplicate doesn't have that hole:
since the two attempts score identically (same variables, same cached
fit), removing one is a strict no-op for the student's standing — there's
no way to use it to discard a bad attempt and get a free do-over. See
API_PROTOCOL.md, "Attempts," for the endpoint contract.

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

## Fixed bug: a definitive `/finalize` failure used to hang the client forever

A student selecting enough numeric predictors at once (reproduces with
just `NUMERIC_USABLE_COLUMNS`, no `Industry_*` involved) could make
`numpy.linalg.matrix_rank()` — called inside `modeling
.describe_collinearity()` to check for exact collinearity — fail with a
raw `LinAlgError: SVD did not converge`. That call happened *before*
`fit_logit_model()`'s own `try/except LinAlgError` (which only wraps the
actual `sm.Logit(...).fit()` call, a few lines further down), so the
exception escaped uncaught. Fixed: `describe_collinearity()` now wraps its
own rank check and treats a non-converging SVD the same as a detected rank
deficiency — a plain-language `warning`, not a crash — so the fit is
attempted anyway, same as any other degenerate case (see "Degenerate
fits" in `API_PROTOCOL.md`).

Fixing that surfaced a second, worse bug right behind it: with the SVD
crash gone, the same numeric-heavy selections instead hit
`statsmodels.tools.sm_exceptions.MissingDataError: exog contains inf or
nans` — not caught anywhere, and not even a `ValueError` subclass (unlike
`LinAlgError`, which is), so it wasn't a clean `400` either, it was a raw
`500`. Root cause traced to `"Guest Present"`: verified against the raw
CSV, it has **zero** non-null values in both the training seasons (1-7)
*and* the basic-test seasons (8-10) — it only starts being recorded in
season 15, part of the final hold-out. `fit_logit_model()`'s
mean-imputation (`train_df[feature_columns].mean()` then `fillna`) is a
no-op when the mean itself is `NaN` (mean of an all-`NaN` column), leaving
the whole column `NaN` in training and guaranteeing this crash on *any*
selection that includes it — even by itself, alone. This isn't a
degenerate-but-fittable case like the ones above; there's no valid
training-period data to fit against at all. Fixed by removing
`"Guest Present"` from `dataset.NUMERIC_USABLE_COLUMNS` entirely — it was
never a legitimate choice given this project's fixed train/test season
split, so it shouldn't have been offered in the first place. `USABLE_COLUMNS`
drops from 32 to 31 (`client/app.py`'s `USABLE_COLUMN_COUNT` updated to
match); check any new column the same way before adding it (`train[col]
.notna().sum()` across the training AND basic-test season ranges, not just
the whole dataset) if the raw CSV ever changes again.

**Even with both of those fixed, the deeper bug was client-side.**
`numpy.linalg.LinAlgError` actually *is* a `ValueError` subclass (verified
directly), so `server.py`'s `except ValueError` in the `/finalize` handler
already turned it into a clean `400` — the backend was never the thing
crashing. Both clients' `postFinalize()` just caught *any* rejected POST
identically, network failure or real HTTP error alike, and fell through
to the poll-then-resend loop on the assumption "maybe it landed anyway."
For a *definitive* failure (any real HTTP response, not a dropped
connection) that assumption is simply wrong — none of these cases ever
reach `Session.finalize()`'s attempt-recording step, so nothing was ever
going to show up no matter how long the client polled, and the resend
just repeated the identical failure every ~3 seconds forever. That's what
"the app freezes" actually was: not a crash, an infinite loop with no
error ever surfaced. Fixed: `postFinalize()` now checks `err.status` (set
by `api.js`'s `apiRequest()` only when a real HTTP response came back,
never on a true network-level failure) and, when present, shows the error
and stops immediately instead of entering the poll loop at all. This is
the general fix — it protects against *any* future definitive `/finalize`
rejection working this way, not just these two specific causes.

## Module responsibilities (keep this modular)

- `dataset.py` — the only place that knows about the raw CSV,
  `USABLE_COLUMNS`, and one-hot encoding. Owns the derived/prepared CSV file
  (raw CSV is never touched — see below). Exposes `load_prepared_dataset()`
  as the one entry point everything else should use. Also owns
  `fully_selected_categories()` (detects a fully-selected one-hot field)
  and `one_hot_collinearity_message()` (the short, student-facing
  rejection text) — both pure, column-name-only functions, no fitting
  involved.
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
  (full-category, one-hot collinearity) selections (`InvalidSelection`,
  `Session.invalid_selection_for()`), collapsing an accidental duplicate
  attempt from a client's retry logic (`Session.collapse_duplicate_attempt()`),
  the professor's dashboard snapshot, and closing a session (the only place
  `modeling.score_final_test` gets called, for every attempt).
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
    ["Original Ask Amount", "Industry_Food and Beverage", "Pitchers Gender"],
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
`last_invalid_selection`. `tests/test_sessions.py` covers
`collapse_duplicate_attempt()`'s eligibility rules directly (identical
variables within the time window vs. every way it should be a no-op:
different variables, too far apart, fewer than 2 attempts, session
closed). The full client-side retry-creates-a-duplicate-then-it-gets-
collapsed round trip was verified with a real Playwright run against
actually running servers, not just these unit tests -- an out-of-band
request was used to simulate the specific race (client sees the original
POST fail fast, but its bytes still reach the server well after 3 polls).

## Known simplifications

See `API_PROTOCOL.md`, "Scope and limitations," for the full list — in
short: in-memory single-process state only, shared-secret auth rather than
real accounts, no rate limiting on the polling endpoints (fine at classroom
scale), and students only see their own final rank rather than a fully
public leaderboard.
