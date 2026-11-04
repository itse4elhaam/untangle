#!/bin/bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_path="$HOME/.local/share/glint/venv/bin/python"
[[ -x "$python_path" ]] || { echo 'Install Untangle first.' >&2; exit 1; }
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$unit_dir"
# systemd specifiers and quoted paths require escaping before writing unit files.
escape_unit() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//%/%%}"
    printf '%s' "$value"
}
cat > "$unit_dir/untangle-archive.service" <<EOF
[Unit]
Description=Archive Untangle recordings to Google Drive
[Service]
Type=oneshot
Environment="PYTHONPATH=$(escape_unit "$app_dir/src")"
ExecStart="$(escape_unit "$python_path")" -m untangle.archive
TimeoutStartSec=infinity
UMask=0077
EOF
cat > "$unit_dir/untangle-archive.timer" <<'EOF'
[Unit]
Description=Periodically archive Untangle recordings
[Timer]
OnStartupSec=5min
OnUnitInactiveSec=15min
[Install]
WantedBy=timers.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now untangle-archive.timer
echo 'Background archiving scheduled every 15 minutes while your user session is running.'
