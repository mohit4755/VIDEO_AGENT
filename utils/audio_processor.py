"""
utils/audio_processor.py

Original functions (download_youtube_audio, convert_to_wav, chunk_audio,
process_input) are kept from the source repo and used as the fallback
path. New in this version:

  - get_video_id(url) / is_valid_youtube_url(url)  -> URL validation
  - fetch_video_title(url)                          -> metadata without downloading
  - get_captions_transcript(video_id)                -> FAST path via
    youtube-transcript-api (no download, no Whisper) - used whenever the
    video already has captions, which is the common case.

process_input() now returns a dict describing which path was used so
main.py can react accordingly (skip Whisper if captions were found).
"""

import os
import re
from urllib.parse import urlparse, parse_qs

import static_ffmpeg
static_ffmpeg.add_paths()

import yt_dlp
from pydub import AudioSegment
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

DOWNLOAD_DIR = "downloads"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

YOUTUBE_ID_REGEX = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


# ── URL validation / metadata ────────────────────────────────────────────────

def get_video_id(url: str) -> str | None:
    """Extract the 11-character YouTube video ID from any common URL shape."""
    match = YOUTUBE_ID_REGEX.search(url)
    if match:
        return match.group(1)

    # fallback: querystring v= param
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "v" in qs and len(qs["v"][0]) == 11:
        return qs["v"][0]

    return None


def is_valid_youtube_url(url: str) -> bool:
    return get_video_id(url) is not None


def fetch_video_title(url: str) -> str:
    """Get the title without downloading anything (fast metadata-only call)."""
    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get("title", "Untitled Video")


# ── Fast path: captions via youtube-transcript-api ──────────────────────────

def get_captions_transcript(video_id: str) -> str | None:
    """
    Try to fetch existing captions (auto-generated or manual) for the video.
    Returns the joined transcript text, or None if no captions are available.
    This avoids downloading audio and running Whisper entirely when it works.
    """
    try:
        if hasattr(YouTubeTranscriptApi, "list"):
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)
        elif hasattr(YouTubeTranscriptApi, "list_transcripts"):
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
        else:
            api = YouTubeTranscriptApi()
            transcript_list = api.list(video_id)

        # Prefer manually created transcripts, fall back to auto-generated,
        # prefer English but accept any language and let the LLM handle it.
        try:
            transcript = transcript_list.find_transcript(["en", "en-US", "en-GB"])
        except Exception:
            transcript = next(iter(transcript_list))

        entries = transcript.fetch()
        texts = []
        for entry in entries:
            t = getattr(entry, "text", None)
            if t is None and isinstance(entry, dict):
                t = entry.get("text")
            if t:
                texts.append(t)

        joined = " ".join(texts)
        return joined.strip() or None
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable):
        return None
    except Exception as e:
        print(f"Captions lookup failed ({type(e).__name__}: {e}); will fall back to audio.")
        return None


# ── Fallback path: original download + Whisper pipeline ─────────────────────

def download_youtube_audio(url: str) -> str:
    output_path = os.path.join(DOWNLOAD_DIR, "%(title)s.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "noplaylist": True,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "192",
            }
        ],
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info).replace(".webm", ".wav").replace(".m4a", ".wav")
    return filename


def convert_to_wav(input_path: str) -> str:
    """Convert any audio/video file to WAV format using pydub."""
    output_path = os.path.splitext(input_path)[0] + "_converted.wav"
    audio = AudioSegment.from_file(input_path)
    audio = audio.set_channels(1).set_frame_rate(16000)  # 16kHz for Whisper
    audio.export(output_path, format="wav")
    return output_path


def chunk_audio(wav_path: str, chunk_minutes: int = 10) -> list:
    audio = AudioSegment.from_wav(wav_path)
    chunk_ms = chunk_minutes * 60 * 1000
    chunks = []
    for i, start in enumerate(range(0, len(audio), chunk_ms)):
        chunk = audio[start:start + chunk_ms]
        chunk_path = f"{wav_path}_chunk_{i}.wav"
        chunk.export(chunk_path, format="wav")
        chunks.append(chunk_path)
    return chunks


def process_input(source: str) -> list:
    """Original behaviour: download/convert then chunk into WAV pieces."""
    if source.startswith("http://") or source.startswith("https://"):
        print("Detected YouTube URL. Downloading audio...")
        wav_path = download_youtube_audio(source)
    else:
        print("Detected local file. Converting to WAV...")
        wav_path = convert_to_wav(source)

    print("Chunking audio...")
    chunks = chunk_audio(wav_path)
    print(f"Audio ready - {len(chunks)} chunk(s) created.")
    return chunks


def cleanup_chunks(chunks: list) -> None:
    """Best-effort cleanup of temp chunk files after transcription."""
    for path in chunks:
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass
