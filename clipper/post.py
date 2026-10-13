"""Send a rendered clip to the existing Night Files TikTok integration."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pipeline"))
from tiktok import send_to_drafts, post_direct
from common import CONFIG

p=argparse.ArgumentParser()
p.add_argument("--video",required=True)
p.add_argument("--mode",choices=["draft","direct"],default="draft")
p.add_argument("--caption",default="MrBeast moments #MrBeast #clips")
a=p.parse_args()
video=Path(a.video)
if not video.is_file():p.error("Video not found")
if a.mode=="direct":
    # Never silently publish as private when public posting was requested.
    CONFIG["direct_privacy"]="PUBLIC_TO_EVERYONE"
    print(post_direct(video,a.caption))
else:
    print(send_to_drafts(video))
