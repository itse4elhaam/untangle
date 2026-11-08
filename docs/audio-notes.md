# Microphone processing rationale

Original research was checked on 2026-10-22 against OBS 27.2.3 and Debian/Ubuntu
package `27.2.3+dfsg1-1`. The linked OBS implementation explains that version;
external sources and host observations were not revalidated in the 2026-11-09
documentation audit. Do not assume identical internals in every supported OBS build.

## Why this chain

Use one verified denoiser, then a peak limiter, on microphone audio only.
Computer audio bypasses both. Prefer RNNoise; fall back to Speex at -15 dB,
a deliberately mild suppression choice. If unavailable, keep the microphone
without suppression and report a warning. **Clean microphone** bypasses both
filters when disabled. Current selection, settings, fallback and ownership live in
[Engine._microphone_noise_backend / _microphone_filters](../src/untangle/engine.py)
and [test_audio.py](../tests/test_audio.py), not in a generic filter-ID assumption.
OBS can omit the method selector in single-backend builds; source defaults and
compiled properties must establish support.

RNNoise has no OBS 27 strength control; `suppress_level` applies only to Speex.
Never stack denoisers. The limiter's -3 dB threshold leaves headroom; its 60 ms
release uses the OBS default. This controls occasional peaks without compressing
normal speech. We omit gates, expanders, a separate compressor and automatic gain
because no measured need justified them. Gates can cut quiet beginnings/endings;
compression/makeup gain can raise residual room noise. The limiter does not make
quiet speech louder. See [suppression implementation](https://github.com/obsproject/obs-studio/blob/27.2.3/plugins/obs-filters/noise-suppress-filter.c)
and [limiter guidance](https://obsproject.com/kb/limiter-filter).

## Ordering and timing

OBS 27 inserts filters at the front and executes audio backward through the list.
Adding suppression first and limiter second runs suppression before limiting.
The parent owns attached filters after local references are released.
See [OBS source/filter execution](https://github.com/obsproject/obs-studio/blob/27.2.3/libobs/obs-source.c).

The denoiser buffers 10 ms blocks and adjusts timestamps. Untangle adds no second
fixed sync correction. RNNoise at the existing 48 kHz needs no extra rate conversion;
this says nothing about total device/buffering/encoding latency. The limiter has
no lookahead or configurable attack. Its OBS 27 attack is effectively 1 microsecond,
with negligible ordinary sample-peak overshoot at 48 kHz. It cannot guarantee
encoded true peaks, repair clipping already at the input, or protect the summed
microphone/computer mix. See [limiter implementation](https://github.com/obsproject/obs-studio/blob/27.2.3/plugins/obs-filters/limiter-filter.c)
and [source mixing](https://github.com/obsproject/obs-studio/blob/27.2.3/libobs/obs-audio.c).

## Limits and evidence

Suppression can reduce mild fan noise, not guarantee removal of competing sounds,
reverberation or every keyboard impact. RNNoise favors speech and can alter wanted
vocal detail; disable Clean microphone when that tradeoff is undesirable.
This is not acoustic echo cancellation: there is no playback reference.
The chain changes no global PipeWire/PulseAudio configuration and requires no
model downloads or added runtime dependencies. See [OBS suppression guidance](https://obsproject.com/kb/noise-suppression-filter).

The original read-only ELF inspection found RNNoise functions/model bundled in
`/usr/lib/x86_64-linux-gnu/obs-plugins/obs-filters.so`, without a separate librnnoise
in `ldd`. Static bundling is allowed by [OBS build rules](https://github.com/obsproject/obs-studio/blob/27.2.3/plugins/obs-filters/CMakeLists.txt).
That historical host finding does not establish another machine's backend.

Run project checks only with `./scripts/test.sh`. The optional installed-backend
check in [test_audio.py](../tests/test_audio.py) processes twenty silent 480-sample
frames directly through RNNoise, without OBS startup or devices. Silent allocation/
processing does not establish speech quality, noise reduction, CPU cost, latency
or audible sync. No live capture/listening was used for this processing research;
see [separate hardware evidence and authorization boundaries](testing.md).
