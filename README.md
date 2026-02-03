# Book Generator (Ollama)

Generates a college-level book (Markdown) from a topic using an Ollama model.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

## Notes

- Jobs are persisted to SQLite at `data/app.db`.
- Generated book output is written under `data/jobs/<job_id>/book.md`.
- The Library page lists completed books at `/library`.
- Running jobs show an ETA based on current progress.
- Job controls: stop (`POST /jobs/{id}/stop`), cancel (`POST /jobs/{id}/cancel`), resume (`POST /jobs/{id}/resume`).
- Retry failed jobs: `POST /jobs/{id}/retry`.

## Venv + Ollama SSH testing

- Activate the venv before running the app:
	```bash
	source .venv/bin/activate
	```
- The Ollama host is reachable at `192.168.1.248`. For password-less SSH testing:
	```bash
	ssh 192.168.1.248
	```
- If you need to override the Ollama host or model per session:

### Optional overrides

- To override per session without editing `.env`:
	```bash
	export OLLAMA_BASE_URL="http://192.168.1.248:11434"
	export OLLAMA_MODEL="llama3.2:1b"
	```

## Start/stop/restart script

```bash
./scripts/server.sh start
./scripts/server.sh stop
./scripts/server.sh restart
```

Logs are written to `.run/uvicorn.log`.
