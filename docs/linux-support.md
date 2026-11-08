# Linux support and installation

Untangle targets x86-64 Linux. X11 supports OBS 27 or 30–33; modern OBS uses EGL
for the native Qt preview. Wayland, including Omarchy/Hyprland, requires OBS
30–33, Xwayland for the UI, and PipeWire/desktop-portal screen selection.
OBS 28/29 and versions after 33 are rejected because the bindings call native C
functions whose layouts must be reviewed. See
[preflight.check](../src/untangle/preflight.py), [engine.py](../src/untangle/engine.py),
and [native-version tests](../tests/test_modern_obs.py).

Synthetic coverage does not establish a successful Omarchy recording. Passing
preflight establishes software prerequisites, not camera, microphone, GPU,
encoder loading or portal operation. Live Omarchy validation remains outstanding
as of the 2026-11-09 documentation audit.

## Check before installing

From the checkout, including over SSH:

```bash
./scripts/install.sh --check --json --wayland
```

Omit `--wayland` for X11. `--json` implies check-only mode, even with `--yes`.
Exit codes are 0 for success, 1 for failed prerequisites and 2 for invalid arguments.
Checks never start Qt, OBS capture, audio, Bluetooth or portal sessions. They load
libobs only to read its version and inspect plugin files. Missing Python produces
a failing report; check-only mode never installs it.

## Install only when explicitly authorized

```bash
./scripts/install.sh --wayland
```

Every installation checks native prerequisites before staging a runtime. The
interactive prompt offers repairs; declining stops installation. Noninteractive
runs stop when repair is needed unless explicitly authorized with `--yes`.
That option also makes sudo noninteractive, so missing privileges fail.
For Omarchy over SSH, identify the target desktop when planning portal packages:

```bash
XDG_CURRENT_DESKTOP=Hyprland ./scripts/install.sh --yes --wayland
```

[preflight.py](../src/untangle/preflight.py) owns package plans for Arch,
Debian/Ubuntu, Fedora/RHEL and openSUSE families. Unknown platforms require manual
repair. Plans use configured repositories only, with no added repositories or
forced downgrades. Arch repair includes `pacman -Syu`, potentially upgrading the
whole system because [partial upgrades are unsupported](https://wiki.archlinux.org/title/System_maintenance#Partial_upgrades_are_unsupported).
A fresh-process version recheck must pass even if the package manager succeeds.
Approved package changes are not rolled back after later failure.

Missing/old uv is installed through pip into
`~/.local/share/glint/bootstrap-tools`, linked under `~/.local/share/glint/tools-bin`.
This leaves system Python and unrelated uv installations alone. See uv's
[pip installation guidance](https://docs.astral.sh/uv/getting-started/installation/#pypi).
These external guidance links were retained, not revalidated in this audit.

[scripts/install.sh](../scripts/install.sh) stages pinned Python dependencies and
checks their versions before replacing the runtime. Failure preserves the old
environment; the previous successful one remains at
`~/.local/share/glint/venv.previous`. Keep the checkout in place because installed
launchers point to it. Rerunning refreshes dependencies, launchers and icons.
Installation does not launch Untangle, authenticate, upload or change desktop settings.

After installation, in the graphical session:

```bash
untangle-doctor --json --wayland --session
```

`--session` checks environment variables without contacting services. Runtime
checks include Essentials, Addons and Shiboken 6.11.1; see the
[Qt crash rationale](testing.md#reasons-for-the-qt-safeguards).

## Wayland operation and remaining validation

In an explicitly launched session, choose Screen and select a source in the
system picker. **Choose / change source** retries cancellation or changes source.
Recording stays disabled during permission/video negotiation; a two-minute timeout
releases a pending session. Selection survives microphone preparation and ordinary
setup changes, but ends on camera-only mode, idle library navigation, or quit.
Browsing Recordings during a stable active take preserves its portal source.

The camera is composited into the recording. X11 global shortcuts, pointer zoom,
the desktop camera bubble and presentation switching are disabled. Stop/save or
pause through the recorder/tray; without a tray the recorder stays visible.
The portal, not an X11 catalogue, determines available native Wayland windows.
See [Wayland UI tests](../tests/test_wayland_ui.py).

Before claiming Omarchy support, obtain authorization for screen/window selection,
cancel/retry, scaling, camera/audio, pause/resume, remux, portal termination and
exit-cleanup checks. Playback needs explicit authorization too. Recheck X11/OBS 27
and available Intel/AMD/NVIDIA systems; one GPU cannot establish all drivers.
No authentication/upload is required. Safe regression owners are
[test_preflight.py](../tests/test_preflight.py) and
[test_install_preflight.py](../tests/test_install_preflight.py); run through
[the isolated runner](testing.md).
