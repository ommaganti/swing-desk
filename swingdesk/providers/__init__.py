"""Provider layer: every external data need behind a swappable interface.

`registry.build_providers()` selects concrete providers from whatever API keys
are present in the environment and always guarantees a working zero-key path.
"""
from __future__ import annotations

from .demo_provider import build_demo_providers
from .registry import Providers, build_providers

__all__ = ["Providers", "build_providers", "build_demo_providers"]
