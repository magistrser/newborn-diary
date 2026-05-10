from .router import router as v1_router
from . import admin_import, ask, events  # noqa: F401 — registers routes on v1_router

__all__ = ['v1_router']
