# Untangle Clearline

Clearline uses neutral surfaces, slate text and indigo actions. Dark mode uses charcoal surfaces and lighter indigo. The orange logo remains distinct from the interface action color. Current palettes, typography, dimensions and Qt selectors belong in [theme.py](../src/untangle/theme.py), not a second token table here.

## Logo constraints

The mark is a pair of offset focus brackets joined by a straight line. White strokes sit inside an opaque orange tile so the icon keeps its shape on light and dark desktop menus. Keep the brackets open and the center line horizontal. Do not animate or pulse the logo.

Use [untangle-mark.svg](../assets/untangle-mark.svg) as the editable master. Keep at least four viewBox units of clear space outside the tile in lockups. Small exports must preserve the whole tile and open brackets. Do not crop into it or substitute transparent white strokes alone.

The [light wordmark](../assets/untangle-wordmark.svg) and [dark wordmark](../assets/untangle-wordmark-dark.svg) contain outlined Inter lettering and render without installed fonts. The [banner](../assets/untangle-banner.svg) carries "One clear take." Root [assets](../assets/) also contains raster exports and theme-specific control indicators; keep assets available beside the package in installed layouts.

## Interface constraints

Use the shared theme on the Qt UI thread and let the caller persist preferences. Avoid per-widget color overrides. Warnings and errors need explicit text as well as color. Microphone signal indicates live telemetry, not proof that saved audio is usable.

Keep essential source and device controls visible in the left setup column, with one divider. Put secondary appearance and output choices in Settings and the preview on the right. Recording actions belong in the bottom bar, with Recordings and Sharing at the left. [app.py](../src/untangle/app.py) owns placement and control visibility; the theme owns styling.

Focus must remain visible without changing control geometry. Preserve readable text, distinguishable editable outlines and disabled selection marks. Exact styles and contrast assertions are maintained with the theme and its tests rather than copied here.

## Fonts and verification

Bundle unmodified Inter and retain Manrope for compatibility. Register fonts with Qt; do not install desktop fonts. Both families use SIL Open Font License 1.1. Keep notices beside the TTFs. [Font provenance and hashes](../assets/fonts/README.md) identify their sources.

The original Clearline work inspected assets at 16, 24 and 48 px and checked offscreen controls, contrast, focus geometry and microphone-meter reading preservation. Those historical checks covered theme and assets without instantiating the production Window. They do not establish current full-layout, OBS-preview, hardware, recording or playback behavior. Use the [safe verification procedure](testing.md) for repository checks; live verification requires separate authorization.
