# 📚 Uncensored LLM Book + Audio Factory

> **Generate complete books in minutes.** Choose a topic. Get Markdown, PDF, MP3, and M4B audiobooks—all generated privately with an uncensored LLM running in a sandbox.

This is an **AI-first native application**. Unlike traditional apps that bolt AI features onto existing frameworks, this entire platform is built around what AI makes possible. Without AI, this wouldn't exist.

---

## ✨ What You Get

| Feature | Details |
|---------|---------|
| 📖 **Full Book Generation** | Markdown + PDF + plain text, all auto-generated |
| 🎵 **Audiobooks** | MP3 and M4B formats with local TTS |
| 🎯 **Smart Queue** | Expand/collapse books to see subtasks; reorder freely |
| ⚡ **Job Controls** | Stop, cancel, resume, retry with one click |
| 🎨 **Reader View** | Beautifully rendered Markdown in your browser |
| 💡 **Smart Suggestions** | Get topic recommendations based on your history |
| 🔒 **Fully Private** | Runs locally; your model never leaves your machine |
| 🐳 **Docker Ready** | One command to run everything |

---

## 🚀 Quick Start

### Local Development (5 minutes)

```bash
# Clone and setup
git clone https://github.com/Greg-2600/uncensored-llm-book-audio-factory.git
cd Book_Generator

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
cp .env.example .env

# Start the app
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000** in your browser.

### Docker (Recommended)

```bash
# Clone the repository
git clone https://github.com/Greg-2600/uncensored-llm-book-audio-factory.git
cd uncensored-llm-book-audio-factory

# Run setup script (ensures proper permissions)
chmod +x setup.sh
./setup.sh

# One command does everything
docker-compose up -d --build

# App is ready at http://localhost:8600
```

The container includes:
- 🐍 FastAPI web server
- 🦙 Ollama with local LLM
- 📦 All dependencies (ffmpeg, TTS, PDF tools)
- 📁 Persistent data volumes

---

## 🏗️ Architecture

**Tech Stack:**
- **Backend:** FastAPI + Jinja2 + HTMX
- **Database:** SQLite with async support (aiosqlite)
- **LLM:** Ollama (100% local, fully private)
- **Audio:** Coqui TTS + ffmpeg
- **Export:** WeasyPrint + xhtml2pdf for PDFs
- **Orchestration:** Docker Compose

---

## 📖 Features in Detail

### Create Books
Simply enter a topic. The app generates:
- ✅ Structured Markdown with headers, sections, and formatting
- ✅ Rendered PDF for print and sharing
- ✅ Plain text for audio generation
- ✅ Full MP3 and M4B audiobooks (optionally)

### Intelligent Queue Management
- **Hierarchical display:** Books appear as expandable sections
- **Click to expand:** See all constituent subtasks (PDF, MP3, M4B)
- **Drag-free reordering:** Up/Down buttons move books; subtasks stay together
- **Live ETA:** See how long until your book is done
- **Job controls:** Stop, cancel, pause, or resume at any time

### Read & Listen
- **In-app reader:** Beautifully formatted, distraction-free reading
- **Local playback:** Listen with adjustable voices and speeds
- **Multiple formats:** MP3 for mobile, M4B for audiobook apps

### Private & Secure
- Model runs in a sandbox container
- Cannot access your files or internet
- All processing happens locally
- No data sent anywhere

---

## 🎯 How It Works

### Book Generation Flow
1. **Create:** Enter topic → app queues generation job
2. **Generate:** LLM creates full book in Markdown
3. **Export:** Simultaneously queue PDF, MP3, M4B jobs
4. **Assemble:** Return finished assets (Markdown, PDF, audio files)

### Queue Organization
Books are the primary unit. When you create a book, four jobs are automatically queued:
```
[Book] "Advanced Physics" ← Your main job (can reorder)
  ├─ PDF Export
  ├─ MP3 Audiobook
  └─ M4B Audiobook
```

Only the book can be reordered. Subtasks inherit dependencies and always follow.

### Storage
- **Database:** `data/app.db` (SQLite with job metadata)
- **Generated books:** `data/jobs/{job_id}/book.md`
- **Assets:** Plain text, PDF, MP3, M4B all organized per job
- **Persistence:** Everything persists across restarts

---

## ⚙️ Configuration

### Environment Variables
Create a `.env` file and optionally a `.secrets` file for private credentials.

```bash
# Model configuration
export OLLAMA_BASE_URL="http://127.0.0.1:11434"
export OLLAMA_API_KEY=""
export OLLAMA_MODEL="huihui_ai/llama3.2-abliterate:3b"
export OLLAMA_AUTO_PULL=true

# TTS configuration
export TTS_PROVIDER="auto"       # auto, local, or openai
export LOCAL_TTS_MODEL="tts_models/en/vctk/vits"
export LOCAL_TTS_DEFAULT_VOICE="p225"
export OPENAI_TTS_MODEL="gpt-4o-mini-tts"
export OPENAI_TTS_DEFAULT_VOICE="alloy"

# API timeouts
export REQUEST_TIMEOUT_SECONDS="120"

# TTS provider notes
# - auto: use OpenAI TTS when OPENAI_API_KEY is configured, otherwise local Coqui TTS
# - local: always use local Coqui TTS
# - openai: always use OpenAI TTS (requires OPENAI_API_KEY)
```

If `OLLAMA_API_KEY` is set and `OLLAMA_BASE_URL` is left at the default local address, the app will automatically switch to Ollama Cloud.

### Switching Models
Change `OLLAMA_MODEL` in `.env` or set via environment. The app auto-pulls on startup if missing.

### TTS Voices
Coqui TTS downloads on first use. Speaker IDs vary by model:
- `p225`, `p229`, `p230` for VCTK model
- Try different voices to find your favorite

If `TTS_PROVIDER` is set to `openai`, the app will use OpenAI speech synthesis with `OPENAI_TTS_MODEL` and `OPENAI_TTS_DEFAULT_VOICE`.

---

## 🛠️ Development

### Run Tests
```bash
# All tests with coverage
pytest

# Specific test file
pytest tests/test_queue_expansion.py -v

# Run with output
pytest -s
```

**Test Coverage:**
- 22 comprehensive tests covering queue, jobs, export, TTS
- Tests for the new expandable queue feature
- Integration tests with the FastAPI test client

### Code Quality
```bash
# Format code (Ruff)
python -m ruff format .
python -m ruff check .

# Or use Black + Pylint
python -m black .
python -m pylint app tests
```

### Server Management
```bash
./scripts/server.sh start     # Start uvicorn in background
./scripts/server.sh stop      # Stop the server
./scripts/server.sh restart   # Restart the server
```

Logs are written to `.run/uvicorn.log`.

---

## 📁 Project Structure
```
.
├── app/
│   ├── main.py              # FastAPI app, endpoints
│   ├── db.py                # SQLite operations, queries
│   ├── generator.py         # Book generation logic
│   ├── local_tts.py         # Audio synthesis
│   ├── ollama_client.py     # LLM integration
│   ├── pdf_export.py        # PDF rendering
│   ├── eta.py               # ETA calculations
│   └── templates/           # Jinja2 HTML templates
│       ├── index.html       # Main page (Create/Queue/Library)
│       ├── job_detail.html  # Individual job view
│       └── partials/        # HTMX fragments
├── tests/                   # Pytest test suite
│   ├── test_queue_expansion.py
│   ├── test_job_controls.py
│   └── ...
├── docker-compose.yml       # Ollama + app services
├── Dockerfile               # App container
├── requirements.txt         # Dependencies
└── dev-requirements.txt     # Dev tools (pytest, ruff, etc.)
```

---

## 🔒 Security & Privacy

- **Fully sandboxed:** LLM runs in Docker; cannot access host files
- **No cloud calls:** Everything is local and private
- **Data protection:** `.env`, `.secrets`, and `data/` ignored in git
- **Secrets hygiene:** Never commit real credential files
- **Open source:** Full transparency; audit the code

---

## 📝 API Endpoints (Reference)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/` | GET | Main UI (Create, Queue, Library) |
| `/jobs` | POST | Create new book job |
| `/jobs/{id}` | GET | View job details |
| `/jobs/{id}/read` | GET | Render book in browser |
| `/jobs/{id}/download.pdf` | GET | Download as PDF |
| `/jobs/{id}/download.txt` | GET | Download as text |
| `/jobs/{id}/audiobook` | GET | Stream MP3/M4B audio |
| `/jobs/{id}/move` | POST | Reorder in queue |
| `/jobs/{id}/stop` | POST | Pause running job |
| `/jobs/{id}/cancel` | POST | Cancel job |
| `/jobs/{id}/resume` | POST | Resume paused job |
| `/jobs/{id}/retry` | POST | Retry failed job |

---

## 🎓 Tips & Tricks

- **Complex topics:** Break into multiple smaller topics for faster generation
- **Audiobook quality:** Choose VCTK speaker voices for better results
- **PDF formatting:** Markdown headings automatically become PDF sections
- **Batch creation:** Queue multiple topics; they'll process sequentially
- **Custom voices:** Swap TTS model for different language support

---

## 🐛 Troubleshooting

**Model won't download?**
- Check `OLLAMA_BASE_URL` points to your Ollama instance
- Verify Ollama is running: `curl http://localhost:11434/api/tags`
- Set `OLLAMA_AUTO_PULL=true` to auto-download on startup

**Audio generation slow?**
- TTS downloads the model on first run (100MB+)
- Subsequent generations are instant
- Use smaller models if you have limited resources

**PDF export failing?**
- Ensure `weasyprint` dependencies are installed
- Check `ffmpeg` is available: `ffmpeg -version`
- Try xhtml2pdf fallback (built-in)

**Docker volume issues?**
- Ensure `data/` directory exists and is writable
- Check Docker has permission to mount volumes
- Try `docker system prune` to clean up

---

## 📜 License

Check LICENSE file. Built with ❤️ for the open-source community.

---

## 🌟 Contributing

Pull requests welcome! Please:
1. Fork the repo
2. Create a feature branch
3. Add tests for new functionality
4. Submit PR with clear description

---

**Made with 🤖 AI + 💻 code**
