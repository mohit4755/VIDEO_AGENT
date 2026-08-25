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
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

from core.pipeline import analyze_video, VideoProcessingError

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
_analysis_jobs = {}


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


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


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


def run_analysis_job(job_id: str, payload: AnalyzeRequest) -> None:
    global _last_rag_chain, _last_video_id

    _analysis_jobs[job_id] = {"status": "processing"}
    try:
        result = analyze_video(payload.url, language=payload.language)
    except VideoProcessingError as e:
        _analysis_jobs[job_id] = {
            "status": "error",
            "error": str(e),
        }
        return
    except Exception as e:
        _analysis_jobs[job_id] = {
            "status": "error",
            "error": f"Unexpected server error: {e}",
        }
        return

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
    _analysis_jobs[job_id] = response


@app.post("/analyze", status_code=202)
def analyze(payload: AnalyzeRequest, background_tasks: BackgroundTasks):
    job_id = uuid.uuid4().hex
    _analysis_jobs[job_id] = {"status": "queued"}
    background_tasks.add_task(run_analysis_job, job_id, payload)
    return {"status": "processing", "job_id": job_id}


@app.get("/analyze/{job_id}")
def analysis_status(job_id: str):
    job = _analysis_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return job


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
