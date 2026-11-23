#!/bin/zsh
# Sets up the kitchen display job on Sam's Mac (Sam, Nov 22 2026). Run once:
#   zsh setup.sh "https://staff.sisyphusbrewing.com/home/kitchen/?k=<wall key>"
# It keeps its own Python packages in ~/.sisyphus/kitchen-cast, saves the page
# address in ~/.sisyphus/kitchen.json (never in the repo), copies the script
# there, and asks macOS (launchd) to run it every 5 minutes while the Mac is on.
set -e
HERE=${0:A:h}
DIR=~/.sisyphus/kitchen-cast
mkdir -p $DIR ~/Library/LaunchAgents
[ -n "$1" ] && printf '{"url": "%s", "name": "Kitchen display"}\n' "$1" > ~/.sisyphus/kitchen.json
chmod 600 ~/.sisyphus/kitchen.json
[ -x $DIR/venv/bin/python ] || python3 -m venv $DIR/venv
$DIR/venv/bin/pip install -q --upgrade pychromecast
cp $HERE/kitchen_cast.py $DIR/kitchen_cast.py
PLIST=~/Library/LaunchAgents/com.sisyphus.kitchen-cast.plist
cat > $PLIST <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.sisyphus.kitchen-cast</string>
  <key>ProgramArguments</key><array><string>$DIR/venv/bin/python</string><string>$DIR/kitchen_cast.py</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$DIR/last.log</string>
  <key>StandardErrorPath</key><string>$DIR/last.log</string>
</dict></plist>
PL
launchctl bootout gui/$(id -u) $PLIST 2>/dev/null || true
launchctl bootstrap gui/$(id -u) $PLIST
echo "Kitchen display job installed. Log: $DIR/last.log"
