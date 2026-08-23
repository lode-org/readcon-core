# readcon-core branding

Family mark for **readcon** (the CON / convel spec and hourglass ABI).
Companion store: [readcon-db](https://github.com/lode-org/readcon-db) uses the
same frame, stacked.

## Concept

- **Frame** — one CON checkpoint: cell outline, gold header rule (line-2
  metadata), three species nodes.
- **Small sizes** — the frame glyph only (favicon, avatar, nav tile).
- **Hero headings** — HTML wordmark `read` + mono `con`. SVG lockups keep a
  single-face `readcon` so GitHub and README render without webfonts.
- **Palette** — indigo tile (`#1E1B4B`, `#C7D2FE`) + gold rule (`#C9A227`).

readcon-db keeps the same frame on a teal tile so the pair reads as one
object, two products.

## Files

| File | Use |
|------|-----|
| `readcon-icon.svg` | Favicon / avatar (square glyph) |
| `readcon-logo-light.svg` | Lockup for light README / docs |
| `readcon-logo-dark.svg` | Lockup for dark backgrounds |
| `docs/source/_static/mark.svg` | Docs hero tile |
| `docs/source/_static/logo-nav-*.svg` | Sphinx nav (glyph + word) |

Sphinx: `html_theme_options` `light_logo` / `dark_logo`, `html_favicon`.
Hero type lives in `docs/source/_static/custom.css` (`.rc-hero-name`).
