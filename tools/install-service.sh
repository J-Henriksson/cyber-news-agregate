#!/usr/bin/env bash
# Runs cyber-news-agregate as a service of your user, so it collects news whenever
# you are logged in, with no terminal open. Undo with:
#   systemctl --user disable --now cyber-news-agregate && rm ~/.config/systemd/user/cyber-news-agregate.service
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
unit="$HOME/.config/systemd/user/cyber-news-agregate.service"
mkdir -p "$(dirname "$unit")"
cat > "$unit" <<UNIT
[Unit]
Description=cyber-news-agregate: cybersecurity and AI news, compiled and scored
After=network-online.target

[Service]
ExecStart=$root/run.sh
WorkingDirectory=$root
Restart=on-failure
RestartSec=30
# A laptop with little memory to spare: give way to everything else.
MemoryMax=700M
OOMScoreAdjust=600
Nice=10

[Install]
WantedBy=default.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now cyber-news-agregate
echo "Running. Page: http://127.0.0.1:8740   Log: journalctl --user -u cyber-news-agregate -f"
