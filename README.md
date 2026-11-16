# Morning Blick

Morning Blick is a FastAPI app for a daily morning overview. Its start page shows the
date and four live cards: Berlin weather (Open-Meteo), transport disruptions (VBB),
today's calendar events (Nylas) and the top Hacker News stories. It also connects to email through
[Nylas](https://www.nylas.com/) (API v3, official `nylas` Python SDK):

- sign in to a mailbox with OAuth (or use a fixed grant from `.env`)
- list recent emails and send an email
- receive a webhook for every new email (`message.created`), with signature verification

All four cards are fetched concurrently on each page load (with a small in-memory cache).
If one source is slow or down, only its card shows "Currently unavailable".

## Project structure

```
morning_blick/
├── app/                          # the application package
│   ├── main.py                   # create_app(): FastAPI app, session middleware, routers; main() entry point
│   ├── api/
│   │   ├── routes.py             # start page, /ask, /health
│   │   ├── nylas_routes.py       # Nylas OAuth, email and webhook routes
│   │   └── session.py            # cookie-based in-memory session middleware
│   ├── config/settings.py        # Settings + get_settings(), values from env / .env
│   ├── database/                 # work in progress, not wired in yet: SQLAlchemy session,
│   │                             #   ProcessedWebhook model, mark_processed() for webhook dedup
│   ├── schemas/                  # pydantic models: briefing (page view model), weather,
│   │                             #   hackernews, vbb, Nylas email/events/webhook
│   ├── services/
│   │   ├── briefing.py           # build_briefing(): runs all providers in a thread pool
│   │   ├── weather.py            # Open-Meteo forecast -> weather card
│   │   ├── hackernews.py         # Hacker News top stories -> news card
│   │   ├── vbb.py                # VBB departures -> transport card (get_departures())
│   │   ├── cache.py              # small thread-safe in-memory TTL cache
│   │   ├── http.py               # shared httpx2 client factory, http(s) URL check
│   │   ├── nylas_service.py      # Nylas client factory, OAuth, email, today's events
│   │   └── nylas_webhook.py      # webhook signature check (HMAC-SHA256)
│   ├── scripts/create_webhook.py # one-off script that registers the Nylas webhook
│   ├── templates/index.html      # start page
│   └── notebooks/                # exploration notebooks (not used by the running app)
├── docs/cloudflared-config.example.yml   # tunnel config that exposes only /events
├── tests/                        # pytest tests, fully offline; fixtures/ holds hand-written JSON
├── docker-compose.yml            # only a Docker setup check for now (no app or database service)
├── .env.example                  # copy to .env and fill in
└── pyproject.toml
```

## Setup and run

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
cp .env.example .env             # then fill in your values (never commit .env)
uv sync                          # install app + dev dependencies
uv run uvicorn app.main:app --reload   # http://127.0.0.1:8000
# or: uv run morning-blick
uv run pytest                    # run the tests
```

API docs: http://127.0.0.1:8000/docs

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `APP_NAME`, `DEBUG`, `HOST`, `PORT` | General app settings |
| `NYLAS_API_KEY` | Nylas API key (required for all Nylas features) |
| `NYLAS_API_URI` | Nylas API region, default `https://api.us.nylas.com` |
| `NYLAS_CLIENT_ID` | Nylas application id, used for OAuth |
| `NYLAS_GRANT_ID` | Optional: a fixed grant; if set, the OAuth flow is skipped |
| `EMAIL` | Your address: reply-to for sent emails, notification address for the webhook |
| `APP_BASE_URL` | Base URL of this app, default `http://localhost:8000` |
| `SERVER_URL` | Public `https://` URL of the tunnel, used for the webhook |
| `NYLAS_WEBHOOK_SECRET` | Secret printed by `create_webhook`; required to accept webhooks |
| `TIMEZONE` | Time zone for "today" and event times, default `Europe/Berlin` |
| `HTTP_TIMEOUT`, `PROVIDER_TIMEOUT` | Seconds per HTTP request (5) and per card provider (8) |
| `WEATHER_LATITUDE`, `WEATHER_LONGITUDE`, `WEATHER_TIMEZONE` | Weather location, default Berlin |
| `HN_STORY_COUNT` | Number of Hacker News stories, default 5 |
| `VBB_STOP_ID`, `VBB_DURATION_MINUTES`, `VBB_MIN_DELAY_MINUTES` | Transport stop, look-ahead window (30) and delay threshold (3) |
| `CACHE_TTL_WEATHER`, `CACHE_TTL_HN`, `CACHE_TTL_VBB`, `CACHE_TTL_NYLAS` | Cache lifetimes in seconds (900, 600, 60, 60) |

The schedule card uses `NYLAS_API_KEY` plus `NYLAS_GRANT_ID` or the signed-in session;
without them it shows "Currently unavailable".

`OPENAI_API_KEY` and the `POSTGRES_*` / `DATABASE_URL` entries in `.env.example` are
reserved for later milestones; the running app does not read them yet. Only the unfinished
`app/database/session.py` reads `DATABASE_URL`, and nothing imports that module yet.

### Finding a VBB stop id

The transport card shows delays and cancellations for one stop (`VBB_STOP_ID`,
default `900100003` = S+U Alexanderplatz Bhf). To find the id of another stop, search
for it by name:

```bash
curl 'https://v6.vbb.transport.rest/locations?query=Ostkreuz&results=5&addresses=false&poi=false'
```

Each result with `"type": "stop"` has an `id`; put it into `.env` as `VBB_STOP_ID`.
Only delays of at least `VBB_MIN_DELAY_MINUTES` (default 3) and cancellations within the
next `VBB_DURATION_MINUTES` (default 30) are shown; otherwise the card says "No disruptions".

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/` | Start page with the live morning briefing |
| POST | `/ask` | Form field `question`; echoes it back |
| GET | `/health` | Health check |
| GET | `/nylas/auth` | Returns the grant id, or redirects to the Nylas login |
| GET | `/oauth/exchange` | OAuth callback; stores the grant id in the session |
| GET | `/nylas/recent-emails` | Recent emails of the signed-in mailbox |
| POST | `/nylas/send-email` | Body `{"subject": "...", "body": "...", "to_email": "..."}` |
| GET | `/events` | Answers the Nylas webhook challenge |
| POST | `/events` | Receives Nylas webhooks (requires a valid `x-nylas-signature`) |

The email routes return `401 Not authenticated` until a grant is available, either from
`NYLAS_GRANT_ID` or after signing in via `/nylas/auth`. Sessions are kept in memory and
reset whenever the app restarts.

## Nylas OAuth sign-in

1. In the Nylas dashboard, register the redirect URI `APP_BASE_URL/oauth/exchange`
   (by default `http://localhost:8000/oauth/exchange`, exactly as written).
2. Open http://localhost:8000/nylas/auth and sign in to your mailbox.
3. You are redirected back and `/nylas/auth` shows your grant id; the email routes now work.

## Nylas webhook setup (`message.created`)

`POST /events` accepts a delivery only with a valid `x-nylas-signature` (HMAC-SHA256 of
the raw body, keyed with `NYLAS_WEBHOOK_SECRET`); everything else gets `401`. The
Cloudflare tunnel exposes only `/events`. Setup order:

0. Install `cloudflared` once (Debian/Ubuntu/WSL; the `.deb` is not part of the repo):
   ```bash
   curl -LO https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
   sudo dpkg -i cloudflared-linux-amd64.deb && rm cloudflared-linux-amd64.deb
   ```
1. Start the app: `uv run uvicorn app.main:app --reload`
2. Copy [docs/cloudflared-config.example.yml](docs/cloudflared-config.example.yml) to
   `docs/cloudflared-config.yml` (git-ignored), fill in the placeholders and start the tunnel;
   set `SERVER_URL=https://<tunnel-hostname>` in `.env`.
3. Create the webhook: `uv run python -m app.scripts.create_webhook`
   (Nylas sends a challenge to `/events` during creation, so steps 1–2 must be running).
4. Copy the printed secret into `.env` as `NYLAS_WEBHOOK_SECRET` (never commit it).
5. Restart the app so the new secret is loaded.

## Tests

`uv run pytest` runs the whole suite. It never touches the network: `tests/conftest.py`
replaces the app's httpx2 client with one that refuses to connect and blocks the Nylas
SDK's HTTP calls. Provider tests pass in an `httpx2.MockTransport` client (or a mocked
Nylas client) fed with hand-written fixtures in `tests/fixtures/*.json`, shaped after the
official docs. Caches are cleared before and after every test.

## Data sources and attribution

| Card | Source | Licence / terms | Limits | Cache |
|---|---|---|---|---|
| Weather | [Open-Meteo](https://open-meteo.com/) Forecast API | Data under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/); attribution is mandatory | Free tier is for non-commercial use only: 600 calls/min, 5,000/hour, under 10,000/day, 300,000/month | 15 min |
| Berlin updates | [v6.vbb.transport.rest](https://v6.vbb.transport.rest/) (VBB timetable and real-time data) | Community-run, unofficial wrapper around the VBB HAFAS API; no SLA | 100 requests/min (burst 200), no key | 60 s per stop |
| Most recent news | [Hacker News API](https://github.com/HackerNews/API) (Firebase) | Public API by Y Combinator | No documented rate limit; 1 + up to 10 requests per refresh | 10 min |
| Tasks of the day | [Nylas Calendar API v3](https://developer.nylas.com/docs/reference/api/events/get-all-events/) | Your Nylas plan's terms; reads only your own grant's primary calendar | Per your Nylas plan; HTTP 429 when exceeded (the card then shows "Currently unavailable") | 60 s per grant |

- **Open-Meteo attribution:** every page carries "Weather data by Open-Meteo.com" (linked to
  open-meteo.com) and a link to the CC BY 4.0 licence in the footer. If you use the app
  commercially, you need an Open-Meteo API plan.
- **VBB is community-run:** `v6.vbb.transport.rest` is run by volunteers
  ([public-transport](https://github.com/public-transport)), not by VBB. It can be slow or
  down, and its data format can change. All access goes through
  `app/services/vbb.py:get_departures()`, so it can be replaced by VBB's official
  GTFS-Realtime feed later. The `delay` field is in seconds: the docs only show an example,
  and this was confirmed against live data (`delay` = `when` − `plannedWhen`).
- **Rate limits and caching:** the caches are per process and in memory. With several worker
  processes, multiply the request rates above by the number of workers.
- **Privacy:** logs contain counts and exception types only, never event titles, email
  content, calendar ids or coordinates.

## Current status

Last verified on 2026-11-16:

- **Tests:** `uv run pytest`: 120 passed, offline.
- **App:** `uv run morning-blick` against the live APIs:
  - `/health` returns `{"status":"ok","app":"Morning Blick"}`.
  - The first `GET /` took about 2.3 s, and a cached reload about 0.04 s.

| Card | Live result |
|---|---|
| Weather in Berlin | OK: current temperature and condition, today's min/max and rain chance |
| Berlin updates | OK: delays at S+U Alexanderplatz (e.g. "M5 → U Turmstr.: +3 min") |
| Most recent news | OK: 5 linked stories |
| Tasks of the day | Nylas answered; there were no events that day, so the card showed "No data yet" |
| Footer | Open-Meteo attribution and CC BY 4.0 link present |

## Known limitations and open items

- **Live event formatting not yet seen:** the "09:00 Title" and "All day · Title" lines
  are covered by tests only, because the calendar was empty during the live check.
- **Empty schedule text:** an empty calendar shows "No data yet" (the original wording);
  "No events today" would be clearer.
- **One unusual event can blank the schedule card:** the Nylas SDK decodes a whole page of
  events at once. An unknown `when` type makes the whole card "Currently unavailable"
  instead of skipping just that event.
- **Nylas rate limits:** the Nylas docs give no numbers for listing calendars and events.
  The app relies on the 60 s cache and treats HTTP 429 as "unavailable".
- **VBB service notices are not shown:** departures are requested with `remarks=false`.
  Only delays (at least `VBB_MIN_DELAY_MINUTES`) and cancellations appear.
- **No logging setup:** the app's info logs (e.g. how many events were fetched) are not
  shown when running uvicorn. Warnings are.
- **Slow providers keep running in the background:** a provider that misses
  `PROVIDER_TIMEOUT` is shown as unavailable. Its thread runs until its own HTTP timeout
  (`HTTP_TIMEOUT`) ends, because Python threads cannot be stopped.
- **Caches are per process:** with several workers, each keeps its own cache, and request
  rates to the APIs multiply accordingly.
- **Database layer is unfinished:** `app/database/` is meant to drop duplicate Nylas
  webhook deliveries (`mark_processed()`), but it is not used yet and cannot be imported
  as written: `crud.py` imports from `app.models` (empty) and `models.py` from `app.db`
  (does not exist; `Base` lives in `app/database/session.py`). `session.py` also needs
  `DATABASE_URL` set at import time, and there is no Postgres service in
  `docker-compose.yml` and no table creation or migrations yet.

## Tutorials used to finish this project

YouTube channel: [Dave Ebbelaar](https://www.youtube.com/@daveebbelaar)

Repositories:

- [workspace-template](https://github.com/daveebbelaar/demo-project/tree/main)
- [ai-cookbook](https://github.com/daveebbelaar/ai-cookbook)
