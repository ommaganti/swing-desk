#!/usr/bin/env bash
# Remove the swingdesk morning-refresh launchd agent.
set -euo pipefail
LABEL="com.swingdesk.refresh"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
launchctl unload "$PLIST" 2>/dev/null || true
rm -f "$PLIST"
echo "Removed $LABEL (morning refresh agent)."
