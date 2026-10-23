# Untangle Clearline

Clearline uses a neutral canvas, slate text, white panels and a burnt-orange action color. Dark mode uses charcoal surfaces and a lighter warm orange. The product name remains Untangle.

The mark is a pair of offset focus brackets joined by a straight line. White strokes sit inside an opaque orange tile so the icon keeps its shape on light and dark desktop menus. The mark stays orange in both themes. Keep the brackets open and the center line horizontal. Do not animate or pulse the logo.

## Assets

- `assets/untangle-mark.svg` is the editable master, with a 32-unit viewBox and 512 × 512 nominal size. The installer can rasterize this file directly.
- `assets/untangle-icon.png` is the 512 × 512 raster export. `untangle-icon-16.png`, `untangle-icon-24.png` and `untangle-icon-48.png` are direct renders of the same vector for small-icon inspection and reuse.
- `assets/untangle-wordmark.svg` is the transparent 760 × 176 lockup for light backgrounds. `assets/untangle-wordmark-dark.svg` has light lettering for dark backgrounds.
- `assets/untangle-banner.svg` is a 1280 × 480 neutral light banner with the line "One clear take."
- `assets/clearline-chevron-{light,dark}.svg`, `clearline-check-{light,dark}.svg` and `clearline-radio-{light,dark}.svg` supply Qt control indicators.

The wordmarks and banner contain outlined Inter lettering. They render without installed fonts. Keep at least four viewBox units of clear space outside the app tile when placing a lockup. Small PNG exports preserve the whole tile and its open brackets. Do not crop into it or replace it with transparent white strokes alone.

## Color

| Token | Light | Dark |
| --- | --- | --- |
| Canvas | `#F6F7F9` | `#191B1F` |
| Panel | `#FFFFFF` | `#23262B` |
| Text | `#202936` | `#F1F2F4` |
| Muted | `#586373` | `#B6BDC7` |
| Action and focus | `#C33C0A` | `#FF995F` |
| Action hover | `#A93208` | `#FFB080` |
| On action | `#FFFFFF` | `#281A12` |
| Selection | `#FFF0E8` | `#473026` |
| Divider border | `#D5DAE1` | `#41464F` |
| Control border | `#858E9A` | `#78818E` |
| Hover | `#ECEFF3` | `#30343B` |
| Disabled text | `#657080` | `#9DA5B0` |
| Disabled background | `#E9ECF0` | `#2D3138` |
| Warning ink / background | `#805000` / `#FFF1CF` | `#F6CE80` / `#42351E` |
| Error ink / background | `#B42332` / `#FFF0F1` | `#FFA6AE` / `#46262D` |
| Signal | `#24704B` | `#8CD4AB` |
| Recording | `#B42332` | `#FFA6AE` |
| Meter track | `#D5DAE1` | `#41464F` |

Divider borders separate surfaces. The stronger `control_border` token identifies editable controls. Text, secondary text, action labels and selected mode labels meet 4.5:1 contrast on their intended backgrounds. Control outlines meet 3:1 against both panel and canvas. Focus uses dashed borders without changing border width or control geometry. Primary actions use the contrasting action-label color for their focus border.

Selected modes use orange text, heavier lettering, an orange outline and a tinted background. Checkboxes use explicit SVG checkmarks; radio buttons use an explicit center dot. Disabled selections retain their mark on a muted fill. Combo boxes have explicit theme-aware chevrons instead of platform-dependent arrows.

Warnings and errors require explicit text as well as color. A microphone signal reports live telemetry; it does not establish that a saved file contains usable audio.

## Typography and layout

Use bundled Inter throughout the app. Controls and ordinary labels use 14 px, secondary text uses at least 13 px, page titles use 24 px semibold, and review/check headings use 18 px. Buttons use semibold; checked modes use bold. Standard buttons and inputs have a minimum 36 px total height. Mode buttons named `mode` or carrying `mode="true"` and the `record` action have a minimum 42 px total height. Checkboxes and radio buttons have at least a 36 px content area.

Use a 276 px setup allocation on the left, including padding, with one vertical divider. Keep essential source and device controls visible. Appearance and output details belong in one secondary disclosure. The right side holds the large preview and a fixed lower action row. Recordings and Sharing stay at the lower left. Layout ownership remains with `app.py`; the theme does not position widgets or decide which controls are visible.

The font loader registers the existing unmodified bundled fonts through Qt and sets Inter as the app font. It does not install desktop fonts. Existing Manrope files remain available for compatibility; Clearline styles do not request Manrope.

Both bundled families use SIL Open Font License 1.1. Notices and licenses remain beside the unmodified TTFs in `assets/fonts/Inter-OFL.txt` and `assets/fonts/Manrope-OFL.txt`. Sources, file hashes and static-font details remain in `assets/fonts/README.md`. No fonts or licenses were changed for Clearline.

## Shared Qt API

`src/untangle/theme.py` owns colors, fonts and widget styling. Keep calls on the Qt UI thread. The caller owns preference persistence.

- `THEMES` contains light and dark token dictionaries. Existing meter and semantic keys remain available; `control_border` adds a stronger outline for inputs.
- `tokens(name='light')` returns a copy. Unknown names fall back to light.
- `stylesheet(name='light')` returns the application stylesheet, including absolute bundled vector paths resolved relative to `theme.py`.
- `load_fonts(application)` registers bundled fonts once and sets 14 px Inter.
- `apply_theme(application, name='light')` applies the palette and stylesheet, sets `untangleTheme`, and refreshes existing MicrophoneMeter widgets without resetting readings.

Repeated theme application returns immediately when both the theme property and stylesheet already match. If another caller replaces the stylesheet, applying the theme restores it. New widgets inherit the stylesheet; new meters read the current tokens. Keep root `assets` beside the package in installed layouts. Asset resolution never depends on the working directory.

The existing named selectors remain supported, including `title`, `eyebrow`, `muted`, `section`, `panel`, `sidebar`, `setupSection`, `setupHeading`, `setupDetails`, `summaryValue`, `record`, `playRecording`, `footerNavigation`, `quiet`, `audioCheck`, `checkTitle`, `checkStatus` and the library selectors. `setupColumn` supplies a plain left divider when used on the full setup container. Apply that divider to one container to avoid duplicate lines. The `recordingFiles` list retains 112 × 64 icons and compact item padding.

Use `warning`, `error`, `success` or `recording` as a QLabel object name or `status` property. Repolish a label after changing a dynamic status property. Avoid per-widget color stylesheets, which override the shared theme. Named panels, dialogs and controls supply backgrounds; ordinary child widgets stay transparent.

## Verification boundary

Clearline assets were rendered and inspected at 16, 24 and 48 px. Both themes were checked with an offscreen Qt control fixture, including checked modes, combo arrows, checkboxes, radio buttons, disabled selections and a synthetic microphone meter. Palette contrast, minimum input/action heights, stable focus geometry, token-copy/fallback behavior, repeated application and meter-reading preservation were checked without opening capture or playback resources.

These checks establish theme and asset behavior only. Full recorder/library layout, native OBS previews, hardware, recording and playback require the owning implementation's separate verification. No production Window was instantiated for this theme work.
