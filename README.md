# Uncensored LLM Book + Audio Factory ✨

Create full-length books (Markdown + PDF + audio) on any topic using an uncensored model that runs privately in a sandbox container and cannot access your files or computer in any way.

This is an AI‑first native app. Most applications are shoehorning AI into them; this app wouldn’t be possible without it.

**Tech stack:** FastAPI + Jinja2 + HTMX, SQLite (aiosqlite), Ollama, Coqui TTS, ffmpeg, WeasyPrint/xhtml2pdf, Docker Compose.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Docker (app + Ollama)

Run both the web UI and a local Ollama instance via Docker Compose:

```bash
docker-compose up --build
```

Open `http://localhost:8600` (or `http://<host-ip>:8600` from another machine).

Notes:
- Ollama is reachable to the app at `http://ollama:11434` inside the compose network.
- Models persist in the `ollama` volume.
- App data persists in `./data`.
- The app will auto-pull the configured model on startup if missing.

## What you get

- ✅ One‑page UI with Create, Queue, and Library sections.
- ✅ Markdown + PDF + Text + MP3 + M4B assets per book.
- ✅ Friendly queue controls (stop, cancel, retry, reorder).
- ✅ Rendered reader with clean typography.

## How it works

- Jobs are persisted to SQLite at `data/app.db`.
- Generated book output is written under `data/jobs/<job_id>/book.md` with a plain-text companion `book.txt` for audio.
- The UI is a single page at `/` with Create, Queue, and Library sections.
- Running jobs show an ETA based on current progress.
- Job controls: stop (`POST /jobs/{id}/stop`), cancel (`POST /jobs/{id}/cancel`), resume (`POST /jobs/{id}/resume`).
- Retry failed jobs: `POST /jobs/{id}/retry`.
- Delete jobs: `POST /jobs/{id}/delete` (not allowed for running jobs).
- Queue ordering: use Up/Down controls in the Queue section for queued jobs.
- Recommended topics use the Ollama model and recent job topics to suggest new ideas.
- PDF export: `GET /jobs/{id}/download.pdf` (uses `weasyprint` with `xhtml2pdf` fallback).
- Rendered reader: `GET /jobs/{id}/read` (opens formatted HTML in a new tab).
- Read aloud: `POST /jobs/{id}/tts` (local Coqui TTS; uses the plain-text file; requires `ffmpeg`).
- Audiobook download: `GET /jobs/{id}/audiobook?format=mp3|m4b` (served from queued audio jobs; m4b needs `ffmpeg`).
- Text download: `GET /jobs/{id}/download.txt`.

Audio queue behavior:
- When a book job is created, text, PDF, MP3, and M4B jobs are queued immediately (in that order).
- Audio jobs read the generated text and will wait behind the book job in the queue.

## Environment overrides

To override per session without editing `.env`:

```bash
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_MODEL="huihui_ai/llama3.2-abliterate:3b"
export OLLAMA_AUTO_PULL=false
export LOCAL_TTS_MODEL="tts_models/en/vctk/vits"
export LOCAL_TTS_DEFAULT_VOICE="p225"
```

Local TTS notes:
- Coqui will download the model on first use.
- Voices are model-specific speaker IDs (e.g., `p225`).
- `ffmpeg` is required for MP3/M4B output.


## Linting and formatting (Ruff)

```bash
python -m ruff check .
python -m ruff format .
```

## Linting and formatting (Pylint + Black)

```bash
python -m black .
python -m pylint app tests
```

## Tests

```bash
pytest
```


## Start/stop/restart script

```bash
./scripts/server.sh start
./scripts/server.sh stop
./scripts/server.sh restart
```

Logs are written to `.run/uvicorn.log`.

## Security and repo hygiene

- `data/` and `.env` are ignored via `.gitignore` and should never be committed.
- Keep real secrets only in `.env`; commit changes to `.env.example` instead.
