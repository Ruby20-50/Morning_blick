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

Repositories: [workspace-template](https://github.com/daveebbelaar/demo-project/tree/main)
