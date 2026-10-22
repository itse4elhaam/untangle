#!/bin/bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")/.." && pwd)"
python_path="$repo_dir/.venv/bin/python"
if [[ ! -x "$python_path" ]]; then
    python_path="$(command -v python3)"
fi
cd -- "$repo_dir"
export PYTHONPATH="$repo_dir/src${PYTHONPATH:+:$PYTHONPATH}"
# Discovery must stay safe even if a hardware opt-in was exported elsewhere.
exec env -u DISPLAY -u WAYLAND_DISPLAY -u RECIT_TEST_MIC_HARDWARE \
    -u RECIT_HARDWARE_PRIVATE_DISPLAY -u RECIT_NATIVE_PRIVATE_DISPLAY -u RECIT_TEST_XVFB \
    QT_QPA_PLATFORM=offscreen "$python_path" -m unittest discover -s tests
