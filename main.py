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

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from core.pipeline import analyze_video, VideoProcessingError

load_dotenv()

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


@app.post("/analyze")
def analyze(payload: AnalyzeRequest):
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

    # Build the RAG chain in the background-ish (synchronously, kept simple)
    # so the optional /ask endpoint works right after analysis.
    try:
        from core.rag_engine import build_rag_chain

        _last_rag_chain = build_rag_chain(result["transcript_full"])
        _last_video_id = result["video_id"]
    except Exception as e:
        # Don't fail the whole analysis if RAG indexing has an issue —
        # the summary is still useful without chat.
        print(f"RAG chain build failed (chat will be unavailable): {e}")
        _last_rag_chain = None

    # Don't ship the full transcript back over the wire by default.
    response = {k: v for k, v in result.items() if k != "transcript_full"}
    return response


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
