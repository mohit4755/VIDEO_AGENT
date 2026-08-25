---
title: Video Agent
emoji: 🎬
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# Video Agent — YouTube Video Summarizer

Paste a YouTube URL, get back a short summary, a detailed summary, key
points, keywords, and a transcript preview. Built on FastAPI + a plain
HTML/CSS/JS frontend, on top of the original `va` repo's transcription
and LangChain/Mistral summarization pipeline.

## Folder structure

```
video-agent/
├── core/
│   ├── __init__.py
│   ├── extractor.py       # key points, keywords (+ original action-item extractors)
│   ├── pipeline.py        # orchestrates the full analyze flow
│   ├── rag_engine.py      # optional "ask about this video" chat
│   ├── summarizer.py      # short + detailed summary, title
│   ├── transcriber.py     # Whisper / Sarvam fallback transcription
│   └── vector_store.py    # Chroma store backing rag_engine
├── utils/
│   ├── __init__.py
│   └── audio_processor.py # URL validation, captions fast-path, audio fallback
├── static/
│   ├── index.html
│   ├── style.css
│   └── script.js
├── downloads/              # temp audio files (fallback path)
├── vector_db/               # persisted Chroma index
├── .env.example
├── main.py                   # FastAPI app
├── requirements.txt
└── test.py                    # CLI entry point
```

## How it works

1. **Fast path (default, ~seconds):** `utils/audio_processor.py` pulls
   the video's existing captions via `youtube-transcript-api` — no
   download, no Whisper.
2. **Fallback path (only if no captions exist):** downloads audio with
   `yt-dlp`, chunks it, and transcribes with local Whisper (or Sarvam
   for Hinglish).
3. Either way, the transcript goes through `core/summarizer.py` (short
   + detailed summary) and `core/extractor.py` (key points, keywords).
4. The transcript is also indexed into Chroma so you can ask follow-up
   questions via the "Ask about this video" box (`POST /ask`).

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure your API key
cp .env.example .env
# then edit .env and set MISTRAL_API_KEY
```

You need an FFmpeg-capable system. The Docker image installs FFmpeg directly.

### Render and YouTube access

YouTube may block requests from Render's shared cloud IP addresses. If
analysis reports that YouTube blocked the cloud IP, add `YOUTUBE_PROXY` in
Render's environment variables using a working residential HTTP(S) proxy:

```text
YOUTUBE_PROXY=http://username:password@proxy-host:port
```

Do not commit proxy credentials to the repository. After adding the variable,
redeploy the service.

## Run

```bash
uvicorn main:app --reload
```

Then open **http://127.0.0.1:8000** — the FastAPI app serves the
frontend directly, so there's no separate frontend server to run.

## API reference

### `GET /health`
```json
{ "status": "ok" }
```

### `POST /analyze`
Request:
```json
{ "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "language": "english" }
```

Success response:
```json
{
  "status": "success",
  "video_id": "dQw4w9WgXcQ",
  "video_title": "Example Video Title",
  "source_used": "captions",
  "short_summary": "...",
  "detailed_summary": "...",
  "key_points": ["...", "..."],
  "keywords": ["...", "..."],
  "transcript_preview": "...",
  "error": null
}
```

Error response (still `200 OK` — check `status`):
```json
{
  "status": "error",
  "error": "That doesn't look like a valid YouTube URL.",
  "video_title": null,
  "short_summary": null,
  "detailed_summary": null,
  "key_points": [],
  "keywords": [],
  "transcript_preview": null
}
```

### `POST /ask` (optional, after analyzing a video)
Request: `{ "question": "What's the main takeaway?" }`
Response: `{ "video_id": "...", "question": "...", "answer": "..." }`

## Testing locally

- **Via the UI:** run the server, open the browser, paste a link.
- **Via curl:**
  ```bash
  curl -X POST http://127.0.0.1:8000/analyze \
    -H "Content-Type: application/json" \
    -d '{"url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","language":"english"}'
  ```
- **Via the CLI:** `python test.py`
- **Interactive API docs:** http://127.0.0.1:8000/docs (FastAPI's
  built-in Swagger UI — good for quick manual testing).

## Notes

- The first request that hits the Whisper fallback path will download
  the model weights (`small` by default, ~500MB) — expect a delay on
  first use.
- Very long videos (2h+) will be slow on the fallback path since audio
  gets processed in 10-minute chunks by local Whisper. The captions
  fast-path is unaffected by video length.
