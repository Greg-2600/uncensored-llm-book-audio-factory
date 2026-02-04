# Feature Implementation TODOs

This document lists implementation TODOs for each requested feature. Each list includes tests and documentation updates.

---

## 1) Auto-update queue percent complete

**Goal:** Live, accurate queue-wide progress shown in the UI.

**Implementation TODOs**
- Add a queue-level progress endpoint (e.g., `GET /queue/status`) that returns total jobs, completed jobs, in-progress job, and aggregate percent.
- Compute percent from DB job statuses: `completed` jobs + partial progress from `running` job(s).
- Update UI (queue page + home) to poll via HTMX every 2–5 seconds and display percent complete with a progress bar.
- Add a lightweight cache or debounce to avoid excessive DB reads.

**Tests**
- Unit tests for queue aggregation logic with mixed job states.
- API test for `GET /queue/status` response shape and values.
- UI smoke test (or snapshot) confirming percent updates in DOM.

**Docs**
- Update README with new endpoint and UI behavior.
- Add a short “Queue Progress” section to the UI docs.

---

## 2) Show remaining time left for a running book

**Goal:** ETA per running job displayed in job detail.

**Implementation TODOs**
- Track per-chapter start times and elapsed time in DB (new table or fields).
- Estimate remaining time from average chapter duration and remaining chapters.
- Expose ETA in job status partial response.
- Show ETA in job detail UI; update in polling partial.

**Tests**
- Unit tests for ETA computation (edge cases: 0 chapters, first chapter, long tail).
- API test for job status response includes ETA fields.

**Docs**
- Document ETA calculation and assumptions.

---

## 3) Show total queue time left until completion

**Goal:** Queue-wide ETA based on job ordering and historical durations.

**Implementation TODOs**
- Compute projected time left by summing ETA for running job + historical average times for queued jobs.
- Store moving average duration per chapter/topic/model to improve estimate.
- Add endpoint data to queue status response.
- Display total queue ETA on queue page and home.

**Tests**
- Unit tests for queue ETA calculation with multiple queued jobs.
- API test for queue ETA fields.

**Docs**
- Document queue ETA logic.

---

## 4) Stop / cancel / resume a job in the queue

**Goal:** User can stop a running job, cancel a queued job, or resume a stopped job.

**Implementation TODOs**
- Add job control endpoints: `POST /jobs/{id}/cancel`, `POST /jobs/{id}/stop`, `POST /jobs/{id}/resume`.
- Extend job statuses (e.g., `stopped`, `cancelled`, `paused`) and update DB schema/migrations.
- Implement stop/cancel in runner: cooperative cancellation with checkpointing.
- Persist chapter progress so resume can continue at last checkpoint.
- Add UI buttons with confirmations and disabled states.

**Tests**
- Unit tests for state transitions and validation rules.
- Integration tests for stop/resume behavior in runner.
- UI tests for control buttons state and error handling.

**Docs**
- Document new job states and control endpoints.

---

## 5) Download the book

**Goal:** Download completed book as Markdown from UI.

**Implementation TODOs**
- Confirm existing `GET /jobs/{id}/download` endpoint is wired in UI (if not, add).
- Ensure content-disposition filename is safe and correct.
- Add error handling if file missing.

**Tests**
- API test: completed job returns file with correct content-type and headers.

**Docs**
- Document download behavior and path.

---

## 6) Export to PDF (rendered Markdown) and download

**Goal:** Convert the book to PDF and provide download.

**Implementation TODOs**
- Add Markdown-to-PDF renderer (e.g., `markdown` + `weasyprint` or `pandoc`).
- Add `GET /jobs/{id}/download.pdf` or `POST /jobs/{id}/export/pdf`.
- Cache generated PDF in job output folder to avoid regenerating.
- Update UI with “Download PDF” button.

**Tests**
- Integration test: export endpoint returns PDF with non-zero size.
- Regression test: repeated export uses cached file.

**Docs**
- Add PDF export instructions and dependencies.

---

## 7) Adjust queue order from the UI

**Goal:** Reorder queued jobs via drag-and-drop or controls.

**Implementation TODOs**
- Add `queue_position` column to jobs and update DB ordering logic.
- Build UI controls (drag/drop or up/down buttons) to reorder queued jobs.
- Add endpoint to update job order.
- Ensure running job remains pinned at top, queued jobs re-ordered underneath.

**Tests**
- Unit tests for reorder validation (only queued jobs, no duplicates).
- API tests for reorder endpoint.
- UI test for reorder interaction.

**Docs**
- Document queue ordering rules.

---

## 8) Make the UI look cooler

**Goal:** More polished UI theme and layout.

**Implementation TODOs**
- Create a unified design system (colors, typography, spacing).
- Add a hero section, progress cards, and improved job list styling.
- Add status badges, icons, and refined loading states.
- Ensure responsive layout for mobile.

**Tests**
- Basic visual regression snapshots for key pages.

**Docs**
- Update screenshots in README (if used).

---

## 9) Model selection dropdown on topic entry

**Goal:** Allow selecting model per job.

**Implementation TODOs**
- Add model list to settings (static list or fetched from Ollama `/api/tags`).
- Extend job schema to store selected model.
- Update job creation form to include dropdown.
- Pass model through to `run_job` and generator calls.

**Tests**
- Unit test: job creation stores model correctly.
- API test: model is respected during job run.

**Docs**
- Document model selection behavior and defaults.

---

## 10) Read a rendered book in the UI

**Goal:** In-app rendered view of the Markdown book.

**Implementation TODOs**
- Add route `/jobs/{id}/read` to render Markdown to HTML.
- Use a Markdown renderer (e.g., `markdown` + safe HTML).
- Add navigation and “back to job” link.

**Tests**
- API test for render route returns HTML.
- UI test for rendered content display.

**Docs**
- Document the reader view.

---

## 11) Text-to-speech playback with voice controls (using OpenAI Whisper)

**Goal:** Read the book aloud with selectable voice and speed.

**Implementation TODOs**
- Clarify pipeline: Whisper is speech-to-text; for TTS use OpenAI TTS (or another TTS provider). If Whisper must be used, define conversion workflow and constraints.
- Add a TTS service layer with configurable voice, speed, and format.
- Generate audio per chapter and cache in job output folder.
- Add UI controls (play/pause/seek/voice/speed) in reader view.
- Add endpoint(s) to request audio generation and stream audio.

**Tests**
- Integration tests for audio generation endpoint.
- UI test for playback controls.

**Docs**
- Document required API keys, costs, and configuration.

---

## 12) Recommended topics based on prior generations

**Goal:** Suggest new topics based on history.

**Implementation TODOs**
- Store historical topics and basic metadata (success, timestamp).
- Generate recommendations via Ollama using recent job topics as input.
- Add recommendations to home page (click-to-fill).

**Tests**
- Unit tests for recommendation logic.
- UI test for recommendation list display.
- Integration test for Ollama recommendation response handling.

**Docs**
- Document how recommendations are generated (Ollama + recent topics).
