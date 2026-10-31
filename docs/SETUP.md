# Setup and running

## Requirements

- Python 3.11 or newer (developed and tested on 3.12 and 3.13)
- Git
- Optional: Docker, to run the service in a container
- Optional: an Anthropic API key, for live LLM mode

## Install

Windows (Command Prompt):

```cmd
git clone https://github.com/vasanthbitu468/url-shortener-agentic-sdlc.git
cd url-shortener-agentic-sdlc
py -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

macOS / Linux:

```bash
git clone https://github.com/vasanthbitu468/url-shortener-agentic-sdlc.git
cd url-shortener-agentic-sdlc
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Check the install:

```cmd
pytest --cov
```

Expect 106 passed and coverage above 85%.

## Run the service

```cmd
uvicorn service.main:app --reload
```

Open http://localhost:8000/docs. Try `POST /api/v1/urls` with
`{"url": "https://www.example.com", "custom_alias": "demo"}`, then open
http://localhost:8000/demo.

With Docker:

```cmd
docker compose up --build
```

Configuration is through environment variables prefixed `APP_` or a `.env` file. Copy
`.env.example` to `.env` to start.

| Variable | Default | Meaning |
| --- | --- | --- |
| `APP_DATABASE_URL` | `sqlite:///./shortener.db` | SQLAlchemy URL |
| `APP_BASE_URL` | `http://localhost:8000` | Used to build short URLs |
| `APP_RATE_LIMIT_REQUESTS` / `APP_RATE_LIMIT_WINDOW_SECONDS` | `30` / `60` | Create-endpoint rate limit per client IP |

## Run the orchestrator

### All scenarios, unattended

```cmd
python scripts/run_scenario.py --all
```

Plays each scenario's scripted human steps and prints the stage table and metrics.

### One scenario, with you as the reviewer

```cmd
sdlc run scenarios/greenfield-bulk-create --run-id gf1
```

The run pauses at each approval checkpoint and prints the next commands. Review
`runs\gf1\artifacts\`, then:

```cmd
sdlc approve gf1 design -m "contract looks right" --by "Your Name"
sdlc approve gf1 release -m "ship it" --by "Your Name"
```

Try the other controls:

| Command | Effect |
| --- | --- |
| `sdlc reject gf1 design -m "what to change"` | Send a stage back with your feedback |
| `sdlc edit gf1 spec my_spec.json -m "why"` | Replace an artifact; stages that used it re-plan |
| `sdlc stop gf1` | Safe-stop: in-flight stages finish, state is saved |
| `sdlc resume gf1` | Continue a stopped or paused run |
| `sdlc status gf1` | Stage table |
| `sdlc trace gf1` | Decision lineage |
| `sdlc verify gf1` | Check the audit log hash chain |
| `sdlc metrics` | Reliability metrics across all runs |
| `sdlc graph` | Print the pipeline |
| `sdlc list` | All runs |

### Apply a run's result to the code

The orchestrator never changes the repository; a human applies its patch:

```cmd
git checkout -b feat/bulk-create
git apply runs\gf1\changes.patch
pytest
git add . && git commit -m "feat: bulk create (from orchestrator run gf1)"
```

Use `runs\gf1\pr_description.md` as the pull-request text.

### Live LLM mode

```cmd
pip install -e ".[live]"
set ANTHROPIC_API_KEY=your-key
sdlc run scenarios/greenfield-bulk-create --llm live
```

`ANTHROPIC_MODEL` overrides the model. The same gates, policies and approvals apply to live
output.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `'python' is not recognized` (Windows) | Use `py` to create the venv; inside the activated venv, `python` works |
| `sdlc` not found | Activate the venv and run `pip install -e ".[dev]"` again |
| `run ... already exists` | Use a new `--run-id`, or delete `runs\<id>` |
| A scenario run fails | The script prints each failed stage's error; full detail is in `runs\<id>\events.jsonl` |
| Odd characters in uvicorn logs (Windows) | Colour codes in old consoles; add `--no-use-colors` |
