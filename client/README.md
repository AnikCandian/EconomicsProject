# Client

A Flask frontend for the deal-likelihood game backend (see
[`../API_PROTOCOL.md`](../API_PROTOCOL.md)). It serves three pages and does
no work itself — every button click calls the REST API directly from the
browser via `fetch()`.

The visual design is a reimplementation of a "Deal Probability" mockup built
in Claude Design (claude.ai/design) — see "Design origin" below for what
came from the mockup, what changed, and why.

A plainer, minimal-styling client also lives at
[`../client_barebones/`](../client_barebones/) — same pages, same API, no
design system on top. Handy for eyeballing raw API responses, or as a
starting point for a different design. Both can run at once (this one on
port 5000, the barebones one on 5001 by default).

## Pages

- `/` — landing: student join (session code + name), or an administrator
  sign-in toggle
- `/play` — student's model builder: a checkbox per usable variable
  (grouped, every one-hot category individually selectable), explore/save,
  and its own final result once the session ends
- `/professor` — start/stop a session, a live-polled dashboard (leaderboard,
  who's online, most-included predictors, accuracy distribution — all
  computed from the real, current session), and Final Results once stopped

## Running

The backend must already be running separately (see the repo root README).
Then, in a second terminal:

```bash
cd client
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
API_BASE_URL=http://127.0.0.1:8000 python app.py
```

Serves on `http://127.0.0.1:5000` by default (override with `HOST`/`PORT`).
`API_BASE_URL` is baked into every page as `window.API_BASE_URL` so the
browser knows where to send its `fetch()` calls — point it at wherever the
FastAPI backend actually runs.

Requires the backend's CORS to allow this page's origin (`CORS_ORIGINS` env
var on the backend; the default `"*"` already covers this).

## Design origin

The mockup (`Deal Probability.dc.html`, a Claude Design canvas prototype)
was translated by hand into plain Flask templates + vanilla JS + a ported
CSS stylesheet (`static/css/design.css`) — none of the prototype's own
runtime (`support.js`, the `<x-dc>`/`sc-if`/`sc-for` custom elements) ships
here; only its color tokens, typography, spacing, and layout were carried
over. A few things in the mockup don't correspond to anything this backend
actually does, and were adapted rather than faked:

- **The whole "fitted logit curve" and its accuracy number were simulated
  client-side math** (a fake `signal`/`slope` formula, no real fit
  happening). Replaced with real `/explore` calls, debounced on every
  checkbox change — the entire point of this rebuild.
- **Admin-configurable training seasons.** The mockup lets an admin toggle
  which seasons train the model at runtime. The backend has a fixed split
  (seasons 1–7 train, 8–10 basic test, 11+ held out) with no such endpoint,
  so that control became a real, static readout instead of a decorative one
  that did nothing.
- **"Historical" tab / 30-day trend chart.** Assumed persisted history
  across many past sessions; the backend is explicitly single-session,
  in-memory, no persistence (see `API_PROTOCOL.md`, "Scope and
  limitations"). Repurposed as **Final Results** — the real two leaderboards
  from `POST /stop`, populated only once a session actually ends.
- **Session codes.** The mockup uses fake `LGT-XXXX` codes; ours are the
  backend's real 6-digit codes.
- **Administrator password.** Mapped directly to the real
  `PROFESSOR_API_KEY` — there's no way to validate it without creating a
  session, so it's stashed in `sessionStorage` at sign-in and checked for
  real the moment "Start session" is clicked.
- **Predictor list.** The mockup hardcodes 33 fictional predictors
  (including a `Business Description` column the real dataset doesn't
  expose as usable). The real 34 come from `/join`'s response instead, and
  "Pitchers Gender" is its own group of 3 individually-selectable toggles
  rather than one collapsed toggle — matching the backend's
  individually-selectable-category design (see the repo root `CLAUDE.md`).
- **Role separation.** The mockup lets one demo user freely switch between
  "Model builder" and "Monitoring" in a shared nav. The real backend has
  genuinely different tokens for each role (a student token can't call the
  professor endpoints and vice versa), so here they're structurally
  separate: `/play` never shows a Monitoring tab, `/professor` never shows
  a Model builder tab.
- **"Most-included predictors" and "Accuracy distribution."** Kept, but now
  computed client-side from the real, current session's leaderboard on
  every poll — not the mockup's fabricated multi-day dataset.

## Notes

- No server-side session/state here. The professor's host token and
  session code live in `sessionStorage` (survive a refresh in the same tab,
  cleared when the tab closes); each student's token lives in
  `localStorage` (survives closing/reopening the tab too).
- Every response is shown close to raw on the student page — a collapsible
  "Raw response" block — so it's easy to see exactly what the API returned
  while testing.
- This is a separate deployable from the backend (own `requirements.txt`,
  own venv) since it's a genuinely different service that could run on a
  different host.
- The Google Fonts `<link>` loads non-blocking (`media="print"` swapped to
  `"all"` on load) — a font host that's slow or unreachable (some classroom
  networks restrict outbound access) never holds up the page. This isn't
  cosmetic caution: a synchronous stylesheet load blocking a same-page
  inline `<script>` is exactly what caused client-side navigation to hang
  during development.
