#!/bin/bash
set -euo pipefail

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
data_dir="$HOME/.local/share/glint"
command -v uv >/dev/null || { echo 'Install uv before running this installer.' >&2; exit 1; }
command -v obs >/dev/null || { echo 'Untangle needs OBS Studio 27 and its plugins.' >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo 'Install FFmpeg before running this installer.' >&2; exit 1; }
mkdir -p "$data_dir" "$HOME/.local/bin" "$HOME/.local/share/applications" "$HOME/.local/share/icons/hicolor/scalable/apps"
if [[ ! -x "$data_dir/venv/bin/python" ]]; then
    uv venv "$data_dir/venv"
fi
uv pip install --python "$data_dir/venv/bin/python" -r "$app_dir/requirements.txt"
ln -sfn "$app_dir/untangle" "$HOME/.local/bin/untangle"
ln -sfn "$app_dir/recit" "$HOME/.local/bin/recit"
ln -sfn "$app_dir/assets/untangle-mark.svg" "$HOME/.local/share/icons/hicolor/scalable/apps/tech.truedevs.Untangle.svg"
cat > "$HOME/.local/share/applications/tech.truedevs.Untangle.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Untangle
GenericName=Screen and Camera Recorder
Comment=Record an explanation. Share it with Loom.
Exec="$HOME/.local/bin/untangle"
Icon=tech.truedevs.Untangle
Terminal=false
Categories=AudioVideo;Video;Recorder;
Keywords=record;screen;camera;loom;video;explainer;
StartupNotify=true
StartupWMClass=Untangle
EOF
# Replace the legacy launcher entry so installation exposes one app.
rm -f "$HOME/.local/share/applications/tech.truedevs.RecIt.desktop"
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$HOME/.local/share/applications"
fi
echo 'Untangle is installed. Find it in your app launcher, or run untangle.'
