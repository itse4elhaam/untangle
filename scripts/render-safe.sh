#!/bin/bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.." && pwd)"
output_dir="${1:?Usage: render-safe.sh OUTPUT [ui|settings|walkthrough] [arguments...]}"
renderer="${2:-ui}"
shift
if [[ $# -gt 0 ]]; then shift; fi
case "$renderer" in
    ui) script="render-ui.py" ;;
    settings) script="render-settings-ui.py" ;;
    walkthrough) script="render-walkthrough.py" ;;
    session) script="ux_session.py" ;;
    recording) script="render-recording-experience.py" ;;
    *) echo 'Choose ui, settings, walkthrough, session or recording.' >&2; exit 2 ;;
esac
python_path="$repo_dir/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then python_path="$(command -v python3)"; fi
command -v bwrap >/dev/null || { echo 'Safe rendering requires bubblewrap.' >&2; exit 1; }
mkdir -p -- "$output_dir"
output_dir="$(cd -- "$output_dir" && pwd -P)"
# Only a dedicated evidence directory becomes writable inside the namespace.
case "$output_dir" in
    "$repo_dir"/docs/ux-overhaul/*) ;;
    *) echo 'Output must be a directory under docs/ux-overhaul/.' >&2; exit 2 ;;
esac
cd -- "$repo_dir"
exec bwrap --unshare-all --die-with-parent --new-session \
    --ro-bind / / --dev /dev --proc /proc --tmpfs /run --tmpfs /tmp \
    --perms 0700 --dir /run/untangle-tests --bind "$output_dir" /tmp/artifacts \
    env -u DISPLAY -u WAYLAND_DISPLAY -u RECIT_TEST_MIC_HARDWARE \
    -u RECIT_HARDWARE_PRIVATE_DISPLAY -u RECIT_NATIVE_PRIVATE_DISPLAY -u RECIT_TEST_XVFB \
    QT_QPA_PLATFORM=offscreen QT_STYLE_OVERRIDE=Fusion \
    XDG_SESSION_TYPE=x11 UNTANGLE_SYNTHETIC_SANDBOX=1 \
    XDG_RUNTIME_DIR=/run/untangle-tests PIPEWIRE_RUNTIME_DIR=/run/untangle-tests \
    PULSE_SERVER=unix:/run/untangle-tests/no-pulse PIPEWIRE_REMOTE=untangle-no-pipewire \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/untangle-tests/no-session-bus \
    DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/untangle-tests/no-system-bus \
    "$python_path" "$repo_dir/scripts/$script" --output /tmp/artifacts "$@"
