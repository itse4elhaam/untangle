# Untangle Companion

Companion is Untangle's blue identity. Two offset white speech tiles share an edge inside a blue rounded square. The lower tile has an open corner. Use the same mark in the recorder, library, tray and desktop launcher.

The tagline is "Ready when you have something to show."

## Assets

- `assets/untangle-mark.svg`: 512 × 512 editable vector icon. It remains legible at 32 px.
- `assets/untangle-icon.png`: 512 × 512 raster export of the mark.
- `assets/untangle-wordmark.svg`: 760 × 176 transparent horizontal lockup for light surfaces.
- `assets/untangle-banner.svg`: 1280 × 480 light banner with the tagline.

The mark uses native SVG shapes. Lettering in the wordmark and banner is outlined from bundled Manrope Bold and Inter Regular, so rendering does not depend on installed fonts. Keep at least one white stroke width of clear space around the blue tile. Preserve the open corner and the white strokes. The mark stays blue in both app themes.

The SVGs and PNG were rendered with installed librsvg and Cairo libraries. The 32 px mark, wordmark and banner were inspected independently of the app.

## Color

| Token | Companion light | Companion dark |
| --- | --- | --- |
| Canvas | `#EDF3FC` | `#101C2D` |
| Panel | `#FFFFFF` | `#192A40` |
| Text | `#1B304F` | `#EAF1FC` |
| Muted | `#50617A` | `#B0C1D9` |
| Action | `#2454B8` | `#A6C5FF` |
| On action | `#FFFFFF` | `#102A50` |
| Selection | `#DFE9FF` | `#29476E` |
| Border | `#B7C8E2` | `#526B8B` |
| Warning ink / background | `#754500` / `#FFF0C2` | `#FFD78B` / `#483618` |
| Error ink / background | `#A02528` / `#FDECEE` | `#FFB3BA` / `#4A2634` |
| Microphone signal | `#236345` | `#91D5B1` |

Warnings and errors need explicit text as well as color. A microphone signal color reports telemetry, not a saved-file or speech-quality check. The focus color matches the action color and remains visible on panels and selected rows.

## Type and licenses

The app loads bundled Inter for controls and Manrope for headings with Qt's application-font API. It does not install fonts on the desktop. Controls use 14 px, ordinary labels 15 px, metadata 13 px, page headings 26 px, and compact sheet/review headings 18 px. Use compact spacing to preserve room for the preview and the 304 px preparation sidebar.

Both families use SIL Open Font License 1.1. Full copyright notices and licenses ship beside the unmodified TTFs in `assets/fonts/Inter-OFL.txt` and `assets/fonts/Manrope-OFL.txt`.

Inter Regular, Medium, SemiBold and Bold come from the official [Inter 4.1 release](https://github.com/rsms/inter/releases/tag/v4.1), under `extras/ttf/` in the release archive. Manrope Regular, Medium, SemiBold and Bold come from the official [Manrope repository](https://github.com/googlefonts/manrope/tree/master/fonts/ttf). File hashes and source paths are recorded in `assets/fonts/README.md`.

The research-cache variable TTFs were verified byte for byte against Google's official Fonts repository. In the installed Qt version, stylesheet weight requests left those variable fonts at their default weight. Production therefore bundles official static TTFs, without conversion or subsetting, so 400, 500, 600 and 700 resolve to the correct faces.

## Shared Qt API

`src/untangle/theme.py` owns the colors and widget styling. Call `apply_theme(application, 'light')` after creating the QApplication. Call it again with `'dark'` when the user changes the theme. The caller owns preference persistence.

- `THEMES` contains the light and dark token dictionaries.
- `tokens(name='light')` returns a copy. Unknown names fall back to light.
- `stylesheet(name='light')` returns the full application stylesheet.
- `load_fonts(application)` registers bundled fonts once and sets the application font to 14 px Inter.
- `apply_theme(application, name='light')` loads fonts, sets the `untangleTheme` application property, applies the QPalette and stylesheet, and refreshes existing MicrophoneMeter widgets without resetting their readings.

Repeated `apply_theme` calls with the same theme property and identical stylesheet return immediately. New widgets inherit the current style, and new meters read the current theme themselves. If another caller replaces the stylesheet, `apply_theme` restores it even when the theme property already matches.

Call these functions on the Qt UI thread. Assets resolve from `theme.py` through the repository or installed package root, never the working directory. Keep `assets/fonts` alongside the other installed assets.

The stylesheet preserves `title`, `eyebrow`, `muted`, `section`, `panel`, `sidebar`, `record`, `playRecording`, `footerNavigation` and `quiet`. It also covers `setupSection`, `setupHeading`, `setupDetails`, `summaryValue`, `audioCheck`, `checkTitle`, `checkStatus`, `libraryBrowser`, `libraryReview`, `libraryStage`, `libraryPoster`, `libraryPlaceholder`, `librarySelectedTitle`, `libraryMetadata`, `libraryMessage`, `libraryCount`, `recordingFiles`, `librarySplitter` and `deleteRecording`.

Use `warning`, `error`, `success` or `recording` as a QLabel object name or its `status` property for semantic feedback. When changing a dynamic `status` property after display, repolish the label or reapply the stylesheet so Qt updates the selector. Avoid per-widget color stylesheets, which override the application theme. Transparent child widgets inherit their containing surface; the stylesheet paints named cards, dialogs and list/input surfaces rather than every QWidget.

The `recordingFiles` list gets 112 × 64 icons and compact item padding. Its owner sets 96 px row size hints and supplies thumbnails. The theme does not open media, capture devices or playback resources.
