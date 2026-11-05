#!/bin/bash
set -euo pipefail

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="$HOME/.local/share/glint"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
# Check mode exits before creating directories or changing an existing runtime.
check_only=false
preflight_args=()
for argument in "$@"; do
    case "$argument" in
        --check|--json) check_only=true; preflight_args+=("$argument") ;;
        --wayland) preflight_args+=("$argument") ;;
        *) echo "Usage: $0 [--check] [--json] [--wayland]" >&2; exit 2 ;;
    esac
done
if [[ "$check_only" == true ]]; then
    exec python3 "$app_dir/src/untangle/preflight.py" "${preflight_args[@]}"
fi
python3 "$app_dir/src/untangle/preflight.py" "${preflight_args[@]}"
mkdir -p "$data_dir" "$HOME/.local/bin" "$desktop_dir" "$icon_dir/scalable/apps"
stage="$(mktemp -d "$data_dir/venv-stage.XXXXXX")"
trap 'rm -rf -- "$stage"' EXIT
uv venv --python "$(command -v python3)" --relocatable "$stage"
uv pip install --python "$stage/bin/python" -r "$app_dir/requirements.txt"
"$stage/bin/python" "$app_dir/src/untangle/preflight.py" --runtime "${preflight_args[@]}"
mkdir -p "$stage/untangle-icons/scalable/apps"
# Copy rather than link so icon lookup does not depend on the checkout path.
cp --remove-destination "$app_dir/assets/untangle-mark.svg" "$stage/untangle-icons/scalable/apps/tech.truedevs.Untangle.svg"
# QtSvg is already an app dependency. Rendering QImages needs no app or display.
"$stage/bin/python" - "$stage/untangle-icons" <<'PY'
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(sys.argv[1])
renderer = QSvgRenderer(str(root / 'scalable/apps/tech.truedevs.Untangle.svg'))
if not renderer.isValid():
    raise SystemExit('Cannot render the Untangle menu icon.')
for size in (16, 24, 32, 48, 64, 128, 256, 512):
    target = root / f'{size}x{size}/apps/tech.truedevs.Untangle.png'
    target.parent.mkdir(parents=True, exist_ok=True)
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    temporary = target.with_suffix('.tmp.png')
    if not image.save(str(temporary)):
        raise SystemExit(f'Cannot save menu icon: {temporary}')
    temporary.replace(target)
PY

# Keep the old runtime until dependencies and icon rendering have succeeded.
backup="$data_dir/venv.previous"
rm -rf -- "$backup"
if [[ -e "$data_dir/venv" ]]; then
    mv -- "$data_dir/venv" "$backup"
fi
if ! mv -- "$stage" "$data_dir/venv"; then
    if [[ -e "$backup" ]]; then mv -- "$backup" "$data_dir/venv"; fi
    exit 1
fi
ln -sfn "$app_dir/bin/untangle-doctor" "$HOME/.local/bin/untangle-doctor"
ln -sfn "$app_dir/bin/untangle" "$HOME/.local/bin/untangle"
ln -sfn "$app_dir/bin/recit" "$HOME/.local/bin/recit"
# Copy rather than link so icon lookup does not depend on the checkout path.
cp --remove-destination "$data_dir/venv/untangle-icons/scalable/apps/tech.truedevs.Untangle.svg" "$icon_dir/scalable/apps/tech.truedevs.Untangle.svg"
for size in 16 24 32 48 64 128 256 512; do
    mkdir -p "$icon_dir/${size}x${size}/apps"
    cp --remove-destination "$data_dir/venv/untangle-icons/${size}x${size}/apps/tech.truedevs.Untangle.png" "$icon_dir/${size}x${size}/apps/tech.truedevs.Untangle.png"
done
cat > "$desktop_dir/tech.truedevs.Untangle.desktop" <<EOF
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
rm -f "$desktop_dir/tech.truedevs.RecIt.desktop"
if command -v gtk-update-icon-cache >/dev/null; then
    # User hicolor directories can inherit the system index.theme without a copy.
    gtk-update-icon-cache --force --ignore-theme-index "$icon_dir"
fi
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$desktop_dir"
fi
echo 'Untangle is installed. Find it in your app launcher, or run untangle.'
