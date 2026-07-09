import os

project = "readcon-core"
copyright = "2025--present, LODE developers"
author = "LODE developers"
release = "0.14.0"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.graphviz",
    "sphinxcontrib.bibtex",
    "sphinx_copybutton",
    "sphinx_design",
    "myst_parser",
    "sphinxcontrib.mermaid",
]

bibtex_bibfiles = ["references.bib"]
bibtex_default_style = "alpha"
bibtex_reference_style = "author_year"

templates_path = ["_templates"]
exclude_patterns = [
    # Pre-generated rust:* directive pages need sphinxcontrib-rust, which CI
    # does not install; the Rust API link points at docs.rs instead.
    "crates/**",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
myst_fence_as_directive = ["mermaid"]

# Mermaid nodes on their own light plate (matches the static SVG figures);
# WCAG AA in both page themes instead of theme-recolored boxes with dark text.
mermaid_init_js = """
mermaid.initialize({
  startOnLoad: true,
  theme: "base",
  themeVariables: {
    fontFamily: "Atkinson Hyperlegible, system-ui, sans-serif",
    fontSize: "14px",
    primaryColor: "#EEF2FF",
    primaryTextColor: "#1E1B4B",
    primaryBorderColor: "#6366F1",
    secondaryColor: "#E0E7FF",
    secondaryTextColor: "#1E1B4B",
    tertiaryColor: "#F8FAFC",
    tertiaryTextColor: "#1E1B4B",
    lineColor: "#64748B",
    textColor: "#1E1B4B",
    clusterBkg: "#F8FAFC",
    clusterBorder: "#94A3B8",
    edgeLabelBackground: "#F8FAFC",
    titleColor: "#1E1B4B"
  }
});
"""

# Pre-generated crate RST under docs/source/crates/ (no sphinxcontrib-rust in CI)
html_theme = "shibuya"
html_static_path = ["_static"]
# Serve the metadata JSON Schema at its $id URL (…/schema/con-metadata.schema.json)
html_extra_path = ["_extra"]
html_favicon = "_static/favicon.svg"
html_title = "readcon-core documentation"
html_baseurl = "https://lode-org.github.io/readcon-core/"

# Edit-this-page + repo-stats sidebars (Shibuya / rgpot / rgpycrumbs parity)
html_context = {
    "source_type": "github",
    "source_user": "lode-org",
    "source_repo": "readcon-core",
    "source_version": "main",
    "source_docs_path": "/docs/source/",
}

html_sidebars = {
    "**": [
        "sidebars/localtoc.html",
        "sidebars/repo-stats.html",
        "sidebars/edit-this-page.html",
    ],
}

html_theme_options = {
    "github_url": "https://github.com/lode-org/readcon-core",
    "accent_color": "indigo",
    "dark_code": True,
    "globaltoc_expand_depth": 1,
    # Compact mark + wordmark for the nav (hero uses HTML brand row + mark.svg).
    "light_logo": "_static/logo-nav-light.svg",
    "dark_logo": "_static/logo-nav-dark.svg",
    "nav_links": [
        {"title": "Start", "url": "getting-started"},
        {
            "title": "Learn",
            "children": [
                {
                    "title": "Tutorial — first CON checkpoint",
                    "url": "tutorial",
                    "summary": "One Good Tutorial: read, inspect, write, build",
                },
                {
                    "title": "How-to — migrate onto CON",
                    "url": "migrate",
                    "summary": "API, convert CLI, readcon-db, plotting path",
                },
                {
                    "title": "How-to — CON I/O by language",
                    "url": "howto",
                    "summary": "Task recipes for every binding",
                },
                {
                    "title": "Tutorial — XYZ/PDB/GRO → CON",
                    "url": "chemfiles-tutorial",
                    "summary": "Convert foreign formats into CON",
                },
            ],
        },
        {
            "title": "Convert",
            "children": [
                {
                    "title": "Tutorial — XYZ/PDB/GRO → CON",
                    "url": "chemfiles-tutorial",
                    "summary": "End-to-end format conversion",
                },
                {
                    "title": "Executable conversion notebook",
                    "url": "chemfiles-notebook",
                    "summary": "Org Babel: scripts/run-chemfiles-notebook.sh",
                },
                {
                    "title": "How-to recipes",
                    "url": "chemfiles-howto",
                    "summary": "Batch convert, C API, install choices",
                },
                {
                    "title": "Explain — why conversion is optional",
                    "url": "chemfiles-explain",
                    "summary": "Bonds, indices, two install flavours",
                },
                {
                    "title": "Reference",
                    "url": "chemfiles-reference",
                    "summary": "APIs, grammar, install matrix",
                },
            ],
        },
        {
            "title": "Ecosystem",
            "children": [
                {
                    "title": "readcon-db (campaign store)",
                    "url": "https://github.com/lode-org/readcon-db",
                    "summary": "LMDB corpora: energy/section indexes, xxHash3 dedup, multi-reader",
                },
                {
                    "title": "readcon-db docs",
                    "url": "https://lode-org.github.io/readcon-db/",
                    "summary": "Hosted package docs: corpus architecture, Select, C/Python/Fortran",
                },
                {
                    "title": "readcon-db Rust API",
                    "url": "https://docs.rs/readcon-db",
                    "summary": "docs.rs crate API for the campaign store",
                },
                {
                    "title": "eOn",
                    "url": "https://eondocs.org",
                    "summary": "Saddle-point search on PESs",
                },
                {
                    "title": "rgpot",
                    "url": "https://omnipotentrpc.github.io/rgpot/",
                    "summary": "Potential evaluation toolkit",
                },
                {
                    "title": "chemparseplot",
                    "url": "https://chemparseplot.rgoswami.me",
                    "summary": "Parsing and plotting for computational chemistry",
                },
                {
                    "title": "rgpycrumbs",
                    "url": "https://rgpycrumbs.rgoswami.me",
                    "summary": "CLI helpers for LODE / eOn workflows",
                },
                {
                    "title": "pychum",
                    "url": "https://github.com/HaoZeke/pychum",
                    "summary": "ORCA / NWChem input generation",
                },
                {
                    "title": "LODE org",
                    "url": "https://github.com/lode-org",
                    "summary": "Long-timescale dynamics ecosystem",
                },
            ],
        },
        {"title": "Spec", "url": "spec"},
        {"title": "Benchmarks", "url": "benchmarks"},
        {
            "title": "Rust API",
            "url": "https://docs.rs/readcon-core",
            "summary": "docs.rs crate reference (includes index_proj)",
        },
        {"title": "GitHub", "url": "https://github.com/lode-org/readcon-core"},
    ],
}

copybutton_prompt_text = r">>> |\.\.\. |\$ |In \[\d*\]: | {2,5}\.\.\.: | {5,8}: "
copybutton_prompt_is_regexp = True
# Do not copy line numbers / prompts; keep blocks paste-friendly
copybutton_exclude = ".linenos, .gp, .go"
copybutton_line_continuation_character = "\\"
copybutton_here_doc_delimiter = "EOF"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    # Hosted objects.inv may be absent in offline CI; explicit URL still documents the peer.
    "readcon-db": ("https://lode-org.github.io/readcon-db/", None),
}


def setup(app):
    app.add_css_file("custom.css")
