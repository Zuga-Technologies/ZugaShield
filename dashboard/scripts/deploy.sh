#!/bin/bash
# The Pentagon (ZugaShield dashboard) Deploy Script — GIT-based.
# Run from Windows: bash dashboard/scripts/deploy.sh
#
# Sanctioned PC->MM path is git, never scp (cross-platform rule). This clones or
# pulls the ZugaShield repo on the Mac Mini and runs the dashboard from that real
# checkout, then (re)loads the launchd job and health-polls. The service reads
# ZugaShield's own signature/version/benchmark files straight from the checkout.

set -e

REMOTE_HOST="mac"
REPO_URL="https://github.com/Zuga-Technologies/ZugaShield.git"
REMOTE_REPO="~/Projects/ZugaShield"
PORT=8019
HEALTH_URL="http://localhost:$PORT/api/health/live"
PLIST="$REMOTE_REPO/dashboard/scripts/com.zuga.pentagon.plist"

echo "=== The Pentagon Deploy (git) ==="

echo "[1/3] Cloning/pulling ZugaShield on the Mac Mini..."
ssh "$REMOTE_HOST" "mkdir -p ~/Projects && \
  if [ -d $REMOTE_REPO/.git ]; then \
    cd $REMOTE_REPO && git fetch --quiet origin && git reset --hard --quiet origin/master; \
  else \
    git clone --quiet $REPO_URL $REMOTE_REPO; \
  fi && cd $REMOTE_REPO && git log --oneline -1"

echo "[2/3] Restarting via launchd..."
if ssh "$REMOTE_HOST" "launchctl print gui/\$(id -u)/com.zuga.pentagon" >/dev/null 2>&1; then
    # Reinstall the plist (paths/env may have changed) then kickstart.
    ssh "$REMOTE_HOST" "cp $PLIST ~/Library/LaunchAgents/ && launchctl kickstart -k gui/\$(id -u)/com.zuga.pentagon"
else
    ssh "$REMOTE_HOST" "cp $PLIST ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/com.zuga.pentagon.plist"
fi

echo "[3/3] Waiting for health..."
for i in $(seq 1 30); do
    HEALTH=$(ssh "$REMOTE_HOST" "curl -s -m 3 $HEALTH_URL 2>/dev/null" || true)
    if echo "$HEALTH" | grep -q '"ok"' 2>/dev/null; then
        echo "  Pentagon healthy on :$PORT"
        echo "=== Deploy complete ==="
        echo "Logs: ssh mac 'tail -f /tmp/pentagon.log'"
        exit 0
    fi
    sleep 1
done

echo "WARNING: health not responding. Check: ssh mac 'tail -30 /tmp/pentagon-error.log'"
exit 1
