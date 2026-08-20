# Deal-Likelihood Game — API Protocol

A classroom game where a professor hosts a session (a "server," Kahoot-style),
students join with a code, and each gets up to 3 attempts to pick predictor
variables for a logit model of Shark Tank deal outcomes, scored for real each
time. The professor watches a live dashboard and, at the end, gets two
leaderboards scored against data nobody saw while playing.

This document is the contract between the backend (`economicsproject.server`)
and any frontend. The backend is intentionally plain RESTful JSON over HTTP —
no WebSockets, no server push. See "Real-time updates" below for what that
means in practice.

## Running it

```bash
pip install -r requirements-dev.txt
pip install -e .
PROFESSOR_API_KEY=<a real secret> python -m economicsproject.main
```

Defaults to `http://127.0.0.1:8000`. Override with the `HOST` / `PORT` env
vars. Interactive OpenAPI docs are auto-served at `/docs`.

## Base URL

All paths below are relative to the server's base URL, e.g.
`http://localhost:8000`.

## Auth model

Three credential types, sent as headers:

| Who | Header | Obtained from | Required on |
|---|---|---|---|
| Professor | `X-Professor-Key` | Set as the `PROFESSOR_API_KEY` env var before starting the server (shared secret, out of band) | `POST /sessions` only |
| Host (that professor's session) | `X-Host-Token` | Response of `POST /sessions` | `GET /sessions/{code}/dashboard`, `POST /sessions/{code}/stop` |
| Student | `X-Student-Token` | Response of `POST /sessions/{code}/join` | `POST /sessions/{code}/finalize`, `GET /sessions/{code}/attempts`, `GET /sessions/{code}/status`, and (deprecated) `POST /sessions/{code}/explore` |

`X-Professor-Key` gates who may create a session at all. Once a session
exists, its own `host_token` is sufficient to control it — the professor key
isn't re-checked on every dashboard poll. This also means two professors
sharing one deployment (and one `PROFESSOR_API_KEY`) can't accidentally
control each other's sessions, since each session's `host_token` is a
separate, random secret.

There's no student password: a full name plus the returned `student_token` is
the whole identity. Good enough for a low-stakes in-class exercise, not for
anything where impersonation matters — see "Scope and limitations."

## Error format

Every error response is:

```json
{ "detail": "human-readable message" }
```

with one of these status codes:

| Status | Meaning |
|---|---|
| 400 | Bad request body, or a variable name that isn't in `USABLE_COLUMNS` |
| 401 | Missing/invalid professor key or student token |
| 403 | Valid-looking but wrong `X-Host-Token` for that session |
| 404 | Unknown session code |
| 409 | The session has already been stopped |
| 422 | A required header or body field is missing/malformed (FastAPI's built-in validation, before your handler even runs) |

## The variable universe

`GET`/`POST` responses that mention usable columns are always drawn from
`economicsproject.dataset.USABLE_COLUMNS`, which is two things concatenated:

**Plain numeric columns**, used by their literal header name:

```
Episode Number, Pitch Number, Multiple Entrepreneurs, US Viewership,
Original Ask Amount, Original Offered Equity, Valuation Requested,
Barbara Corcoran Present, Mark Cuban Present, Lori Greiner Present,
Robert Herjavec Present, Daymond John Present, Kevin O Leary Present,
Guest Present, Season Number
```

**One-hot category values, each individually selectable.** Students pick out
specific categories — e.g. `"Industry_Travel"` — not the parent field as a
whole; there's no way to select "Industry" and get every industry at once.
Naming convention: `<OriginalHeader>_<DiscreteValue>`.

- **Industry** (16 values → 16 columns `Industry_Food and Beverage`,
  `Industry_Lifestyle/Home`, ... `Industry_Travel`): Food and Beverage,
  Lifestyle/Home, Fashion/Beauty, Fitness/Sports/Outdoors,
  Children/Education, Health/Wellness, Technology/Software, Pet Products,
  Business Services, Media/Entertainment, Uncertain/Other, Electronics,
  Automotive, Green/CleanTech, Liquor/Alcohol, Travel
- **Pitchers Gender** (3 values → 3 columns `Pitchers Gender_Male`,
  `Pitchers Gender_Female`, `Pitchers Gender_Mixed Team`)

Picking a **subset** of a field's categories (e.g. just `Industry_Travel`
and `Industry_Automotive`) is fine. Picking **every** category of the same
field at once is *allowed* — deliberately not rejected, see "Degenerate
fits" below — but the resulting model is numerically meaningless, and the
response says so via a `warning` field.

`POST /sessions/{code}/join` echoes three things so a frontend can build its
variable picker without hardcoding any of this:
- `usable_columns` — the flat list above, i.e. every literal string a
  student may put in `variables`.
- `categories` — the same category → values grouping shown above, handy for
  labeling a group of checkboxes.
- `dummy_column_category` — the reverse lookup, `{"Industry_Travel":
  "Industry", ...}`, handy for grouping the flat `usable_columns` list by
  category without re-deriving the `<Header>_<Value>` naming convention
  yourself.

## Data split & scoring

Every model is trained only on **seasons 1–7**. Two disjoint slices are used
for scoring, and only one of them is ever shown to students while a session
is running:

- **Basic test — seasons 8–10.** Scored immediately on every `explore` and
  `finalize` call. This is what students see and optimize against live.
- **Final test — seasons 11 and up** (currently 11–17 in the bundled CSV;
  it's "whatever seasons exist beyond 10," not hardcoded to a specific upper
  bound). Never scored until the professor calls `POST /stop`. This is a
  genuine hold-out — nothing in `/explore` or `/finalize` responses reveals
  final-test performance, so students can't back it out mid-game.

Each score is a `ConfusionMetrics` object:

```json
{
  "accuracy": 0.588,
  "yes_deal_accuracy": 0.797,
  "no_deal_accuracy": 0.186,
  "sample_size": 284
}
```

- `accuracy` — overall % of predictions matching the actual outcome.
- `yes_deal_accuracy` — of the pitches that *actually* got a deal, the % the
  model predicted correctly (recall on the positive class).
- `no_deal_accuracy` — of the pitches that *actually* didn't get a deal, the
  % the model predicted correctly (recall on the negative class).
- These are reported separately (not just accuracy) because the dataset is
  imbalanced toward deals happening — a model that always guesses "yes" gets
  decent accuracy while being useless. `null` for `yes_deal_accuracy` /
  `no_deal_accuracy` only if a slice has zero examples of that outcome
  (won't happen with this dataset, but the API stays honest about it).

## Attempts

Each student gets `MAX_ATTEMPTS` (currently **3**) submissions per session,
not one. This replaced an earlier one-shot "explore live, then finalize
once" design — see below for why, and why `/explore` is now deprecated
rather than removed.

**Why 3 attempts instead of unlimited live exploring.** The previous design
let a student call `/explore` as many times as they liked before committing,
seeing basic-test accuracy on every keystroke. That's pedagogically
generous but functionally pointless to keep once the game is meant to feel
like a small number of deliberate, real submissions rather than an
open-ended search — so live pre-submission feedback is gone, and every
submission actually counts. `/explore` itself is **deprecated, not
deleted**: it's still fully functional (see its endpoint doc below) so this
is a one-line revert if that turns out to be the wrong call, but neither
shipped client calls it any more.

**Why the client should poll `GET /attempts` instead of trusting the
`POST /finalize` response.** An attempt is recorded server-side the moment
`/finalize` computes it — regardless of whether the HTTP response carrying
that result actually makes it back to the student's browser (a dropped
connection, a closed tab, flaky classroom wifi). With unlimited attempts
that was a non-issue: just try again. With only 3, a lost response would
mean a student burns an attempt and never finds out what happened. So the
recommended client pattern is:

1. `POST /finalize`. Treat the response as a hint at best — don't render it
   directly, and don't worry if the request itself errors out (the attempt
   may still have landed).
2. Immediately start polling `GET /sessions/{code}/attempts` every second.
3. Keep the "submit" button disabled while polling.
4. Once the poll's `attempts_used` reflects the new attempt, stop polling,
   render from *that* response, and re-enable submission if
   `attempts_remaining > 0`.

`GET /attempts` is idempotent and cheap (a dict lookup, no computation), so
polling it is safe to retry indefinitely and imposes no meaningful load.
This "don't trust the POST, confirm via GET" pattern is a client-side
convention, not something the server enforces — the server's only real
rule is the count itself: the 4th `finalize` call (and beyond) returns
`status: "attempts_exhausted"` with the *3rd* attempt's data unchanged, it
does not error and does not silently accept a 4th submission.

**What counts as "current standing."** With multiple attempts, a student's
position on the professor's dashboard and on both final leaderboards is
always their **best attempt so far by basic-test accuracy** — not their
most recent, not an average. `GET /attempts`, on the other hand, always
returns *every* attempt (that's the whole point of it) so a student can see
exactly how each of their 3 tries actually did, including which one
strategy would have scored best on the (eventually revealed) final test.

**Rejected selections don't consume an attempt either.** `POST /finalize`
has a third outcome besides `"ok"` and `"attempts_exhausted"`:
`"invalid_selection"` — a student selected every category of one or more
one-hot fields at once (the dummy-variable trap; see "Degenerate fits"
below for why that's unsolvable, not just unwise). The exhaustion count is
still checked first (an already-exhausted student's selection is never
even looked at); an `invalid_selection` is then caught right after, before
any fit is attempted, so a still-eligible student never loses an attempt to
it. Both shipped clients
also check this themselves before ever sending the request, so in the
normal case a student never gets to POST it at all — but the server
enforces the same rule independently in case that client-side check is
stale or bypassed. Because this can also arrive via a lost `/finalize`
response, the same client polling pattern above applies: `GET /status`'s
`last_invalid_selection` field (see its endpoint doc below) is how a client
learns a submission was rejected even if it never saw the POST response
that said so.

## Degenerate fits

A student can select every category of the same one-hot field at once (e.g.
all 16 `Industry_*` columns). This makes the design matrix perfectly
multicollinear: those 16 dummy columns sum to 1 for every row, exactly
duplicating the intercept column — there's no unique best-fit answer for a
model like that (see below for the numerical detail).

**In the actual student game, `POST /finalize` rejects this outright** —
see "Attempts" above. `status: "invalid_selection"`, no fit attempted, no
attempt consumed, and a short explanation in `message`:

```json
{
  "status": "invalid_selection",
  "attempts_used": 0,
  "attempts_remaining": 3,
  "max_attempts": 3,
  "variables": ["Industry_Automotive", "...", "Industry_Uncertain/Other"],
  "culprit_categories": ["Industry"],
  "message": "Can't build a model with every Industry option selected — that's the dummy variable trap (perfect multicollinearity from one-hot encoding). Deselect at least one Industry option and try again.",
  "attempted_at": 1732500000.0
}
```

This used to be allowed-with-a-warning instead — the fit would go through
and a `warning` string on the response explained why the coefficients
weren't a real answer. That taught nothing in practice (nobody but the
professor reads a multicollinearity writeup mid-game) and cost the student
a scored attempt for a model that was never usable, so it was replaced with
an outright rejection that doesn't touch the attempt count. The deprecated
`POST /explore` endpoint (and `modeling.fit_logit_model()` used directly,
outside a game session — see `CLAUDE.md`, "Running a model standalone")
still exhibit the old behavior unchanged: they fit it anyway and attach a
`warning` string, since seeing *why* the fit breaks is a useful
demonstration there, just not something that should cost a student a
scored attempt in the real game.

**What actually happens, numerically, when it's fit anyway (`/explore`, or
`fit_logit_model()` called directly):** the fit doesn't error out.
statsmodels happily reports "Optimization terminated successfully" and
hands back an equation that looks completely normal. But there's no unique
solution — shift the intercept by any constant `c` and every one of that
field's coefficients by `-c`, and you get *identical* predictions for every
row (exactly one dummy is always 1, so the `+c`/`-c` always cancels).
That's an entire line of equally-"correct" coefficient vectors, not one
answer. Empirically: Newton's method, BFGS, and L-BFGS each converge to
*different* numbers on the exact same data (we checked — predicted
probabilities differed by up to 3.5 percentage points between solvers),
standard errors come back `NaN`, and the design matrix's condition number
is on the order of 10¹⁵ (numerically singular).

`modeling.describe_collinearity()` detects this directly (design-matrix
rank deficiency via `numpy.linalg.matrix_rank`, not by pattern-matching
"did they pick every category" — the same detection catches any
combination of variables that happens to be exactly collinear, not just
this one anticipated case) and attaches a `warning` string to the fit
result explaining it. `warning` is `null` on every normal fit and still
appears on `/explore` responses when triggered; it's effectively always
`null` on `/finalize`/`/attempts`/leaderboard entries now, since
`/finalize` rejects the one case (full-category selection) that could
trigger it before any fit happens.

(A genuinely unfittable design matrix — statsmodels hard-fails rather than
silently returning an arbitrary answer — is the one case that *does* still
come back as an error: `400` with a `detail` explaining the same thing. This
is rare; every case we've tried, including the full-category one above,
returns a degenerate-but-present result instead when it's fit at all.)

## Model caching

The backend fits a logit model for a given *set* of variables (order and
duplicates don't matter — `["Industry_Travel", "Original Ask Amount"]` and
`["Original Ask Amount", "Industry_Travel", "Industry_Travel"]` are the same model) **at
most once per server process**, the first time any student asks for it. Every
later `explore`/`finalize` call with that same variable set — from the same
student or a different one — reuses the cached fit instantly instead of
re-running the regression. The cache is shared across all sessions on the
server, not per-session, since the fit is a pure function of the training
data and the variable set.

## Real-time updates (read this if you're building the frontend)

This API has no push channel. Two consequences:

1. **The professor's dashboard is a poll, not a push.** "Every five seconds"
   is implemented by the frontend calling `GET /sessions/{code}/dashboard` on
   a `setInterval(..., 5000)` — the backend has no timer of its own and just
   answers with current state whenever asked.
2. **Students find out a session ended by polling too**, or by the natural
   `409` they'll get on their next `/finalize` call after `/stop` — there's
   no way for the backend to interrupt them mid-session. Use
   `GET /sessions/{code}/status` for this; poll it however often feels right
   (a few seconds is plenty) for that purpose alone. Right after submitting
   an attempt, though, both shipped clients poll `GET /sessions/{code}/attempts`
   *and* `GET /sessions/{code}/status` together on the same *much* tighter
   ~1-second interval — `/attempts` to confirm a successful submission
   landed, `/status`'s `last_invalid_selection` to confirm a rejected one
   did too — see "Attempts" above. That tight interval is for confirming
   what just happened, not for detecting the session ending; the loose,
   several-seconds `/status` poll runs the whole time regardless and covers
   that.

If you need instant push (e.g. a student's screen should update the moment
the professor stops the game, not next-poll), that requires WebSockets or
Server-Sent Events — a deliberate step beyond "RESTful," not implemented
here.

---

## Endpoints

### `POST /sessions`

Start a new session ("server"). Professor-only.

**Headers:** `X-Professor-Key: <secret>`

**Request body:** none

**Response** `201`:
```json
{ "session_code": "701163", "host_token": "vhin3wkXSlwFz4o8jt-cja03dRy_mgPL" }
```

`session_code` is the 6-digit code to display/share with students (like a
Kahoot PIN). `host_token` is secret — keep it on the professor's client only;
it's what proves ownership of this specific session for the dashboard/stop
calls below.

---

### `POST /sessions/{code}/join`

A student joins a session with their name.

**Headers:** none

**Request body:**
```json
{ "full_name": "Ada Lovelace" }
```

**Response** `201`:
```json
{
  "student_id": "S1",
  "student_token": "50JH2u0kZBypwz3YiVjidVKEpwPbKqR4",
  "usable_columns": ["Episode Number", "Pitch Number", "...", "Industry_Food and Beverage", "Industry_Travel", "..."],
  "categories": {
    "Industry": ["Food and Beverage", "Lifestyle/Home", "..."],
    "Pitchers Gender": ["Male", "Female", "Mixed Team"]
  },
  "dummy_column_category": {
    "Industry_Food and Beverage": "Industry",
    "Industry_Travel": "Industry",
    "Pitchers Gender_Female": "Pitchers Gender",
    "...": "..."
  },
  "max_attempts": 3
}
```

`student_token` identifies this student for every subsequent call — store it
client-side (e.g. `sessionStorage`) and send it as `X-Student-Token`.
`max_attempts` is echoed here so a frontend doesn't need to hardcode it.

**Errors:** `404` unknown `code`; `400` empty `full_name`.

---

### `POST /sessions/{code}/explore` — deprecated

**Deprecated as of the attempts model — see "Attempts" above.** Not called
by either shipped client any more, but left fully functional in case that
decision gets reverted. Fits (or reuses a cached fit for) the given
variables and returns basic-test metrics **without consuming an attempt**.
Marked `deprecated: true` in the OpenAPI schema (visible struck-through in
`/docs`).

**Headers:** `X-Student-Token: <token>`

**Request body:**
```json
{ "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"] }
```

**Response** `200`:
```json
{
  "status": "ok",
  "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"],
  "equation": "logit(P(Got Deal)) = 0.7460 + 0.0903 * Industry_Food and Beverage + 0.3893 * Industry_Travel - 0.0000 * Original Ask Amount",
  "basic_test": { "accuracy": 0.570, "yes_deal_accuracy": 0.695, "no_deal_accuracy": 0.330, "sample_size": 284 },
  "warning": null
}
```

Or, once this student has used all `MAX_ATTEMPTS` submissions on
`/finalize` (exploring doesn't grant extra ones back):
```json
{ "status": "attempts_exhausted", "attempts_used": 3, "attempts_remaining": 0 }
```

**Errors:** `400` if any name in `variables` isn't in `USABLE_COLUMNS`, or if
statsmodels itself fails to fit at all (rare -- see "Degenerate fits"); `401`
bad/missing student token; `404` unknown session; `409` session already
closed.

---

### `POST /sessions/{code}/finalize`

Submit an attempt. Up to `MAX_ATTEMPTS` (3) per student per session — see
"Attempts" above for the full reasoning, including why the client should
confirm via `GET /attempts` rather than trust this response directly.

**Headers:** `X-Student-Token: <token>`

**Request body:**
```json
{ "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"] }
```

**Response** `200` (attempt recorded):
```json
{
  "status": "ok",
  "attempts_used": 1,
  "attempts_remaining": 2,
  "max_attempts": 3,
  "student_id": "S1",
  "full_name": "Ada Lovelace",
  "attempt_number": 1,
  "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"],
  "equation": "logit(P(Got Deal)) = 0.7460 + 0.0903 * Industry_Food and Beverage + 0.3893 * Industry_Travel - 0.0000 * Original Ask Amount",
  "basic_test": { "accuracy": 0.570, "yes_deal_accuracy": 0.695, "no_deal_accuracy": 0.330, "sample_size": 284 },
  "final_test": null,
  "warning": null,
  "finalized_at": 1787121482.58
}
```

**Response** `200` (all attempts already used — this student's *3rd*
attempt is returned unchanged, a 4th is never recorded):
```json
{
  "status": "attempts_exhausted",
  "attempts_used": 3,
  "attempts_remaining": 0,
  "max_attempts": 3,
  "attempt_number": 3,
  "variables": ["...the 3rd attempt's variables, not the ones just submitted..."],
  "...": "rest of the shape is the 3rd attempt's data, unchanged"
}
```

**Response** `200` (rejected: every category of one or more one-hot fields
was selected at once — see "Degenerate fits" below. No attempt was
consumed; `attempts_used`/`attempts_remaining` reflect this student's
*prior* state, unchanged):
```json
{
  "status": "invalid_selection",
  "attempts_used": 0,
  "attempts_remaining": 3,
  "max_attempts": 3,
  "variables": ["Industry_Automotive", "...", "Industry_Uncertain/Other"],
  "culprit_categories": ["Industry"],
  "message": "Can't build a model with every Industry option selected — that's the dummy variable trap (perfect multicollinearity from one-hot encoding). Deselect at least one Industry option and try again.",
  "attempted_at": 1732500000.0
}
```

`final_test` stays `null` on every attempt until the session is stopped —
this is a genuine hold-out; nothing here reveals it early.

**Errors:** `400` if any name in `variables` isn't in `USABLE_COLUMNS`, or if
statsmodels itself fails to fit at all (rare -- see "Degenerate fits"). Note:
an exhausted student's `variables` are never even looked at -- neither
validated nor checked for the dummy-variable trap (there's no attempt left
to spend on them) -- so a bad or invalid column list from a student with 0
attempts remaining still comes back `attempts_exhausted`, not `400` or
`invalid_selection`. `401` bad/missing student token; `404` unknown
session; `409` session already closed (and this student hadn't used all
their attempts before it closed).

---

### `GET /sessions/{code}/attempts`

Every attempt this student has made, oldest first. This is the endpoint to
poll (every ~1 second) right after `POST /finalize` — see "Attempts" above
for why it's the trustworthy source of truth, not the POST response.

**Headers:** `X-Student-Token: <token>`

**Response** `200`:
```json
{
  "attempts": [
    {
      "student_id": "S1",
      "full_name": "Ada Lovelace",
      "attempt_number": 1,
      "variables": ["Industry_Travel"],
      "equation": "...",
      "basic_test": { "accuracy": 0.658, "yes_deal_accuracy": 1.0, "no_deal_accuracy": 0.0, "sample_size": 284 },
      "final_test": null,
      "warning": null,
      "finalized_at": 1787121482.58
    }
  ],
  "attempts_used": 1,
  "attempts_remaining": 2,
  "max_attempts": 3
}
```

`attempts` is `[]` (not an error) if this student hasn't submitted yet.
A rejected (`invalid_selection`) submission never shows up here, by
design — it never became an attempt. `GET /status`'s `last_invalid_selection`
below is where a client checks for that instead.
Each entry's `final_test` stays `null` until the session is stopped, then
gets filled in for *every* attempt (not just the best one) — this is how a
student sees which of their 3 tries would actually have done best on the
data nobody saw.

**Errors:** `401` bad/missing student token; `404` unknown session.

---

### `GET /sessions/{code}/dashboard`

The professor's live view. Poll every 5 seconds (see "Real-time updates").

**Headers:** `X-Host-Token: <token>`

**Response** `200`:
```json
{
  "status": "open",
  "students_online": [{ "student_id": "S1", "full_name": "Ada Lovelace" }],
  "students_total": 1,
  "students_finalized": 1,
  "average_variables_chosen": 2.0,
  "leaderboard": [
    {
      "student_id": "S1",
      "full_name": "Ada Lovelace",
      "attempt_number": 1,
      "variables": ["Industry_Travel", "Original Ask Amount"],
      "equation": "...",
      "basic_test": { "accuracy": 0.570, "...": "..." },
      "final_test": null,
      "warning": null,
      "finalized_at": 1787121482.58
    }
  ]
}
```

`leaderboard` has **one entry per student who has submitted at least one
attempt** — not one entry per attempt. Each entry is that student's **best**
attempt so far by `basic_test.accuracy` (see "Attempts" above); its
`attempt_number` tells you which of their (up to 3) attempts is currently
winning, so "attempt 1" leading doesn't necessarily mean they've only tried
once. Sorted descending by `basic_test.accuracy`. `average_variables_chosen`
is the mean size of `variables` across each student's best attempt (`0` if
nobody has submitted yet). A non-`null` `warning` is visible to the
professor live — a natural moment to point out, on the spot, why that
student's number doesn't mean what it looks like it means.

**Errors:** `403` wrong `X-Host-Token`; `404` unknown session.

---

### `POST /sessions/{code}/stop`

End the session. Scores **every attempt from every student** (not just each
student's best) against the seasons 11+ final hold-out for the first time,
and returns both leaderboards. Idempotent — calling it again just returns
the same final results.

**Headers:** `X-Host-Token: <token>`

**Response** `200`:
```json
{
  "status": "closed",
  "basic_test_leaderboard": [ { "...": "one entry per student (their best attempt), sorted by basic_test.accuracy desc" } ],
  "final_test_leaderboard": [ { "...": "same students' best attempts, sorted by final_test.accuracy desc" } ]
}
```

Each entry has the same shape as a `finalize` response, now with
`final_test` populated. As with the dashboard, "best attempt" is by
basic-test accuracy — `final_test_leaderboard` is still ranking each
student's *basic-test-best* attempt on the final-test numbers, not
re-picking whichever attempt scores highest on the final test. (A student
can see that latter comparison for themselves via `GET /attempts`, where
every one of their attempts gets `final_test` filled in.)

**Errors:** `403` wrong `X-Host-Token`; `404` unknown session.

---

### `GET /sessions/{code}/status`

A student checks whether the session has ended, and if so, their results.
Also carries `last_invalid_selection` in every response, open or closed —
this is the endpoint a client polls to learn a `/finalize` submission was
rejected for selecting every category of a one-hot field, in case the
`/finalize` response itself never arrived (see "Attempts" above).

**Headers:** `X-Student-Token: <token>`

**Response** `200` while open:
```json
{ "status": "open", "last_invalid_selection": null }
```

Or, if this student's most recent `/finalize` call (or their most recent
one at the time this was polled) was rejected as a dummy-variable-trap
selection:
```json
{
  "status": "open",
  "last_invalid_selection": {
    "variables": ["Industry_Automotive", "...", "Industry_Uncertain/Other"],
    "culprit_categories": ["Industry"],
    "message": "Can't build a model with every Industry option selected — that's the dummy variable trap (perfect multicollinearity from one-hot encoding). Deselect at least one Industry option and try again.",
    "attempted_at": 1732500000.0
  }
}
```

**Response** `200` once closed:
```json
{
  "status": "closed",
  "your_attempts": [ { "...": "every attempt this student made, oldest first, each with final_test now populated" } ],
  "your_basic_test_rank": 1,
  "your_final_test_rank": 1,
  "last_invalid_selection": null
}
```

`your_attempts` is `[]` (and the rank fields `null`) if this student never
submitted before the session ended. The ranks are computed from this
student's *best* attempt (the same one representing them on both
leaderboards) — see "Attempts" above.

`last_invalid_selection` only ever holds the single most recent rejection
(not a history of every one) — a client compares its `attempted_at`
against the time it started waiting, so it only reacts to a rejection that
actually corresponds to its own pending submission, not a stale one from
earlier in the session.

By design this endpoint only reveals the calling student's own results and
rank, not the whole leaderboard with everyone's names — see "Scope and
limitations" if you'd rather make results fully public to students too.

**Errors:** `401` bad/missing student token; `404` unknown session.

---

## Scope and limitations

Worth knowing before treating this as more than a classroom tool:

- **In-memory, single-process only.** Sessions, students, submissions, and
  the model cache all live in plain Python objects in one running process.
  Restarting the server loses everything. Running multiple `uvicorn` worker
  processes would give each one its own, inconsistent copy of this state —
  run with a single worker (the default).
- **Auth is a shared secret, not real accounts.** One `PROFESSOR_API_KEY` for
  every professor using a given deployment; students are identified by
  whatever name they type plus a bearer token, with no password. Fine for a
  low-stakes in-class exercise; not suitable if impersonation or grading
  integrity actually matters.
- **No rate limiting.** `/finalize` is naturally self-limiting now (3
  attempts per student, enforced server-side), but `GET /attempts` and
  `GET /sessions/{code}/dashboard` are meant to be polled repeatedly and
  nothing throttles a client hammering them faster than intended. Not a
  concern at classroom scale (a few hundred students polling once a second
  is a trivial load for a dict lookup); would be worth adding for a public
  deployment. `/explore` (deprecated) has no cap at all, by design — it
  never consumes an attempt.
- **Students only see their own final result**, not a public list of
  everyone's names/scores — a privacy default, not a technical constraint.
  If you'd rather students see the full final leaderboard too, that's a
  small change (expose a read-only version of `/stop`'s response, or a
  variant of `/status` that includes it).
- **Polling, not push** — covered above under "Real-time updates."
- **The derived CSV is a build artifact, not the source of truth.** On
  startup the backend regenerates
  `src/economicsproject/prepared_shark_tank_dataset.csv` from the raw
  `Shark Tank US dataset.csv` (which is never modified) and loads from the
  derived file. It's gitignored — delete it any time; it's fully
  reproducible from the raw CSV plus `dataset.py`.
