# Linux support and CLI installation

Untangle runs on x86-64 Linux. X11 with OBS 27 is the existing recording path.
OBS 30–33 use X11 EGL for the native Qt preview. On Wayland, including Omarchy's
Hyprland desktop, the UI runs through Xwayland and OBS captures the selected
screen or window through PipeWire and the desktop portal.

The Wayland path has automated synthetic coverage. It is not yet verified by a
live Omarchy recording. Passing the doctor command establishes software and
version prerequisites, not camera, microphone, GPU or portal operation.

## Install from a checkout

Every installation runs the prerequisite checks, on every platform. If a
required program is missing or its version is incompatible, the installer shows
the repair commands and asks whether to install or upgrade those prerequisites.
Declining stops the installation. No Untangle runtime is staged until all native
prerequisites pass. If Python itself is missing, a shell bootstrap offers to
install it before running the detailed checks.

Automatic repair uses the native package manager on Arch/Omarchy, Debian/Ubuntu
and derivatives, Fedora/RHEL and derivatives, and openSUSE. An unknown platform
still gets the checks, but unsupported systems and package managers require
manual repair. Untangle itself remains an x86-64 Linux application.

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

Check-only mode never installs Python or invokes a package manager. If Python
is missing, it returns a failing JSON report. OBS 28/29 and versions after 33 are
rejected. Do not bypass the guard: the Python bindings call native C functions.
OBS 27 is accepted only for X11 capture, not Wayland.

To install with the interactive prerequisite prompt:

```bash
./scripts/install.sh --wayland
```

For X11, omit `--wayland`. For an agent or unattended terminal, explicitly
approve prerequisite installation:

```bash
./scripts/install.sh --yes --wayland
```

Without `--yes`, a noninteractive run stops if prerequisites need repair. With
`--yes`, sudo uses noninteractive mode too: missing privileges fail instead of
waiting for a password. The plan remains visible in the output. `--check` and
`--json` remain read-only even when combined with `--yes`.

For Wayland setup over SSH, set `XDG_CURRENT_DESKTOP` to the target desktop when
a screen-sharing backend must be installed. For Omarchy:

```bash
XDG_CURRENT_DESKTOP=Hyprland ./scripts/install.sh --yes --wayland
```

The installer installs only packages needed by failed checks using configured
repositories. It does not add repositories or force downgrades. If those
repositories cannot provide supported versions, the mandatory fresh-process
recheck fails and Untangle is not installed. A successful package-manager exit
alone never counts as a passing version check.

Arch repairs include `pacman -Syu`, which can upgrade the entire system. This is
shown before consent because [partial upgrades are unsupported](https://wiki.archlinux.org/title/System_maintenance#Partial_upgrades_are_unsupported).
Other families use apt-get, dnf or zypper. Package-manager errors, unavailable
packages and missing administrator privileges stop installation.

If uv is missing or too old, the plan installs it with pip in a private tool
environment at `~/.local/share/glint/bootstrap-tools`, with a command link in
`~/.local/share/glint/tools-bin`. This follows uv's [supported pip installation
method](https://docs.astral.sh/uv/getting-started/installation/#pypi) and does not
modify the system Python or an unrelated uv installation. The installer and
doctor include this private command directory in their own PATH.

After native checks pass, the installer creates a separate Python environment,
installs the pinned dependencies there and checks their versions before replacing
the previous environment. Dependency failure leaves the old runtime in place.
The previous successful environment is retained at
`~/.local/share/glint/venv.previous`. Installation never starts Untangle, signs
in to a service, uploads files, or changes desktop settings. System packages
change only after the prerequisite prompt is accepted or `--yes` is provided.
Approved package changes are not rolled back if a later check fails; the
existing Untangle runtime remains in place.

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
