# Client (barebones)

A minimal-styling Flask frontend for the deal-likelihood game backend (see
[`../API_PROTOCOL.md`](../API_PROTOCOL.md)). It serves four pages and does
no work itself — every button click calls the REST API directly from the
browser via `fetch()`.

This is the original client, kept alongside [`../client/`](../client/) (the
"Deal Probability"-designed one) as a plainer alternative — handy for
quickly eyeballing raw API responses without a styled UI in the way, or as
a simple starting point if you'd rather build your own design on top of it.
See `../client/README.md`, "Design origin," for what the styled one adds.

## Pages

- `/` — landing page, pick professor or student
- `/professor` — start a session, watch the live dashboard (polls every 5s),
  stop the session, and see both final leaderboards
- `/join` — student enters a session code + full name
- `/play` — student checks off variables (one checkbox per usable column,
  including every individual one-hot category), explores/finalizes, and
  (once the professor stops the session) sees their own final result

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
