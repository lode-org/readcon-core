import os

project = "readcon-core"
copyright = "2025--present, LODE developers"
author = "LODE developers"
release = "0.13.1"

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
    "crates/readcon_core/main.rst",
]

myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
myst_fence_as_directive = ["mermaid"]

# Pre-generated crate RST under docs/source/crates/ (no sphinxcontrib-rust in CI)
html_theme = "shibuya"
html_static_path = ["_static"]
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
    "light_logo": "_static/logo-light.svg",
    "dark_logo": "_static/logo-dark.svg",
    "nav_links": [
        {"title": "Start", "url": "getting-started"},
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
                    "summary": "Corpus architecture, Select predicates, C/Python/Fortran APIs",
                },
            ],
        },
        {"title": "Spec", "url": "spec"},
        {"title": "Benchmarks", "url": "benchmarks"},
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
}


def setup(app):
    app.add_css_file("custom.css")
