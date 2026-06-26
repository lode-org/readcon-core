# readcon-core branding

Original mark for **readcon-core** (CON / convel I/O for LODE and eOn), *not*
derived from rsx-rs RAD-seq artwork.

## Concept

- **Document card** — the on-disk CON frame (header band + body).
- **Header strip** — fixed preamble; small gold/indigo glints evoke the JSON
  metadata line (spec v2).
- **Vertical type-group columns** — atoms are grouped by species in CON
  layout (unlike RAD marker stream logos).
- **Gold dots** — `atom_id` identity preserved through type-grouping.
- **Double chevron** — multi-format ingress (XYZ/PDB/GRO/… via chemfiles)
  funneling into one CON representation.
- **Palette** — indigo / violet LODE-science (`#312E81`, `#4F46E5`) + amber
  accent (`#FBBF24`), distinct from rsx teal/orange barcode marks.

## Files

| File | Use |
|------|-----|
| `readcon-logo-light.svg` | Docs header (light), READMEs |
| `readcon-logo-dark.svg` | Docs header (dark) |
| `readcon-icon.svg` | Favicon / avatar (square) |
| `docs/source/_static/logo-*.svg` | Sphinx / shibuya copies |

Sphinx: `html_theme_options` `light_logo` / `dark_logo`, `html_favicon`.
