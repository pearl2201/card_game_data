"""Storefront adapters."""

from .appstore import AppStoreSource
from .play import PlaySource
from .steam import SteamSource

__all__ = ["AppStoreSource", "PlaySource", "SteamSource"]
