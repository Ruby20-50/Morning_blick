# Morning Blick

A FastAPI application, packaged as the `app` Python package.

## Project structure

```
morning_blick/
├── app/                    # the application package
│   ├── __init__.py
│   ├── main.py             # FastAPI app (create_app) + `main()` entry point
│   ├── api/routes.py       # HTTP endpoints
│   ├── config/settings.py  # settings loaded from env / .env
│   ├── schemas/            # pydantic request/response models
│   ├── services/           # business logic (e.g. calculator)
│   └── notebooks/          # exploration notebooks (not used by the running app)
├── tests/                  # pytest tests
├── docker-compose.yml
├── .env.example            # copy to .env and fill in
└── pyproject.toml
```

## Run

```bash
uv sync                          # install app + dev dependencies
uv run morning-blick             # start the server on http://127.0.0.1:8000
# or: uv run uvicorn app.main:app --reload
uv run pytest                    # run tests
```

API docs: http://127.0.0.1:8000/docs

### Endpoints
- `GET /health`
- `POST /calculate/{add|subtract|multiply|divide}` with body `{"a": 10, "b": 5}`

### Tutorials used to finish this project
Youtube channel: [Dave Ebbelaar](https://www.youtube.com/@daveebbelaar)

Repositories: 

 [workspace-template](https://github.com/daveebbelaar/demo-project/tree/main)

[ai-cookbook](https://github.com/daveebbelaar/ai-cookbook)

### Nylas webhook setup (message.created)
Incoming `POST /events` calls are accepted only with a valid `x-nylas-signature`
(HMAC-SHA256 of the raw body, keyed with `NYLAS_WEBHOOK_SECRET`). Setup order:

1. Start the app: `uv run uvicorn app.main:app --reload`
2. Start the tunnel with [docs/cloudflared-config.example.yml](docs/cloudflared-config.example.yml)
   (copied and filled in); set `SERVER_URL=https://<tunnel-hostname>` in `.env`.
3. Create the webhook: `uv run python -m app.scripts.create_webhook`
   (Nylas sends a challenge to `/events` during creation, so steps 1–2 must be running).
4. Copy the printed secret into `.env` as `NYLAS_WEBHOOK_SECRET` (never commit it).
5. Restart the app so the new secret is loaded.
