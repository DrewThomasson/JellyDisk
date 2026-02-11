"""
JellyDisc - Automated DVD Authoring Suite

A cross-platform desktop application that connects to a Jellyfin server,
downloads TV show seasons, and authors commercial-grade DVD ISOs with
interactive menus, metadata, and subtitles.
"""

__version__ = "0.1.0"
__author__ = "JellyDisc Contributors"

from .jellyfin_client import JellyfinClient
from .transcoder import (
    Transcoder,
    TranscodeJob,
    VideoSettings,
    AudioSettings,
    VideoStandard,
    DiscPlan,
    check_dependencies,
)
from .menu_builder import (
    MenuBuilder,
    MenuConfig,
    MenuStyle,
    EpisodeThumbnail,
    check_menu_dependencies,
)
from .burner import (
    Burner,
    DiscInfo,
    check_burner_dependencies,
)

__all__ = [
    # Jellyfin Client
    "JellyfinClient",
    # Transcoder
    "Transcoder",
    "TranscodeJob",
    "VideoSettings",
    "AudioSettings",
    "VideoStandard",
    "DiscPlan",
    "check_dependencies",
    # Menu Builder
    "MenuBuilder",
    "MenuConfig",
    "MenuStyle",
    "EpisodeThumbnail",
    "check_menu_dependencies",
    # Burner
    "Burner",
    "DiscInfo",
    "check_burner_dependencies",
]
