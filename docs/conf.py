"""Sphinx documentation build configuration."""

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sphinx.application import Sphinx

# docs/conf.py -> repo root -> src/. Both packages (tricca_autopipette,
# autopipette_kiosk) live directly under src/, so one entry covers both.
sys.path.insert(0, os.path.abspath("../src"))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Tricca AutoPipette"
copyright = "2024-2026, James Cook"
author = "James Cook"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.duration",
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.viewcode",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- autosummary ---------------------------------------------------------
# Generate the docs/generated/ stub pages from the live package tree on
# every build (docs/api.rst's `:recursive:` autosummary directive drives
# this) rather than hand-listing modules -- the hand-maintained list is
# what went stale before (#21).
autosummary_generate = True

# -- autodoc ---------------------------------------------------------------
# The generated stub pages only write a bare `automodule::` (no explicit
# `:members:`) -- these defaults apply to every autodoc directive the build
# processes, including the autoclass/automethod entries automodule expands
# into, so a module page actually renders its classes' methods rather than
# just linking their names.
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    # Every dunder is a candidate; autodoc-skip-member below (registered in
    # setup()) prunes back to only the ones with a real docstring of their
    # own, e.g. Coordinate.__eq__, Plate.__iter__ -- not __weakref__ or a
    # plain inherited __hash__.
    "special-members": True,
}

# -- napoleon (Google-style docstring parsing) ----------------------------
# This codebase leans on Note/Warning sections for safety-critical caveats
# (tip disposal, the homed interlock, the `trigger` stub); rendering them
# as admonitions makes them visually distinct from surrounding prose
# instead of blending in as plain rubric text.
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_examples = True

# Both default False, which would silently drop real content: __init__
# docstrings (e.g. AutoPipette.__init__'s own Args/Example) and dunder
# methods with substantive docstrings (e.g. Coordinate.__eq__'s comparison
# semantics, Plate.__iter__'s traversal-order note) never render otherwise.
napoleon_include_init_with_doc = True
napoleon_include_special_with_doc = True

# Render a docstring's Attributes: section as `:ivar:` field-list prose
# rather than napoleon's default `.. attribute::` directives. The default
# registers each attribute as its own cross-reference target -- which
# collides ("duplicate object description") with the *real* `.. attribute::`
# entry autodoc's `:members:` (above) already generates for the same name
# from the actual dataclass/pydantic field, since this codebase's
# dataclasses (e.g. `commands/tap_cmd_parsers.py`'s `*Args`) always carry
# both a real type-annotated field and a docstring Attributes: entry
# describing it.
napoleon_use_ivar = True

# -- intersphinx -----------------------------------------------------------
# Stdlib only for now. Third-party mappings (aiohttp, cmd2) are a possible
# future addition, not done here -- they add build-time network fetches and
# can break the build if a project moves its inventory.
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]


def _skip_undocumented_dunder(
    _app: "Sphinx", _what: str, name: str, obj: object, skip: bool, _options: object
) -> bool:
    """Keep a dunder member only if it carries its own docstring.

    ``special-members: True`` (above) makes every dunder a candidate, which
    would otherwise flood each class page with boilerplate (``__weakref__``,
    a plain inherited ``__hash__``, ...). Comparing against ``object``'s own
    docstring for the same name catches both "never overridden" and
    "overridden but left undocumented" without a hand-maintained list of
    which dunders happen to be documented today -- new ones (e.g. a future
    ``__contains__``) pick this up automatically as soon as they get a real
    docstring.

    Args:
        name: The member's attribute name, e.g. ``"__eq__"``.
        obj: The member object itself, supplied by autodoc.
        skip: autodoc's own default skip/include decision for this member.

    Returns:
        True to skip the member, False to include it, or `skip` unchanged
        for non-dunder names (autodoc's default decision stands).
    """
    if not (name.startswith("__") and name.endswith("__")):
        return skip
    doc = getattr(obj, "__doc__", None)
    if not doc:
        return True
    base_doc = getattr(getattr(object, name, None), "__doc__", None)
    return doc == base_doc or skip


def setup(app: "Sphinx") -> None:
    """Register the dunder-filtering hook with the Sphinx build.

    Args:
        app: The Sphinx application object, supplied by Sphinx itself.
    """
    # Sphinx's own stub types `callback` as a bare `Callable`, so its
    # return type comes through as partially Unknown regardless of how
    # precisely `_skip_undocumented_dunder` itself is typed -- not
    # something a caller-side annotation can fix.
    app.connect(  # pyright: ignore[reportUnknownMemberType]
        "autodoc-skip-member", _skip_undocumented_dunder
    )
