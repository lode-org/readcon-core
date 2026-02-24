import os

project = "readcon-core"
copyright = "2025--present, LODE developers"
author = "LODE developers"
release = "0.4.2"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinxcontrib_rust",
    "sphinx_rustdoc_postprocess",
]

templates_path = ["_templates"]
exclude_patterns = []

# -- sphinxcontrib-rust configuration ----------------------------------------
rust_crates = {
    "readcon_core": os.path.abspath("../../"),
}
rust_doc_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crates")
rust_rustdoc_fmt = "rst"
rust_generate_mode = "always"

# -- sphinx-rustdoc-postprocess configuration --------------------------------
# Toctree injection not needed; crates/readcon_core/lib is linked directly
# from the main toctree in index.rst.

# -- Options for HTML output -------------------------------------------------
html_theme = "shibuya"
html_static_path = ["_static"]

html_theme_options = {
    "github_url": "https://github.com/lode-org/readcon-core",
}

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}
