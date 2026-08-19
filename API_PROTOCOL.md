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

`GET`/`POST` responses that mention usable columns are always drawn from this
fixed set (`economicsproject.dataset.USABLE_COLUMNS`):

```
Episode Number, Pitch Number, Industry, Pitchers Gender, Multiple Entrepreneurs,
US Viewership, Original Ask Amount, Original Offered Equity, Valuation Requested,
Barbara Corcoran Present, Mark Cuban Present, Lori Greiner Present,
Robert Herjavec Present, Daymond John Present, Kevin O Leary Present,
Guest Present, Season Number
```

Two of those are categories, not numbers, and get one-hot encoded
automatically wherever they're used — students just refer to them by their
plain name (`"Industry"`, `"Pitchers Gender"`), never by dummy-column name:

- **Industry** (16 values): Food and Beverage, Lifestyle/Home, Fashion/Beauty,
  Fitness/Sports/Outdoors, Children/Education, Health/Wellness,
  Technology/Software, Pet Products, Business Services, Media/Entertainment,
  Uncertain/Other, Electronics, Automotive, Green/CleanTech, Liquor/Alcohol,
  Travel
- **Pitchers Gender** (3 values): Male, Female, Mixed Team

`POST /sessions/{code}/join` echoes both `usable_columns` and `categories` in
its response so a frontend can build its variable picker without hardcoding
this list.

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

## Model caching

The backend fits a logit model for a given *set* of variables (order and
duplicates don't matter — `["Industry", "Original Ask Amount"]` and
`["Original Ask Amount", "Industry", "Industry"]` are the same model) **at
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
  "usable_columns": ["Episode Number", "Pitch Number", "Industry", "..."],
  "categories": {
    "Industry": ["Food and Beverage", "Lifestyle/Home", "..."],
    "Pitchers Gender": ["Male", "Female", "Mixed Team"]
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
{ "variables": ["Industry", "Original Ask Amount"] }
```

**Response** `200` (first time, or any time before this student finalizes):
```json
{
  "status": "ok",
  "variables": ["Industry", "Original Ask Amount"],
  "equation": "logit(P(Got Deal)) = 0.2392 + 0.1527 * Industry_Lifestyle/Home - ...",
  "basic_test": { "accuracy": 0.570, "yes_deal_accuracy": 0.695, "no_deal_accuracy": 0.330, "sample_size": 284 }
}
```

**Response** `200` (if this student already finalized — see "Real-time
updates" for why this is a response, not a push):
```json
{
  "status": "already_submitted",
  "student_id": "S1",
  "full_name": "Ada Lovelace",
  "variables": ["Industry", "Original Ask Amount"],
  "equation": "...",
  "basic_test": { "...": "..." },
  "final_test": null,
  "finalized_at": 1787121482.58
}
```

`final_test` stays `null` until the session is stopped.

**Errors:** `400` if any name in `variables` isn't in `USABLE_COLUMNS`; `401`
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
      "variables": ["Industry", "Original Ask Amount"],
      "equation": "...",
      "basic_test": { "accuracy": 0.570, "...": "..." },
      "final_test": null,
      "finalized_at": 1787121482.58
    }
  ]
}
```

`leaderboard` only contains students who have **finalized** — someone still
exploring doesn't show up (or affect the ranking) until they commit.
Sorted descending by `basic_test.accuracy`. `average_variables_chosen` is the
mean size of `variables` across finalized submissions only (`0` if nobody has
finalized yet).

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
