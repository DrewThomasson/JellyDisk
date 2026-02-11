"""
JellyDisc - Automated DVD Authoring Suite

A cross-platform desktop application that connects to a Jellyfin server,
downloads TV show seasons, and authors commercial-grade DVD ISOs with
interactive menus, metadata, and subtitles.
"""

__version__ = "0.1.0"
__author__ = "JellyDisc Contributors"

from .jellyfin_client import JellyfinClient

__all__ = ["JellyfinClient"]
