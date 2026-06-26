import os

project = "readcon-core"
copyright = "2025--present, LODE developers"
author = "LODE developers"
release = "0.13.1"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinxcontrib.bibtex",
]

bibtex_bibfiles = ["references.bib"]
bibtex_default_style = "alpha"
bibtex_reference_style = "author_year"

templates_path = ["_templates"]
exclude_patterns = [
    "crates/readcon_core/main.rst",
]

html_theme = "shibuya"
html_static_path = ["_static"]
html_favicon = "_static/favicon.svg"
html_title = "readcon-core documentation"

html_theme_options = {
    "github_url": "https://github.com/lode-org/readcon-core",
    "light_logo": "_static/logo-light.svg",
    "dark_logo": "_static/logo-dark.svg",
    "accent_color": "indigo",
}


def setup(app):
    app.add_css_file("custom.css")


intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
