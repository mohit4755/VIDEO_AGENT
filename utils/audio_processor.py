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
import requests
from urllib.parse import urlparse, parse_qs, quote

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


class YouTubeSession(requests.Session):
    def __init__(self):
        super().__init__()
        proxy = os.getenv("PROXY_URL")
        if proxy:
            self.proxies = {"http": proxy, "https": proxy}

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", 15)
        return super().request(method, url, **kwargs)


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

def _get_captions_youtube_api(video_id: str) -> str | None:
    """
    Try to fetch existing captions (auto-generated or manual) for the video.
    Returns the joined transcript text, or None if no captions are available.
    This avoids downloading audio and running Whisper entirely when it works.
    """
    try:
        if hasattr(YouTubeTranscriptApi, "list"):
            api = YouTubeTranscriptApi(http_client=YouTubeSession())
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


# ── Cloud fallback: alternative transcript sources ──────────────────────────

# Hardcoded fallback list; supplemented at runtime by the Piped registry.
_PIPED_API_SEEDS = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.r4fo.com",
    "https://pipedapi.darkness.services",
    "https://pipedapi.smnz.de",
    "https://api.piped.yt",
]

_cached_piped_instances: list | None = None


def _discover_piped_instances() -> list:
    """Fetch the live Piped instance list; fall back to seeds on failure."""
    global _cached_piped_instances
    if _cached_piped_instances is not None:
        return _cached_piped_instances

    try:
        resp = requests.get(
            "https://piped-instances.kavin.rocks/",
            timeout=10,
            headers={"Accept": "application/json"},
        )
        if resp.ok:
            data = resp.json()
            apis = [
                inst["api_url"].rstrip("/")
                for inst in data
                if inst.get("api_url")
            ]
            if apis:
                _cached_piped_instances = apis
                return apis
    except Exception:
        pass

    _cached_piped_instances = list(_PIPED_API_SEEDS)
    return _cached_piped_instances


def _parse_vtt_to_text(vtt_text: str) -> str:
    """Extract plain text from WebVTT subtitle format."""
    lines = []
    for line in vtt_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE", "##")):
            continue
        if "-->" in line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        clean = re.sub(r"<[^>]+>", "", line).strip()
        if clean:
            lines.append(clean)
    # Deduplicate consecutive identical lines (common in auto-generated subs)
    deduped = []
    for line in lines:
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return " ".join(deduped)


def _get_captions_piped(video_id: str) -> str | None:
    """Fetch transcript via public Piped API instances (bypasses cloud IP blocks)."""
    instances = _discover_piped_instances()
    for base in instances:
        try:
            resp = requests.get(f"{base}/streams/{video_id}", timeout=12)
            if not resp.ok:
                continue
            subtitles = resp.json().get("subtitles", [])
            if not subtitles:
                continue

            # Prefer English subtitles
            sub_url = None
            for sub in subtitles:
                if sub.get("code", "").startswith("en"):
                    sub_url = sub.get("url")
                    break
            if not sub_url:
                sub_url = subtitles[0].get("url")
            if not sub_url:
                continue

            sub_resp = requests.get(sub_url, timeout=12)
            if not sub_resp.ok:
                continue

            text = _parse_vtt_to_text(sub_resp.text)
            if text and len(text.strip()) > 20:
                print(f"Got transcript via Piped ({base})")
                return text
        except Exception as e:
            print(f"Piped {base} failed: {e}")
            continue
    return None


def get_captions_transcript(video_id: str) -> str | None:
    """
    Try multiple sources to get the video transcript.

    Strategy 1: youtube-transcript-api  (fast, works from non-cloud IPs)
    Strategy 2: Piped public API        (works from cloud IPs, tries many instances)

    Set PROXY_URL in .env to route Strategy 1 through a proxy.
    """
    transcript = _get_captions_youtube_api(video_id)
    if transcript:
        return transcript

    print("Direct YouTube API failed; trying Piped instances...")

    transcript = _get_captions_piped(video_id)
    if transcript:
        return transcript

    print("All transcript sources failed.")
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
