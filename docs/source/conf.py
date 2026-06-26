import os
import shutil

project = "readcon-core"
copyright = "2025--present, LODE developers"
author = "LODE developers"
release = "0.13.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinxcontrib_rust",
    "sphinx_rustdoc_postprocess",
    "sphinxcontrib.bibtex",
]

bibtex_bibfiles = ["references.bib"]
bibtex_default_style = "alpha"
bibtex_reference_style = "author_year"

templates_path = ["_templates"]
exclude_patterns = [
    "crates/readcon_core/main.rst",
]

rust_crates = {
    "readcon_core": os.path.abspath("../../"),
}
rust_doc_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crates")
rust_rustdoc_fmt = "rst"
# Prefer committed / previously generated crate RST so CI does not require
# `cargo install sphinx-rustdocgen` on every docs job (rsx-rs still uses always
# when the tool is installed; we fall back for reliability).
rust_generate_mode = "always" if shutil.which("sphinx-rustdocgen") else "never"

html_theme = "shibuya"
html_static_path = ["_static"]
html_favicon = "_static/favicon.svg"

html_theme_options = {
    "github_url": "https://github.com/lode-org/readcon-core",
    "light_logo": "_static/logo-light.svg",
    "dark_logo": "_static/logo-dark.svg",
}


def setup(app):
    app.add_css_file("custom.css")


intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
