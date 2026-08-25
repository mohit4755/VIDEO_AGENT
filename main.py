"""
main.py

FastAPI backend for Video Agent — YouTube video summarizer.

Endpoints:
  GET  /            -> serves the frontend (static/index.html)
  GET  /health       -> health check
  POST /analyze       -> main analysis endpoint
  POST /ask            -> optional RAG chat over the last-analyzed transcript

Run with:
  uvicorn main:app --reload
"""

import os

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from core.pipeline import analyze_transcript, analyze_video, VideoProcessingError

app = FastAPI(title="Video Agent API", version="1.0.0")

# Allow the static frontend (and local dev tools) to call the API freely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory cache so /ask can reuse the RAG chain built during /analyze
# without re-embedding the transcript on every question. Fine for a
# single-user demo; swap for a proper session store in production.
_last_rag_chain = None
_last_video_id = None


# ── Request / response models ────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    url: str = Field(..., description="YouTube video URL")
    language: str = Field("english", description="'english' or 'hinglish'")


class AskRequest(BaseModel):
    question: str


# ── Routes ────────────────────────────────────────────────────────────────

@app.get("/")
def serve_frontend():
    return FileResponse("static/index.html")


@app.head("/")
def probe_frontend():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"status": "ok"}


def build_rag_in_background(transcript: str, video_id: str) -> None:
    global _last_rag_chain, _last_video_id
    try:
        from core.rag_engine import build_rag_chain

        _last_rag_chain = build_rag_chain(transcript)
        _last_video_id = video_id
    except Exception as e:
        print(f"RAG chain build failed (chat will be unavailable): {e}")


@app.post("/analyze")
def analyze(payload: AnalyzeRequest, background_tasks: BackgroundTasks):
    global _last_rag_chain, _last_video_id

    try:
        result = analyze_video(payload.url, language=payload.language)
    except VideoProcessingError as e:
        # Expected, user-facing errors -> clean structured response, not a 500
        return {
            "status": "error",
            "error": str(e),
            "video_title": None,
            "short_summary": None,
            "detailed_summary": None,
            "key_points": [],
            "keywords": [],
            "transcript_preview": None,
        }
    except Exception as e:
        # Unexpected failure -> still respond gracefully
        raise HTTPException(status_code=500, detail=f"Unexpected server error: {e}")

    # RAG can exceed the free instance memory limit. Enable it explicitly
    # when a larger instance or a compatible embedding backend is available.
    _last_rag_chain = None
    if os.getenv("ENABLE_RAG", "false").lower() == "true":
        background_tasks.add_task(
            build_rag_in_background,
            result["transcript_full"],
            result["video_id"],
        )

    # Don't ship the full transcript back over the wire by default.
    response = {k: v for k, v in result.items() if k != "transcript_full"}
    return response


@app.post("/analyze-upload")
async def analyze_upload(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
):
    global _last_rag_chain

    allowed_extensions = (".txt", ".srt", ".vtt")
    filename = file.filename or "transcript.txt"
    if not filename.lower().endswith(allowed_extensions):
        return {"status": "error", "error": "Upload a .txt, .srt, or .vtt transcript file."}

    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        return {"status": "error", "error": "Transcript files must be 5 MB or smaller."}

    text = content.decode("utf-8-sig", errors="replace")
    if filename.lower().endswith((".srt", ".vtt")):
        import re

        text = re.sub(r"^WEBVTT.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\s*\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(
            r"^\s*\d{2}:\d{2}(?::\d{2})?[,.]\d{3}\s+-->.*$",
            "",
            text,
            flags=re.MULTILINE,
        )

    try:
        result = analyze_transcript(
            text,
            video_title=filename,
        )
    except VideoProcessingError as e:
        return {"status": "error", "error": str(e)}

    _last_rag_chain = None
    if os.getenv("ENABLE_RAG", "false").lower() == "true":
        background_tasks.add_task(
            build_rag_in_background,
            result["transcript_full"],
            result["video_id"],
        )

    return {k: v for k, v in result.items() if k != "transcript_full"}


@app.post("/ask")
def ask(payload: AskRequest):
    if _last_rag_chain is None:
        raise HTTPException(
            status_code=400,
            detail="Analyze a video first before asking questions about it.",
        )
    try:
        from core.rag_engine import ask_question

        answer = ask_question(_last_rag_chain, payload.question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not answer: {e}")

    return {"video_id": _last_video_id, "question": payload.question, "answer": answer}


# Mount static assets (CSS/JS) after routes so "/" above takes priority.
app.mount("/static", StaticFiles(directory="static"), name="static")
