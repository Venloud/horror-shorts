#!/usr/bin/env bash
# Commit this run's data/history.json + data/missed_slot.json onto the newest main and push (3 tries).
# history.json is merged entry by entry (merge_history.py), so a build and a publish never conflict.
# Usage (repo root, inside Actions): bash pipeline/push_state.sh "Commit message"
set -e
msg="$1"
git config user.name "horror-bot"
git config user.email "horror-bot@users.noreply.github.com"
if [ -z "$(git status --porcelain -- data/history.json data/missed_slot.json)" ]; then
  echo "Nothing to save"; exit 0
fi
tmp="${RUNNER_TEMP:-$(mktemp -d)}"
git show HEAD:data/history.json > "$tmp/base.json" 2>/dev/null || echo "[]" > "$tmp/base.json"
cp data/history.json "$tmp/ours.json"
had_missed=0; git cat-file -e HEAD:data/missed_slot.json 2>/dev/null && had_missed=1
rm -f "$tmp/missed.json"; [ -f data/missed_slot.json ] && cp data/missed_slot.json "$tmp/missed.json"
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
  git diff --cached --quiet && { echo "Nothing new to save"; exit 0; }
  git commit -q -m "$msg $(date -u +%F_%H%M)"
  git push -q origin HEAD:main && exit 0
  echo "Push failed (try $i), retrying"; sleep 5
done
exit 1
