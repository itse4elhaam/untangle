# Untangle

![Untangle](assets/untangle-banner.svg)

A clear recording beats another long message.

Untangle is a native Linux screen and camera recorder built with Qt and OBS. Record, review, name, and optionally share a video. Recordings stay on your computer until you choose an upload, including opting in for an individual take.

## Record and review

Choose Camera or Screen, select your devices, check the microphone, and use **Start recording** in the bottom bar. Camera mode offers landscape, social canvases, source-size output and zoom. Recordings lets you review saved videos, rename them, recover MKVs, and share through Loom or Google Drive.

Recording starts in MKV for interruption recovery; FFmpeg prepares MP4 without re-encoding after stopping. Optional smaller camera files trade some detail for size. Screen encoding stays unchanged.

[Using Untangle](docs/usage.md) covers controls, audio, sharing and recovery. [Google Drive setup](docs/google-drive.md) covers the manual setup wizard and credentials.

## Linux support

Untangle targets x86-64 Linux. OBS 27 supports X11; OBS 30–33 adds EGL preview and Wayland screen/window selection through PipeWire, the desktop portal and Xwayland. The Wayland path has synthetic coverage; live Omarchy validation remains pending. See [requirements and installation](docs/linux-support.md).

Bluetooth silence remains unresolved. A OnePlus test produced silence through native PulseAudio, PipeWire and OBS; why the reported Meet/Loom path worked is unknown. Levels and microphone checks detect some failures but do not prove usable saved audio. See [verification evidence](docs/testing.md).

## Development

With Python 3.10+, uv 0.9+ and the [system prerequisites](docs/linux-support.md):

```bash
uv venv --python /usr/bin/python3 .venv
uv pip install --python .venv/bin/python -r requirements.txt
./scripts/test.sh
```

The runner requires bubblewrap and fails closed if isolation is unavailable. It isolates devices, audio/desktop services and networking with a read-only host filesystem. Use it for all tests; launching the app can open capture devices and requires explicit authorization.

Qt is pinned to 6.11.1 because 6.12.0 crashed the tested Python 3.10 runtime during repeated widget updates. Keep Essentials, Addons and Shiboken matched.

## Installation and existing data

Check prerequisites without installing or opening devices:

```bash
./scripts/install.sh --check --json
# Include Wayland requirements:
./scripts/install.sh --check --json --wayland
```

Installation is a separate manual action. Follow the [installation guide](docs/linux-support.md); tests and cloning do not redirect an installed app.

Untangle was formerly RecIt. Compatibility paths remain `~/Videos/RecIt`, `~/.local/share/glint` and `~/.local/state/glint`, alongside existing settings and single-instance identifiers. See [migration provenance and cutover](docs/migration.md) and [brand assets](docs/brand.md).

Local diagnostics exclude recording contents, window titles, recording filenames, credentials, exception messages and upload payloads. Nothing is uploaded. Logs live under `~/.local/state/glint`; [audio troubleshooting](docs/audio-troubleshooting.md) explains investigation. Updates do not restart an existing instance.
