# Deal-Likelihood Game — API Protocol

A classroom game where a professor hosts a session (a "server," Kahoot-style),
students join with a code, pick predictor variables, and get live feedback on
how well a logit model built from those variables predicts Shark Tank deal
outcomes. The professor watches a live dashboard and, at the end, gets two
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
| Student | `X-Student-Token` | Response of `POST /sessions/{code}/join` | `POST /sessions/{code}/explore`, `POST /sessions/{code}/finalize`, `GET /sessions/{code}/status` |

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

## Degenerate fits

A student can select every category of the same one-hot field at once (e.g.
all 16 `Industry_*` columns). This is allowed on purpose rather than
rejected — it's a genuinely instructive mistake, and blocking it teaches
nothing. But it does make the design matrix perfectly multicollinear: those
16 dummy columns sum to 1 for every row, exactly duplicating the intercept
column. That has a real consequence worth understanding, not just avoiding.

**What actually happens, numerically:** the fit doesn't error out. statsmodels
happily reports "Optimization terminated successfully" and hands back an
equation that looks completely normal. But there's no unique solution —
shift the intercept by any constant `c` and every one of that field's
coefficients by `-c`, and you get *identical* predictions for every row
(exactly one dummy is always 1, so the `+c`/`-c` always cancels). That's an
entire line of equally-"correct" coefficient vectors, not one answer.
Empirically: Newton's method, BFGS, and L-BFGS each converge to *different*
numbers on the exact same data (we checked — predicted probabilities
differed by up to 3.5 percentage points between solvers), standard errors
come back `NaN`, and the design matrix's condition number is on the order of
10¹⁵ (numerically singular).

So the backend detects this directly (design-matrix rank deficiency via
`numpy.linalg.matrix_rank`, not by pattern-matching "did they pick every
category" — the same detection catches any combination of variables that
happens to be exactly collinear, not just this one anticipated case) and
attaches a `warning` string to the response explaining it. `warning` is
`null` on every normal fit, and appears on `explore`/`finalize` responses
and on leaderboard entries (so a professor can see, live, if a student's
model is degenerate):

```json
{
  "status": "ok",
  "variables": ["Industry_Automotive", "...", "Industry_Uncertain/Other"],
  "equation": "logit(P(Got Deal)) = -0.0259 + 0.3135 * Industry_Automotive + ...",
  "basic_test": { "accuracy": 0.560, "yes_deal_accuracy": 0.695, "no_deal_accuracy": 0.299, "sample_size": 284 },
  "warning": "This variable set is perfectly multicollinear: every category of 'Industry' was selected at once, so those dummy columns sum to 1 for every row -- exactly duplicating the intercept. There is no unique best-fit answer -- the coefficients below are just one arbitrary point among infinitely many that score identically. Different solvers (or even the same solver from a different starting point) can return different numbers for the exact same data, and standard errors are undefined. Treat this as a demonstration of a broken fit, not a usable model."
}
```

(A genuinely unfittable design matrix — statsmodels hard-fails rather than
silently returning an arbitrary answer — is the one case that *does* still
come back as an error: `400` with a `detail` explaining the same thing. This
is rare; every case we've tried, including the full-category one above,
returns a degenerate-but-present result instead.)

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
   403/409 they'll get on their next `explore`/`finalize` call after
   `/stop` — there's no way for the backend to interrupt them mid-session.
   Use `GET /sessions/{code}/status` for this; poll it however often feels
   right (a few seconds is plenty).

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
  }
}
```

`student_token` identifies this student for every subsequent call — store it
client-side (e.g. `sessionStorage`) and send it as `X-Student-Token`.

**Errors:** `404` unknown `code`; `400` empty `full_name`.

---

### `POST /sessions/{code}/explore`

Try out a set of variables. Cheap and repeatable — call this as often as a
student wants while they experiment.

**Headers:** `X-Student-Token: <token>`

**Request body:**
```json
{ "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"] }
```

**Response** `200` (first time, or any time before this student finalizes):
```json
{
  "status": "ok",
  "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"],
  "equation": "logit(P(Got Deal)) = 0.7460 + 0.0903 * Industry_Food and Beverage + 0.3893 * Industry_Travel - 0.0000 * Original Ask Amount",
  "basic_test": { "accuracy": 0.570, "yes_deal_accuracy": 0.695, "no_deal_accuracy": 0.330, "sample_size": 284 },
  "warning": null
}
```

`warning` is non-`null` if this exact variable set makes the fit
numerically degenerate (e.g. every category of one field selected at once)
-- see "Degenerate fits" above. It's still a `200` with a real, fitted
equation; the model just isn't a meaningful one.

**Response** `200` (if this student already finalized — see "Real-time
updates" for why this is a response, not a push):
```json
{
  "status": "already_submitted",
  "student_id": "S1",
  "full_name": "Ada Lovelace",
  "variables": ["Industry_Food and Beverage", "Industry_Travel", "Original Ask Amount"],
  "equation": "...",
  "basic_test": { "...": "..." },
  "final_test": null,
  "warning": null,
  "finalized_at": 1787121482.58
}
```

`final_test` stays `null` until the session is stopped.

**Errors:** `400` if any name in `variables` isn't in `USABLE_COLUMNS`, or if
statsmodels itself fails to fit at all (rare -- see "Degenerate fits"); `401`
bad/missing student token; `404` unknown session; `409` session already
closed (and this student hadn't already finalized before it closed).

---

### `POST /sessions/{code}/finalize`

Lock in a variable set. One-shot per student — calling it again just returns
the original submission unchanged (`status: "already_submitted"`), even with
different `variables` in the body.

**Headers:** `X-Student-Token: <token>`

**Request body:** same shape as `/explore`.

**Response** `200`: same shape as `/explore`'s `already_submitted` response
above, with `status: "ok"` the first time.

**Errors:** same as `/explore`.

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

`leaderboard` only contains students who have **finalized** — someone still
exploring doesn't show up (or affect the ranking) until they commit.
Sorted descending by `basic_test.accuracy`. `average_variables_chosen` is the
mean size of `variables` across finalized submissions only (`0` if nobody has
finalized yet). A non-`null` `warning` on a leaderboard entry is visible to
the professor live — a natural moment to point out, on the spot, why that
student's number doesn't mean what it looks like it means.

**Errors:** `403` wrong `X-Host-Token`; `404` unknown session.

---

### `POST /sessions/{code}/stop`

End the session. Scores every finalized submission against the seasons 11+
final hold-out for the first time, and returns both leaderboards. Idempotent
— calling it again just returns the same final results.

**Headers:** `X-Host-Token: <token>`

**Response** `200`:
```json
{
  "status": "closed",
  "basic_test_leaderboard": [ { "...": "one entry per finalized student, sorted by basic_test.accuracy desc" } ],
  "final_test_leaderboard": [ { "...": "same entries, sorted by final_test.accuracy desc" } ]
}
```

Each entry has the same shape as a `finalize` response, now with `final_test`
populated.

**Errors:** `403` wrong `X-Host-Token`; `404` unknown session.

---

### `GET /sessions/{code}/status`

A student checks whether the session has ended, and if so, their own result.

**Headers:** `X-Student-Token: <token>`

**Response** `200` while open:
```json
{ "status": "open" }
```

**Response** `200` once closed:
```json
{
  "status": "closed",
  "your_submission": { "...": "same shape as a finalize response, with final_test populated" },
  "your_basic_test_rank": 1,
  "your_final_test_rank": 1
}
```

`your_submission` is `null` (and the rank fields omitted from being
meaningful) if this student never finalized before the session ended.

By design this endpoint only reveals the calling student's own result and
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
- **No rate limiting.** `/explore` is meant to be hit repeatedly and cheaply
  (that's the point), and nothing currently throttles a student hammering
  it. Not a concern at classroom scale; would be worth adding for a public
  deployment.
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
