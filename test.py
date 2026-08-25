"""
test.py

CLI entry point — same interaction style as the original main.py's
__main__ block, now calling the shared core.pipeline.analyze_video()
so the CLI and the FastAPI backend stay in sync.

Run with:
    python test.py
"""

from core.pipeline import analyze_video, VideoProcessingError

if __name__ == "__main__":
    source = input("Enter a YouTube URL: ").strip()
    language = input("Language (english/hinglish) [english]: ").strip() or "english"

    try:
        result = analyze_video(source, language=language)
    except VideoProcessingError as e:
        print(f"\nError: {e}")
        raise SystemExit(1)

    print("\n" + "=" * 60)
    print(f"Title: {result['video_title']}")
    print(f"Source: {result['source_used']}")
    print(f"\nQuick summary:\n{result['short_summary']}")
    print(f"\nDetailed summary:\n{result['detailed_summary']}")
    print("\nKey points:")
    for point in result["key_points"]:
        print(f"  - {point}")
    print(f"\nKeywords: {', '.join(result['keywords'])}")
    print("=" * 60)
