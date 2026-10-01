"""specguard — detect breaking changes between OpenAPI specifications."""

__version__ = "0.1.0"

from .diff import Change, diff_specs

__all__ = ["Change", "diff_specs", "__version__"]
