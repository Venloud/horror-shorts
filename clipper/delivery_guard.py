"""Fail-closed durable deduplication for the scheduled TikTok inbox clipper.

Uses GitHub Contents API as a compare-and-swap ledger. Reserve BEFORE any upload.
Uncertain attempts remain blocked until explicitly reconciled; never auto retry.
"""
import argparse
import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

FILE = "data/clipper_delivery_ledger.json"

def api(method, data=None, sha=None):
    repo = os.environ["GITHUB_REPOSITORY"]
    token = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("No GitHub write token; refusing to upload")
    url = f"https://api.github.com/repos/{repo}/contents/{FILE}"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    if method == "PUT":
        payload = {"message": "state: reserve scheduled TikTok clip upload",
                   "content": base64.b64encode(json.dumps(data, indent=2).encode()).decode(),
                   "branch": "main"}
        if sha:
            payload["sha"] = sha
        body = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = None
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.load(res)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        raise

def read():
    response = api("GET")
    if not response:
        return {"entries": []}, None
    obj = json.loads(base64.b64decode(response["content"]))
    if not isinstance(obj, dict) or not isinstance(obj.get("entries"), list):
        raise ValueError("Malformed delivery ledger, refusing upload")
    return obj, response["sha"]

def update(part, slot, state, publish_id=""):
    for _ in range(3):
        ledger, sha = read()
        entries = ledger["entries"]
        existing = next((x for x in entries if x.get("part") == part), None)
        if state == "reserved":
            if existing:
                print(f"Part {part} already {existing.get('state')}, skipping upload")
                return False
            entries.append({"part": part, "slot": slot, "state": "reserved",
                            "created_at": datetime.now(timezone.utc).isoformat()})
        else:
            if not existing or existing.get("slot") != slot or existing.get("state") != "reserved":
                raise RuntimeError("Reservation mismatch, refusing ledger finalization")
            existing["state"] = state
            existing["publish_id"] = publish_id
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            api("PUT", ledger, sha)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code not in (409, 422):
                raise
    raise RuntimeError("Ledger update conflicts, refusing upload")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["reserve", "confirm"])
    p.add_argument("--part", type=int, required=True)
    p.add_argument("--slot", type=int, required=True)
    p.add_argument("--publish-id", default="")
    args = p.parse_args()
    if args.part < 1 or args.slot < 0:
        p.error("Invalid part or slot")
    if args.action == "confirm" and not args.publish_id:
        p.error("publish ID required for confirmation")
    ok = update(args.part, args.slot, "reserved" if args.action == "reserve" else "delivered", args.publish_id)
    if not ok:
        raise SystemExit(3)

if __name__ == "__main__":
    main()
