#!/usr/bin/env bash
# Commit this run's data/history.json + data/missed_slot.json + data/counter.json + data/youtube_pending.json
# + data/failed_stories/ onto the newest main and push
# (3 tries). history.json is merged entry by entry (merge_history.py), so a build and a publish never conflict;
# counter.json keeps the higher next_video, so a post number is never handed out twice.
# Usage (repo root, inside Actions): bash pipeline/push_state.sh "Commit message"
set -e
msg="$1"
git config user.name "horror-bot"
git config user.email "horror-bot@users.noreply.github.com"
if [ -z "$(git status --porcelain -- data/history.json data/missed_slot.json data/counter.json data/youtube_pending.json data/failed_stories data/hollywood/memory.json)" ]; then
  echo "Nothing to save"; exit 0
fi
tmp="${RUNNER_TEMP:-$(mktemp -d)}"
# base = the main commit this run read its state from (common.sync_shared_state on another branch), else HEAD
base_ref=HEAD; [ -s .state_base ] && base_ref=$(cat .state_base)
git show "$base_ref":data/history.json > "$tmp/base.json" 2>/dev/null || echo "[]" > "$tmp/base.json"
cp data/history.json "$tmp/ours.json"
rm -rf "$tmp/failed_stories"; [ -d data/failed_stories ] && cp -r data/failed_stories "$tmp/failed_stories"  # parked stories
had_missed=0; git cat-file -e "$base_ref":data/missed_slot.json 2>/dev/null && had_missed=1
rm -f "$tmp/missed.json"
# only THIS run's change to the missed slot is applied (a copy read from main and left alone never re-adds a slot
# that main removed meanwhile)
if [ -f data/missed_slot.json ] && ! git show "$base_ref":data/missed_slot.json 2>/dev/null | cmp -s - data/missed_slot.json; then
  cp data/missed_slot.json "$tmp/missed.json"
fi
missed_gone=0; [ "$had_missed" = 1 ] && [ ! -f data/missed_slot.json ] && missed_gone=1
rm -f "$tmp/hollywood_memory.json"
[ -n "$(git status --porcelain -- data/hollywood/memory.json)" ] && cp data/hollywood/memory.json "$tmp/hollywood_memory.json"
counter_changed=0
pending_changed=0
if [ -n "$(git status --porcelain -- data/youtube_pending.json)" ]; then   # YouTube paused: videos kept for later
  pending_changed=1; cp data/youtube_pending.json "$tmp/pending_ours.json"
  git show "$base_ref":data/youtube_pending.json > "$tmp/pending_base.json" 2>/dev/null || echo "{}" > "$tmp/pending_base.json"
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
  elif [ "$missed_gone" = 1 ]; then            # builder made up (or expired) the missed slot: remove it
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
  if [ -f "$tmp/hollywood_memory.json" ]; then  # Hollywood's memory (it learns from every video): this run's copy wins
    mkdir -p data/hollywood && cp "$tmp/hollywood_memory.json" data/hollywood/memory.json
    git add data/hollywood/memory.json
  fi
  if [ -d "$tmp/failed_stories" ]; then        # parked / retried stories (checkpoint.park): this run's copy wins
    mkdir -p data/failed_stories && cp -r "$tmp/failed_stories/." data/failed_stories/
    git add data/failed_stories
  fi
  git diff --cached --quiet && { echo "Nothing new to save"; exit 0; }
  git commit -q -m "$msg $(date -u +%F_%H%M)"
  git push -q origin HEAD:main && exit 0
  echo "Push failed (try $i), retrying"; sleep 5
done
exit 1
