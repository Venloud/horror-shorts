"""One-time, run on YOUR computer (it opens a browser): get the YouTube refresh token for YT_REFRESH_TOKEN.

  pip install google-auth-oauthlib
  python connect_youtube.py path/to/client_secret.json

client_secret.json = Google Cloud Console -> APIs & Services -> Credentials -> OAuth client ID (type: Desktop app).
Sign in with the Google account that owns the YouTube channel. Put the printed values into the GitHub repo
secrets YT_CLIENT_ID, YT_CLIENT_SECRET and YT_REFRESH_TOKEN. Never paste them into a chat.
Set the OAuth consent screen to "In production" first: in "Testing" mode Google expires the token after 7 days.
"""
import json
import sys


def main() -> int:
    from google_auth_oauthlib.flow import InstalledAppFlow
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1],
                                                     ["https://www.googleapis.com/auth/youtube.upload"])
    creds = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    info = json.load(open(sys.argv[1]))
    client = info.get("installed") or info.get("web") or {}
    print("\nAdd these as GitHub repo secrets:\n")
    print(f"YT_CLIENT_ID      = {client.get('client_id')}")
    print(f"YT_CLIENT_SECRET  = {client.get('client_secret')}")
    print(f"YT_REFRESH_TOKEN  = {creds.refresh_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
