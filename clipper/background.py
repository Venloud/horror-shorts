"""Fetch a rotating Minecraft parkour background from approved creator links."""
import argparse
import hashlib
import subprocess
import urllib.parse
from pathlib import Path

# Creator reuse permissions should be rechecked before production distribution.
SOURCES=[
    "https://www.youtube.com/watch?v=u7kdVe8q5zs", # Orbital
    "https://www.youtube.com/watch?v=JlPEb6WNuDI", # Spicy Sauce
]
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--url",default="")
    p.add_argument("--output",default="/tmp/clipper_background.mp4")
    a=p.parse_args()
    # Rotate by day; deterministic for reruns on the same day.
    from datetime import datetime,timezone
    day=datetime.now(timezone.utc).date().toordinal()
    source=a.url.strip() or SOURCES[day%len(SOURCES)]
    parsed=urllib.parse.urlparse(source)
    if parsed.scheme!="https" or not parsed.hostname:
        p.error("Background URL must be HTTPS")
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(["yt-dlp","--no-playlist","--max-filesize","150M",
                    "-f","bv*[height<=1080]+ba/b[height<=1080]/b",
                    "--merge-output-format","mp4","-o",str(out),source],check=True)
    if not out.is_file():raise RuntimeError("Background video was not downloaded as an MP4")
    print(f"Background ready: {source}")
if __name__=="__main__":main()
