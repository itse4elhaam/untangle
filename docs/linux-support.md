# Linux support and CLI installation

Untangle runs on x86-64 Linux. X11 with OBS 27 is the existing recording path.
OBS 30–33 use X11 EGL for the native Qt preview. On Wayland, including Omarchy's
Hyprland desktop, the UI runs through Xwayland and OBS captures the selected
screen or window through PipeWire and the desktop portal.

The Wayland path has automated synthetic coverage. It is not yet verified by a
live Omarchy recording. Passing the doctor command establishes software and
version prerequisites, not camera, microphone, GPU or portal operation.

## Install from a checkout

On Arch / Omarchy, install the system prerequisites explicitly:

```bash
sudo pacman -S --needed python uv obs-studio ffmpeg libpulse v4l-utils \
  xorg-xwayland pipewire pipewire-pulse xdg-desktop-portal \
  xdg-desktop-portal-hyprland
```

An agent can check the checkout before making installation changes, including
over SSH. Run these commands from the repository root:

```bash
./scripts/install.sh --check --json --wayland
```

The JSON object includes `ok`, individual `checks` with `name`, `ok` and `detail`,
and installation hints. Exit status 0 means the checks passed, 1 means a missing
or incompatible prerequisite, and 2 means invalid arguments. `--json` implies
check-only mode. Checks do not start Qt, OBS, audio, Bluetooth or portal sessions.
They load libobs only to read its version and inspect plugin files.

If `python3` itself is missing, the shell reports it before creating anything.
Install Python first. On Ubuntu, use `obs-studio`, `ffmpeg`, `pulseaudio-utils`,
and `v4l-utils`; install uv separately. OBS 28/29 and versions after 33 are
rejected. Do not bypass the guard: the Python bindings call native C functions.
OBS 27 is accepted only for X11 capture, not Wayland.

When checks pass, install explicitly:

```bash
./scripts/install.sh --wayland
```

For X11, omit `--wayland`. The installer creates a separate Python environment,
installs the pinned dependencies there and checks their versions before replacing
the previous environment. Dependency failure leaves the old runtime in place.
The previous successful environment is retained at
`~/.local/share/glint/venv.previous`. Installation never starts Untangle, signs
in to a service, uploads files, or changes system packages or desktop settings.

Keep this checkout in place. The CLI and desktop entry point to its launchers.
Rerunning the installer refreshes dependencies, launchers and icons. Existing
settings, recording paths and compatibility identifiers stay unchanged.

After installation, from a terminal in the graphical session:

```bash
untangle-doctor --json --wayland --session
```

This also checks the installed PySide6 Essentials, Addons and Shiboken versions
against 6.11.1. `--session` checks DISPLAY and session-bus environment variables;
it does not contact the services or request permission. Plugin file presence is
checked, but loading each plugin and verifying encoders happens at engine startup.
A session can still fail despite having the correct packages installed.

## Recording on Wayland

Launch Untangle explicitly from the application menu or `untangle`. Switch to
Screen mode and choose a screen or window in the system picker. Use
**Choose / change source** to retry a cancelled permission request or select a
different source. Recording stays disabled while permission or video negotiation
is pending. After two minutes without video, the pending session is released.
Selection remains alive across microphone preparation and ordinary setup changes;
it is released when switching to camera-only mode, opening Recordings, or quitting.

The camera is composited into the recorded video. Global X11 shortcuts, pointer
zoom, the desktop camera bubble, and camera presentation switching are disabled
on Wayland. Use the recorder or tray menu to stop/save and pause. If no system
tray is available, the recorder stays visible so stop/save remains reachable.
The portal controls which displays/windows are available; Untangle does not use
an X11 window catalogue to select native Wayland windows.

## Validation before calling Omarchy supported

Automated tests use private devices, networking and runtime directories through
`./scripts/test.sh`. They cover version guards, native structure layouts, portal
readiness and ownership, UI gating, and failed installation preserving the runtime.
They also run the existing X11/UI/audio regression tests with synthetic sources.

Live validation requires explicit authorization and an Omarchy machine. Check
screen and native Wayland-window selection, cancellation/retry, multi-monitor
scaling, camera composition, microphone and desktop audio, pause/resume, stop and
remux, portal termination, and exit cleanup. Review the saved MP4 with playback
explicitly authorized. Test an existing X11 / OBS 27 installation too. Include
Intel/AMD/NVIDIA results as available; a single GPU does not establish all-driver
compatibility. No upload or authentication is part of this validation.
