"""Send a rendered clip to the Night Files TikTok inbox as a draft only.

Direct/public publishing is intentionally not available to this clipper.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))
from tiktok import send_to_drafts


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--mode", choices=["draft"], default="draft")
    args = parser.parse_args()

    video = Path(args.video)
    if not video.is_file():
        parser.error("Video not found")
    print(send_to_drafts(video))


if __name__ == "__main__":
    main()
