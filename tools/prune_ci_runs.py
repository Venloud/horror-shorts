"""Prune old completed runs of one explicitly identified CI workflow only.

No external packages. Dry run by default. Never targets other workflow files.
Keep newest 10 completed runs and newest failed/cancelled run even when older.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def request(method, url, token):
    req = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer " + token,
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp) if method == "GET" else None


def select_for_pruning(runs, keep=10):
    if keep < 5 or keep > 100:
        raise ValueError("keep must be between 5 and 100")
    completed = sorted((r for r in runs if r.get("status") == "completed"),
                       key=lambda r: (r.get("created_at", ""), r["id"]), reverse=True)
    protected = {r["id"] for r in completed[:keep]}
    evidence = next((r for r in completed if r.get("conclusion") in
                     {"failure", "cancelled", "timed_out", "action_required"}), None)
    if evidence:
        protected.add(evidence["id"])
    return [r for r in completed if r["id"] not in protected]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Actually delete, otherwise preview only")
    ap.add_argument("--keep", type=int, default=10)
    ap.add_argument("--workflow", default="ci.yml")
    args = ap.parse_args()
    if args.workflow != "ci.yml":
        ap.error("Only ci.yml is permitted by this repo's cleanup policy")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not repo or "/" not in repo or not token:
        ap.error("Requires GITHUB_REPOSITORY and GH_TOKEN/GITHUB_TOKEN")
    root = "https://api.github.com/repos/" + repo
    all_runs = []
    for page in range(1, 101):
        url = (root + "/actions/workflows/" +
               urllib.parse.quote(args.workflow) +
               "/runs?per_page=100&page=" + str(page))
        batch = request("GET", url, token)["workflow_runs"]
        all_runs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise RuntimeError("Too many pages, refusing incomplete inventory/prune")
    candidates = select_for_pruning(all_runs, args.keep)
    print(f"CI runs read: {len(all_runs)}; older completed candidates: {len(candidates)}")
    for run in candidates:
        print(("DELETE " if args.execute else "DRY RUN ") +
              f"{run['id']} {run.get('conclusion')} {run.get('html_url', '')}")
        if args.execute:
            request("DELETE", root + "/actions/runs/" + str(run["id"]), token)
    print("CI history cleanup complete" if args.execute else "Dry run only; no runs removed")


if __name__ == "__main__":
    main()
