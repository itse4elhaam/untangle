# Untangle

A continuous mint ribbon turns a loose knot into an open U. The knot sits on the left shoulder so the U stays legible at small sizes. A small coral dot above the right endpoint signals recording. The dark ink tile gives the ribbon a consistent background.

## Files

- `untangle-mark.svg`: 512 × 512 app icon. Rounded square tile, editable ribbon path and recording dot.
- `untangle-wordmark.svg`: 760 × 176 horizontal lockup with transparent background. Use on light surfaces.
- `untangle-banner.svg`: 1280 × 480 README banner with a dark background.

## Colors

| Color | Hex | Use |
| --- | --- | --- |
| Ink | `#13272D` | Tile, banner, wordmark lettering |
| Teal | `#52C9B3` | Ribbon gradient start |
| Mint | `#79E6C5` | Ribbon gradient middle, at 58% |
| Pale mint | `#A6F5D7` | Ribbon gradient end, recorder label |
| Coral | `#F28F83` | Recording dot |
| Chalk | `#F2F8F5` | Banner lettering |

## Editing and use

SVGs contain native paths, shapes, gradients and live text. No embedded raster images or external assets. The ribbon is one continuous path with a short overpass drawn over an ink separation to make the crossing readable.

Wordmark type uses `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`, weight 600. The installed system sans will determine exact letter shapes. Text remains editable. Convert text to outlines in your vector editor when exact cross-platform letter shapes are needed.

Use the mark at 32 px or larger. Keep at least one ribbon width of space around the tile. Preserve the ink background beneath the knot, including its overpass. For a single-color adaptation, replace all ribbon gradient stops with mint `#79E6C5`.

## Preview verification

Rendered with the installed librsvg and Cairo libraries. Visually inspected the combined `untangle-preview.png`, including the app icon rendered directly at 32 × 32 px. `render-previews.py` reproduces the PNG previews without installing packages.
