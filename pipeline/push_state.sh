#!/usr/bin/env bash
# Commit this run's data/history.json + data/missed_slot.json + data/counter.json + data/youtube_pending.json onto the newest main and push
# (3 tries). history.json is merged entry by entry (merge_history.py), so a build and a publish never conflict;
# counter.json keeps the higher next_video, so a post number is never handed out twice.
# Usage (repo root, inside Actions): bash pipeline/push_state.sh "Commit message"
set -e
msg="$1"
git config user.name "horror-bot"
git config user.email "horror-bot@users.noreply.github.com"
if [ -z "$(git status --porcelain -- data/history.json data/missed_slot.json data/counter.json data/youtube_pending.json)" ]; then
  echo "Nothing to save"; exit 0
fi
tmp="${RUNNER_TEMP:-$(mktemp -d)}"
git show HEAD:data/history.json > "$tmp/base.json" 2>/dev/null || echo "[]" > "$tmp/base.json"
cp data/history.json "$tmp/ours.json"
had_missed=0; git cat-file -e HEAD:data/missed_slot.json 2>/dev/null && had_missed=1
rm -f "$tmp/missed.json"; [ -f data/missed_slot.json ] && cp data/missed_slot.json "$tmp/missed.json"
counter_changed=0
pending_changed=0
if [ -n "$(git status --porcelain -- data/youtube_pending.json)" ]; then   # YouTube paused: videos kept for later
  pending_changed=1; cp data/youtube_pending.json "$tmp/pending_ours.json"
  git show HEAD:data/youtube_pending.json > "$tmp/pending_base.json" 2>/dev/null || echo "{}" > "$tmp/pending_base.json"
fi
if [ -n "$(git status --porcelain -- data/counter.json)" ]; then counter_changed=1; cp data/counter.json "$tmp/counter.json"; fi
for i in 1 2 3; do
  git fetch -q origin main
  python pipeline/merge_history.py "$tmp/base.json" "$tmp/ours.json"
  git reset -q --mixed origin/main
  git add data/history.json
  if [ -f "$tmp/missed.json" ]; then          # publisher found the buffer empty: record the missed slot
    cp "$tmp/missed.json" data/missed_slot.json
    git add data/missed_slot.json
  elif [ "$had_missed" = 1 ]; then             # builder made up (or expired) the missed slot: remove it
    git rm -q --cached --ignore-unmatch data/missed_slot.json
    rm -f data/missed_slot.json
  fi
  if [ "$counter_changed" = 1 ]; then         # a video was posted: save the post counter (higher value wins)
    python - "$tmp/counter.json" <<'PY'
import json, subprocess, sys
ours = json.load(open(sys.argv[1])).get("next_video", 1)
p = subprocess.run(["git", "show", "origin/main:data/counter.json"], capture_output=True, text=True)
theirs = json.loads(p.stdout).get("next_video", 1) if p.returncode == 0 and p.stdout.strip() else 1
open("data/counter.json", "w").write(json.dumps({"next_video": max(ours, theirs)}) + "\n")
PY
    git add data/counter.json
  fi
  if [ "$pending_changed" = 1 ]; then          # merged entry by entry (uploaded beats pending)
    git show origin/main:data/youtube_pending.json > "$tmp/pending_theirs.json" 2>/dev/null || echo "{}" > "$tmp/pending_theirs.json"
    python pipeline/youtube_pending.py merge "$tmp/pending_base.json" "$tmp/pending_ours.json" "$tmp/pending_theirs.json" data/youtube_pending.json
    git add data/youtube_pending.json
  fi
  git diff --cached --quiet && { echo "Nothing new to save"; exit 0; }
  git commit -q -m "$msg $(date -u +%F_%H%M)"
  git push -q origin HEAD:main && exit 0
  echo "Push failed (try $i), retrying"; sleep 5
done
exit 1
