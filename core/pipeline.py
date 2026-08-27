"""
core/pipeline.py

The core orchestration logic, refactored out of the original main.py's
run_pipeline() so it can be reused by both the FastAPI backend (main.py)
and the CLI (test.py).

Flow:
  1. Validate the YouTube URL.
  2. Try the FAST path: pull existing captions via youtube-transcript-api.
  3. If no captions exist, FALL BACK to the original pipeline:
     download audio -> chunk -> transcribe with Whisper.
  4. Summarize (short + detailed), extract key points and keywords.
"""

from dotenv import load_dotenv
import json
import os
import re

load_dotenv()

from utils.audio_processor import (
    is_valid_youtube_url,
    get_video_id,
    get_captions_transcript,
)
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

TRANSCRIPT_PREVIEW_CHARS = 1200


class VideoProcessingError(Exception):
    """Raised for any recoverable failure while analyzing a video."""


def analyze_video(url: str, language: str = "english") -> dict:
    url = (url or "").strip()
    if not url:
        raise VideoProcessingError("Please provide a YouTube URL.")

    if not is_valid_youtube_url(url):
        raise VideoProcessingError("That doesn't look like a valid YouTube URL.")

    video_id = get_video_id(url)

    # ── Step 1: try all available transcript sources ────────────────────
    transcript = get_captions_transcript(video_id)
    source_used = "captions"

    if not transcript or len(transcript.strip()) < 20:
        raise VideoProcessingError(
            "Could not retrieve usable captions for this video. "
            "The video may not have captions, or all transcript sources "
            "are currently unavailable. Please try again in a few minutes."
        )

    try:
        llm = ChatMistralAI(
            model="mistral-small-latest",
            mistral_api_key=os.getenv("MISTRAL_API_KEY"),
            temperature=0.2,
        )
        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "Analyze the transcript and return ONLY valid JSON with keys "
                    "short_summary, detailed_summary, key_points, and keywords. "
                    "key_points and keywords must be arrays of strings.",
                ),
                ("human", "{transcript}"),
            ]
        )
        sample = transcript[:12000]
        raw = (prompt | llm | StrOutputParser()).invoke({"transcript": sample})
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            raise ValueError("AI response was not valid JSON")
        analysis = json.loads(match.group(0))
        short_summary = str(analysis.get("short_summary", "")).strip()
        detailed_summary = str(analysis.get("detailed_summary", "")).strip()
        key_points = [str(item) for item in analysis.get("key_points", [])]
        keywords = [str(item) for item in analysis.get("keywords", [])]
    except Exception as e:
        raise VideoProcessingError(f"AI analysis failed: {e}") from e

    return {
        "status": "success",
        "video_id": video_id,
        "video_title": f"YouTube video {video_id}",
        "source_used": "captions",
        "short_summary": short_summary.strip(),
        "detailed_summary": detailed_summary.strip(),
        "key_points": key_points,
        "keywords": keywords,
        "transcript_preview": transcript[:TRANSCRIPT_PREVIEW_CHARS].strip()
        + ("..." if len(transcript) > TRANSCRIPT_PREVIEW_CHARS else ""),
        "transcript_full": transcript,
        "error": None,
    }
