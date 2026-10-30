#!/bin/bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.." && pwd)"
python_path="$repo_dir/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3)"
fi
command -v bwrap >/dev/null || {
    echo 'Safe tests require bubblewrap (bwrap); refusing to use host devices or audio.' >&2
    exit 1
}
cd -- "$repo_dir"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
# Discovery must stay safe even if a hardware opt-in was exported elsewhere.
# Mocks alone cannot isolate Qt audio or background UI workers. Give tests
# private devices/runtime/network and a read-only view of the host checkout.
# If namespace creation fails, bwrap exits; never fall back to host execution.
exec bwrap --unshare-all --die-with-parent --new-session \
    --ro-bind / / --dev /dev --proc /proc --tmpfs /run --tmpfs /tmp \
    --perms 0700 --dir /run/untangle-tests \
    env -u DISPLAY -u WAYLAND_DISPLAY -u RECIT_TEST_MIC_HARDWARE \
    -u RECIT_HARDWARE_PRIVATE_DISPLAY -u RECIT_NATIVE_PRIVATE_DISPLAY -u RECIT_TEST_XVFB \
    QT_QPA_PLATFORM=offscreen UNTANGLE_SYNTHETIC_SANDBOX=1 \
    XDG_RUNTIME_DIR=/run/untangle-tests PIPEWIRE_RUNTIME_DIR=/run/untangle-tests \
    PULSE_SERVER=unix:/run/untangle-tests/no-pulse \
    PIPEWIRE_REMOTE=untangle-no-pipewire \
    DBUS_SESSION_BUS_ADDRESS=unix:path=/run/untangle-tests/no-session-bus \
    DBUS_SYSTEM_BUS_ADDRESS=unix:path=/run/untangle-tests/no-system-bus \
    "$python_path" -m unittest discover -s tests
