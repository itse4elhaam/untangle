#!/bin/bash
set -euo pipefail

app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
data_dir="$HOME/.local/share/glint"
desktop_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
icon_dir="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"
# Check mode exits before creating directories or changing an existing runtime.
check_only=false
assume_yes=false
export PATH="$HOME/.local/share/glint/tools-bin:$PATH"
preflight_args=()
for argument in "$@"; do
    case "$argument" in
        --check|--json) check_only=true; preflight_args+=("$argument") ;;
        --wayland) preflight_args+=("$argument") ;;
        --yes) assume_yes=true ;;
        *) echo "Usage: $0 [--check] [--json] [--wayland] [--yes]" >&2; exit 2 ;;
    esac
done
# This bootstrap is needed before Python can perform the detailed checks.
# Check-only mode never installs Python or invokes a package manager.
if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
    if [[ "$check_only" == true ]]; then
        echo '{"ok":false,"checks":[{"name":"python","ok":false,"detail":"Python 3.10+ is missing or incompatible; run install.sh interactively to install it"}]}'
        exit 1
    fi
    if [[ "$(uname -s)" != Linux || "$(uname -m)" != x86_64 ]]; then
        echo 'Untangle requires x86-64 Linux. Nothing was installed.' >&2
        exit 1
    fi
    distribution=' '
    if [[ -r /etc/os-release ]]; then
        while IFS='=' read -r release_key release_value; do
            case "$release_key" in
                ID|ID_LIKE)
                    release_value="${release_value//\"/}"
                    release_value="${release_value//\'/}"
                    distribution+="$release_value " ;;
            esac
        done < /etc/os-release
    fi
    case "$distribution" in
        *' arch '*|*' omarchy '*|*' manjaro '*)
            bootstrap=(pacman -Syu --noconfirm python)
            echo 'Installing Python on Arch includes a full system upgrade.' ;;
        *' debian '*|*' ubuntu '*|*' pop '*|*' linuxmint '*)
            bootstrap=(apt-get install -y python3 python3-venv) ;;
        *' fedora '*|*' rhel '*|*' centos '*|*' rocky '*|*' almalinux '*)
            bootstrap=(dnf install -y python3) ;;
        *' suse '*|*' opensuse '*|*' opensuse-tumbleweed '*|*' opensuse-leap '*)
            bootstrap=(zypper --non-interactive install python3) ;;
        *) echo 'Unsupported platform. Install Python 3.10+ manually and rerun. Nothing was installed.' >&2; exit 1 ;;
    esac
    command -v "${bootstrap[0]}" >/dev/null || {
        echo "${bootstrap[0]} is missing. Install Python 3.10+ manually and rerun." >&2
        exit 1
    }
    privilege=()
    if [[ "$EUID" -ne 0 ]]; then
        command -v sudo >/dev/null || { echo 'sudo is missing; ask an administrator to install Python 3.10+.' >&2; exit 1; }
        privilege=(sudo)
        if [[ "$assume_yes" == true ]]; then privilege+=(-n); fi
    fi
    printf 'Python 3.10+ is required. Proposed command: '
    printf '%q ' "${privilege[@]}" "${bootstrap[@]}"
    echo
    if [[ "$assume_yes" != true ]]; then
        [[ -t 0 ]] || { echo 'No interactive input. Rerun in a terminal or use --yes to approve prerequisite installation.' >&2; exit 1; }
        read -r -p 'Install/upgrade Python before checking the remaining prerequisites? [y/N] ' reply || reply=''
        [[ "$reply" == y || "$reply" == Y || "$reply" == yes || "$reply" == YES ]] || exit 1
    fi
    if [[ "${bootstrap[0]}" == apt-get ]]; then
        if ! "${privilege[@]}" apt-get update; then
            echo 'Package index refresh failed. Untangle was not installed.' >&2
            exit 1
        fi
    fi
    if ! "${privilege[@]}" "${bootstrap[@]}"; then
        echo 'Python installation failed. Untangle was not installed.' >&2
        exit 1
    fi
    if ! command -v python3 >/dev/null || ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        echo 'Python 3.10+ is still unavailable from these repositories. Untangle was not installed.' >&2
        exit 1
    fi
fi
if [[ "$check_only" == true ]]; then
    exec python3 "$app_dir/src/untangle/preflight.py" "${preflight_args[@]}"
fi
repair_args=(--install-deps)
if [[ "$assume_yes" == true ]]; then repair_args+=(--yes); fi
python3 "$app_dir/src/untangle/preflight.py" "${preflight_args[@]}" "${repair_args[@]}"
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
ln -sfn "$app_dir/bin/untangle-review" "$HOME/.local/bin/untangle-review"
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
