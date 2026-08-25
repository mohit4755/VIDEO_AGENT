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
import os

from utils.audio_processor import (
    is_valid_youtube_url,
    get_video_id,
    get_captions_transcript,
    process_input,
    cleanup_chunks,
)
from core.summarizer import summarize_short, summarize_detailed, generate_title
from core.extractor import extract_key_points, extract_keywords

load_dotenv()

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

    # ── Step 1: try the fast captions path first ────────────────────────
    try:
        transcript = get_captions_transcript(video_id)
    except RuntimeError as e:
        raise VideoProcessingError(str(e)) from e
    source_used = "captions"

    # ── Step 2: fall back to download + Whisper if no captions exist ────
    if not transcript:
        if not os.getenv("YOUTUBE_PROXY"):
            raise VideoProcessingError(
                "YouTube is blocking requests from Render. Configure a working "
                "YOUTUBE_PROXY in Render, then try again."
            )
        source_used = "audio_transcription"
        chunks = []
        try:
            # Whisper/Torch is only needed when captions are unavailable.
            from core.transcriber import transcribe_all

            chunks = process_input(url)
            transcript = transcribe_all(chunks, language=language)
        except Exception as e:
            raise VideoProcessingError(
                f"Could not process this video's audio: {e}"
            )
        finally:
            cleanup_chunks(chunks)

    if not transcript or len(transcript.strip()) < 20:
        raise VideoProcessingError(
            "This video doesn't have usable captions or speech content to summarize."
        )

    # Title metadata requires a separate yt-dlp request and is often
    # rate-limited on hosted services, so keep analysis independent of it.
    video_title = f"YouTube video {video_id}"

    # ── Step 3: summarize + extract structured info ─────────────────────
    try:
        short_summary = summarize_short(transcript)
        detailed_summary = summarize_detailed(transcript)
        key_points = extract_key_points(transcript)
        keywords = extract_keywords(transcript)
    except Exception as e:
        raise VideoProcessingError(f"AI analysis failed: {e}")

    return {
        "status": "success",
        "video_id": video_id,
        "video_title": video_title,
        "source_used": source_used,
        "short_summary": short_summary.strip(),
        "detailed_summary": detailed_summary.strip(),
        "key_points": key_points,
        "keywords": keywords,
        "transcript_preview": transcript[:TRANSCRIPT_PREVIEW_CHARS].strip()
        + ("..." if len(transcript) > TRANSCRIPT_PREVIEW_CHARS else ""),
        "transcript_full": transcript,
        "error": None,
    }
