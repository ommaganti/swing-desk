#!/usr/bin/env bash
# Install a launchd agent that runs the swingdesk morning refresh each weekday.
# Usage: scripts/install_launchd.sh [HOUR]   (HOUR is local 24h, default 8 = 8am)
set -euo pipefail

LABEL="com.swingdesk.refresh"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PY="$PROJECT_DIR/.venv/bin/python"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$PROJECT_DIR/data/refresh.log"
HOUR="${1:-8}"            # pre-open morning run (backfills OI from cache)
CAPTURE_HOUR="${2:-13}"   # midday run during the session (seeds the OI cache)

if [ ! -x "$PY" ]; then
  echo "ERROR: venv python not found at: $PY"
  echo "Create it first:"
  echo "  python3.11 -m venv \"$PROJECT_DIR/.venv\""
  echo "  \"$PROJECT_DIR/.venv/bin/pip\" install -r \"$PROJECT_DIR/requirements.txt\""
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_DIR/data"

day_dict() {  # $1=weekday $2=hour
  printf '    <dict><key>Weekday</key><integer>%s</integer><key>Hour</key><integer>%s</integer><key>Minute</key><integer>0</integer></dict>\n' "$1" "$2"
}

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$PY</string>
    <string>$PROJECT_DIR/refresh.py</string>
  </array>
  <key>WorkingDirectory</key><string>$PROJECT_DIR</string>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
  <key>RunAtLoad</key><false/>
  <key>StartCalendarInterval</key>
  <array>
$(for d in 1 2 3 4 5; do day_dict "$d" "$HOUR"; done)
$(for d in 1 2 3 4 5; do day_dict "$d" "$CAPTURE_HOUR"; done)
  </array>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "Installed $LABEL on weekdays:"
echo "  ${HOUR}:00 local — pre-open refresh (backfills OI from cache)"
echo "  ${CAPTURE_HOUR}:00 local — midday capture (seeds the OI cache while the market is open)"
echo "  plist: $PLIST"
echo "  log:   $LOG"
echo "Run it now:   launchctl start $LABEL"
echo "Uninstall:    scripts/uninstall_launchd.sh"
