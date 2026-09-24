"""One-time: swap the TikTok login code for a refresh token (run by the 'Connect TikTok' workflow)."""
import os
import sys
import urllib.parse

import requests


def main() -> int:
    raw = os.environ.get("AUTH_CODE_OR_URL", "").strip()
    if "code=" in raw:  # user pasted the whole redirect URL
        raw = urllib.parse.parse_qs(urllib.parse.urlparse(raw).query).get("code", [""])[0]
    code = urllib.parse.unquote(raw)
    if not code:
        sys.exit("No code given.")

    r = requests.post("https://open.tiktokapis.com/v2/oauth/token/", timeout=30,
                      headers={"Content-Type": "application/x-www-form-urlencoded"},
                      data={
                          "client_key": os.environ["TIKTOK_CLIENT_KEY"],
                          "client_secret": os.environ["TIKTOK_CLIENT_SECRET"],
                          "code": code,
                          "grant_type": "authorization_code",
                          "redirect_uri": os.environ["TIKTOK_REDIRECT_URI"],
                      })
    data = r.json()
    if "refresh_token" not in data:
        sys.exit(f"TikTok said no: {data}\nLogin codes expire fast. Get a fresh one and run this again within a few minutes.")
    scopes = data.get("scope", "")
    if "video.upload" not in scopes and "video.publish" not in scopes:
        print(f"WARNING: token scopes are '{scopes}'. Add video.upload in the TikTok developer portal.")
    with open(".new_refresh_token", "w") as f:
        f.write(data["refresh_token"])
    print(f"Connected. Scopes: {scopes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
