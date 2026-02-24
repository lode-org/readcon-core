project = "readcon-core"
copyright = "2025, LODE developers"
author = "LODE developers"
release = "0.3.2"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = []

html_theme = "shibuya"
html_static_path = ["_static"]

html_theme_options = {
    "github_url": "https://github.com/lode-org/readcon-core",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
