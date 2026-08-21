# Deploying to Google Cloud (Cloud Run + buildpacks)

The backend and the client are two separate deployables (see `README.md`
and `client/README.md`) and stay that way here: this deploys each as its
own Cloud Run service, built straight from source by Google Cloud's
buildpacks -- no Dockerfile needed. Both services run continuously and
talk to each other over HTTPS, which is what "run simultaneously" means in
a Cloud Run world (there's no single machine running two processes; there
are two small, always-addressable services). This still matches the
project's existing split-server-client design -- see `CLAUDE.md`'s answer
to "is REST a good call for this project?" for why that split holds up at
Cloud Run scale too.

Only `client/` (the "Quinn Labs"-branded client) is covered below.
`client_barebones/` deploys exactly the same way -- it's a separate Flask
app with the same shape (`requirements.txt`, `app.py` reading `PORT`) --
just repeat the client steps with `--source client_barebones` and its own
service name if you want it running too.

## Prerequisites

- A Google Cloud project with billing enabled and the Cloud Run and Cloud
  Build APIs turned on (`gcloud services enable run.googleapis.com
  cloudbuild.googleapis.com`).
- The `gcloud` CLI, authenticated (`gcloud auth login`) and pointed at your
  project (`gcloud config set project <PROJECT_ID>`).
- A region to deploy into, e.g. `us-central1` -- substitute your own below.

No `docker` install is required: `gcloud run deploy --source` uploads the
source and builds it in the cloud with Google's buildpacks.

## 1. Deploy the backend first

From the repo root:

```bash
gcloud run deploy deal-game-backend \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --set-env-vars PROFESSOR_API_KEY=<a-real-secret>
```

What makes this buildable as-is:

- The root `Procfile` (`web: uvicorn economicsproject.server:app --host
  0.0.0.0 --port $PORT`) tells the buildpack how to start it -- Cloud Run
  always sets `$PORT` itself, so this doesn't need a fallback.
- `requirements.txt` ends with `-e .`, so the buildpack's `pip install -r
  requirements.txt` also installs this project itself in editable mode
  (same as the local `pip install -e .` step in `README.md`) -- without
  that line, `economicsproject.server:app` wouldn't be importable.
- `.python-version` pins the buildpack to Python 3.11, matching what this
  project's been developed and tested against.
- `.gcloudignore` keeps `client/`, `client_barebones/`, and `tests/` out of
  the upload -- the backend doesn't need them.
- The raw dataset (`src/economicsproject/Shark Tank US dataset.csv`) is
  committed to the repo, so it ships with the source upload automatically;
  the derived, prepared CSV regenerates itself into the container's
  writable filesystem on first request, same as it does locally (see
  `dataset.py`).

`--allow-unauthenticated` makes the service reachable from a browser at
all -- `PROFESSOR_API_KEY` (not Cloud Run's own IAM) is still the real
gate on starting a session, exactly as documented in `API_PROTOCOL.md`,
"Auth model." **Set a real key here, not the `change-me` default** -- see
that section for why the default is insecure.

`--memory 512Mi` gives `statsmodels`/`scipy` reasonable headroom to fit a
model; the Cloud Run default (256Mi) can be tight. Bump it further if you
see the service get OOM-killed under load.

Once it finishes, note the printed **Service URL** (something like
`https://deal-game-backend-xxxxxxxxxx.us-central1.run.app`) -- the client
needs it next.

## 2. Deploy the client, pointed at the backend

```bash
gcloud run deploy deal-game-client \
  --source client \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars API_BASE_URL=<backend-service-url-from-step-1>
```

What makes *this* buildable as-is:

- `client/Procfile` (`web: HOST=0.0.0.0 python app.py`) starts the Flask
  dev server bound to all interfaces -- required for Cloud Run's health
  check to reach it at all (the local default, `127.0.0.1`, is
  unreachable from outside the container and is left as-is for local dev;
  this env var override is scoped to the Procfile, not a code change).
  `app.py` already reads `PORT` from the environment, and Cloud Run
  injects that itself.
- `client/requirements.txt` just needs `flask` -- already there.
- `client/.python-version` and `client/.gcloudignore` mirror the root
  ones, scoped to this subdirectory as the build source.
- `API_BASE_URL` is baked into every page as `window.API_BASE_URL` at
  request time (see `client/app.py`'s `inject_globals`), so the browser's
  own `fetch()` calls go straight to the backend's Cloud Run URL -- no
  server-side proxying involved, same as running both locally.

Once it finishes, the printed Service URL is what you actually hand to a
professor and students.

## 3. (Optional) tighten CORS

The backend's default `CORS_ORIGINS=*` (see `API_PROTOCOL.md`, "Scope and
limitations") already lets the deployed client reach it with zero extra
config -- fine for a classroom exercise. To restrict it to just the
client's real origin once you have that URL from step 2:

```bash
gcloud run deploy deal-game-backend \
  --source . \
  --region us-central1 \
  --update-env-vars CORS_ORIGINS=<client-service-url-from-step-2>
```

## Deploying via the Cloud Console (the web UI, no CLI)

Everything above also works by clicking through
[console.cloud.google.com/run](https://console.cloud.google.com/run)
instead of running `gcloud` -- same `Procfile`/buildpack setup, just
triggered from GitHub instead of an upload from your machine. This also
gets you continuous deployment for free: every push to the branch you pick
triggers a rebuild and redeploy automatically, no `gcloud run deploy`
needed again after the first setup.

**Backend, first:**

1. Cloud Run → **Create service**.
2. Choose **"Continuously deploy from a repository"** → **Set up with
   Cloud Build**.
3. Connect your GitHub account if you haven't, then pick this repo and the
   branch to deploy from.
4. **Build type: Google Cloud Buildpacks** (not Dockerfile -- there isn't
   one, and there doesn't need to be). Leave the **build context
   directory** as `/` (the repo root) -- that's where the root `Procfile`
   and `requirements.txt` live.
5. Service name (e.g. `deal-game-backend`), region, and under
   **Authentication**, allow unauthenticated invocations (same reason as
   `--allow-unauthenticated` above -- `PROFESSOR_API_KEY` is the real gate,
   not Cloud Run's IAM).
6. Before creating, open **Container(s), Volumes, Networking, Security**:
   - **Variables & Secrets** tab → add `PROFESSOR_API_KEY` = a real secret
     (or wire it to a Secret Manager secret via **Reference a Secret**
     instead of a plain variable -- see "Rotating the professor key"
     below).
   - **Container** tab → memory `512 MiB`.
   - **Revision scaling** → set **maximum instances** to `1` (and,
     optionally, **minimum instances** to `1`) -- see "Notes and caveats"
     below for why.
7. **Create.** Cloud Build runs, and once it's done the service's URL is
   shown at the top of its page -- copy it for the next part.

**Then the client, the same way:**

1. Cloud Run → **Create service** → **Continuously deploy from a
   repository** → same repo/branch.
2. **Build type: Google Cloud Buildpacks**, but this time set the **build
   context directory** to `/client` -- that's where `client/Procfile` and
   `client/requirements.txt` live.
3. Service name (e.g. `deal-game-client`), same region, allow
   unauthenticated invocations.
4. **Variables & Secrets** tab → add `API_BASE_URL` = the backend URL you
   copied above.
5. **Create.**

Once both exist, the client service's URL is what you hand to a professor
and students. To tighten CORS afterward (the optional step 3 above), open
the backend service → **Edit & deploy new revision** → **Variables &
Secrets** → add/edit `CORS_ORIGINS` to the client's URL → **Deploy**.

## Redeploying after a code change

**CLI path:** re-run the same `gcloud run deploy` command for whichever
service changed (backend: step 1's command from the repo root; client:
step 2's command from `client/`) -- `gcloud` rebuilds from the current
source and rolls out a new revision. Environment variables you set with
`--set-env-vars` persist across redeploys unless you explicitly change
them; use `--update-env-vars` (as in step 3) to change just one without
repeating all of them.

**Console path:** nothing to do -- push to the branch you connected and
Cloud Build redeploys it automatically. To trigger one without a new
commit, open the service in the console and use **Edit & deploy new
revision** → **Deploy**.

## Rotating the professor key

**CLI:** update the running backend service directly -- this deploys a new
revision with the new value using the *already-built* image, no rebuild:

```bash
gcloud run services update deal-game-backend \
  --region us-central1 \
  --update-env-vars PROFESSOR_API_KEY=<new-secret>
```

**Console:** backend service → **Edit & deploy new revision** →
**Variables & Secrets** → edit `PROFESSOR_API_KEY` → **Deploy**.

Either way, it takes effect immediately for new requests, but anyone
already signed in as professor in the client has the *old* key cached in
their browser's `sessionStorage` -- they need to sign out and back in with
the new one (starting a session works fine regardless; it's only the
client's cached admin-key field that goes stale).

For a plain env var, the key sits in your shell history / the revision's
config in plaintext. Secret Manager avoids that and makes rotation a
one-liner that doesn't touch the Cloud Run service config again:

```bash
# first time only: create the secret, and point the service at it
echo -n "<a-real-secret>" | gcloud secrets create professor-api-key --data-file=-
gcloud run services update deal-game-backend \
  --region us-central1 \
  --update-secrets PROFESSOR_API_KEY=professor-api-key:latest

# to rotate later, just add a new version -- no service update needed
echo -n "<newer-secret>" | gcloud secrets versions add professor-api-key --data-file=-
```

In the console, the equivalent is Secret Manager → **Create secret**, then
back in the backend service's **Variables & Secrets** tab, **Reference a
secret** instead of adding a plain variable.

## Notes and caveats

- **State is still in-memory and single-process** (see `API_PROTOCOL.md`,
  "Scope and limitations") -- this is unchanged by deploying to Cloud Run.
  Keep the backend service's instance count effectively pinned to one
  live session at a time: Cloud Run can still scale it to zero when idle
  and back up on the next request (a cold start, not a problem by itself),
  but if it scales to *more than one concurrent instance* mid-session,
  each instance has its own separate copy of session state and students
  could land on different ones. Setting `--max-instances 1` on the backend
  service is the simplest way to guarantee this for a single professor's
  session:

  ```bash
  gcloud run deploy deal-game-backend --source . --max-instances 1 ...
  ```

  This does mean the backend serves one request at a time under real
  concurrency, which is fine at the request rates this project already
  documents as its scale target (a few hundred students polling once a
  second).
- **Cold starts** reset all session state (a new instance starts with an
  empty `SessionStore`) -- if the backend scales to zero between a
  professor starting a session and it actually being used, that's
  equivalent to a restart. Setting `--min-instances 1` keeps one instance
  always warm for the duration of a class (small ongoing cost).
- Neither service needs a database or Cloud Storage bucket to work --
  env vars are enough for a classroom deployment. Secret Manager is an
  optional upgrade for `PROFESSOR_API_KEY` specifically -- see "Rotating
  the professor key" above.
