# Client (barebones)

A minimal-styling Flask frontend for the deal-likelihood game backend (see
[`../API_PROTOCOL.md`](../API_PROTOCOL.md)). It serves four pages and does
no work itself — every button click calls the REST API directly from the
browser via `fetch()`.

This is the original client, kept alongside [`../client/`](../client/) (the
"Quinn Labs"-branded, designed one) as a plainer alternative — handy for
quickly eyeballing raw API responses without a styled UI in the way, or as
a simple starting point if you'd rather build your own design on top of it.
See `../client/README.md`, "Design origin," for what the styled one adds.

## Pages

- `/` — landing page, pick professor or student
- `/professor` — start a session, watch the live dashboard (polls every 5s),
  stop the session, and see both final leaderboards
- `/join` — student enters a session code + full name
- `/play` — student checks off variables (one checkbox per usable column,
  including every individual one-hot category) and submits up to 3 scored
  attempts (`POST /finalize`), with a running "Your attempts" table fed by
  `GET /attempts`; once the professor stops the session, each attempt also
  shows its final-test result

## Running

The backend must already be running separately (see the repo root README).
Then, in a second terminal:

```bash
cd client_barebones
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
API_BASE_URL=http://127.0.0.1:8000 python app.py
```

Serves on `http://127.0.0.1:5001` by default (`../client/` defaults to
`5000`, so both can run side by side on one machine without a port clash —
override either with `HOST`/`PORT`). `API_BASE_URL` is baked into every page
as `window.API_BASE_URL` so the browser knows where to send its `fetch()`
calls — point it at wherever the FastAPI backend actually runs.

For letting students join from their own devices (phones included) rather
than just testing on one machine, see `../client/README.md`, "Running for a
real classroom" — the same `HOST`/`API_BASE_URL` steps apply here, just
swap in this directory and its port (5001).

Requires the backend's CORS to allow this page's origin (`CORS_ORIGINS` env
var on the backend; the default `"*"` already covers this).

## Attempts, not live exploring

`POST /sessions/{code}/explore` still exists on the backend (kept, marked
deprecated, for rollback) but this client never calls it — there's no live
fit-as-you-check-boxes preview. `play.js` only calls `POST /finalize`
("Submit attempt"), which is scored for real and consumes one of 3
attempts. After that POST, the page doesn't trust the response by itself:
it disables the form and polls both `GET /sessions/{code}/attempts` (did
the attempt count go up?) and `GET /sessions/{code}/status` (was it
rejected instead?) every 1 second until one of those resolves, then
re-enables the form (or shows the relevant banner). This guards against a
dropped HTTP response after the attempt was already consumed server-side.
If 3 polls in a row show neither, the client resends the identical POST —
the original request may never have reached the server at all, not just
its response getting lost, and that would otherwise leave the page stuck
on "Submitted..." forever. This is a plain retry, not a different request,
so if the original POST actually did land, this creates a second, genuine
attempt with the same variables; that's an accepted trade for not leaving
students stuck with no feedback. It's all client-side-only behavior — the
server enforces the 3-attempt cap regardless, not "wait for a poll before
resubmitting." See the repo root `CLAUDE.md` and `API_PROTOCOL.md`,
"Attempts," for the full rationale.

Selecting every value of a one-hot field (currently just "Industry") is
never sent to the server at all -- `play.js` checks it live as boxes are
(un)checked (`fullySelectedCategories()` in `api.js`) and shows a short
banner instead of letting "Submit attempt" fire. The server enforces the
same rule independently in case that check is ever bypassed.

## Notes

- No server-side session/state here. The professor's host token lives only
  in a page-local JS variable (lost on refresh — reasonable for a live
  screen-share); each student's token lives in `localStorage` so refreshing
  `/play` doesn't lose their place.
- Deliberately barebones: minimal styling, and every response is shown close
  to raw — the student page includes a collapsible "Raw response" block —
  so it's easy to see exactly what the API returned.
- This is a separate deployable from both the backend and `../client/` (own
  `requirements.txt`, own venv) since each is a genuinely different service
  that could run on a different host.
