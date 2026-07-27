#!/usr/bin/env python3
"""
JellyDisc - Main Application

A cross-platform desktop application that connects to a Jellyfin server,
downloads TV show seasons, and authors commercial-grade DVD ISOs with
interactive menus, metadata, and subtitles.
"""

import logging
import os
import subprocess
import sys
import threading
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

def load_env_file():
    """Load local .env file variables into os.environ if it exists."""
    for base in [Path("."), Path(__file__).resolve().parent.parent]:
        env_path = base / ".env"
        if env_path.exists():
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            k, v = line.split("=", 1)
                            # Strip quotes if present
                            v = v.strip().strip("'\"")
                            os.environ[k.strip()] = v
            except Exception:
                pass

load_env_file()

try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
    from tkinter import filedialog, messagebox
    GUI_AVAILABLE = True
except ImportError as e:
    GUI_AVAILABLE = False
    GUI_ERROR = str(e)

from .jellyfin_client import (
    JellyfinClient, 
    JellyfinClientError, 
    AuthenticationError,
    JellyfinConnectionError,
    Series,
    Season,
    Episode
)
from .transcoder import (
    Transcoder,
    TranscodeJob,
    VideoSettings,
    VideoStandard,
    DiscPlan,
    check_dependencies as check_transcoder_deps
)
from .menu_builder import (
    MenuBuilder,
    MenuConfig,
    MenuStyle,
    EpisodeThumbnail,
    generate_trivia_questions,
)
from .burner import (
    Burner,
    check_burner_dependencies
)
from .art_generator import ArtGenerator
from .preview_renderer import DVDPreviewRenderer

logger = logging.getLogger(__name__)


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Sanitize a string for use as a filename.
    
    Args:
        name: Original filename
        max_length: Maximum length for the filename

    Returns:
        Safe filename string
    """
    # Keep only alphanumeric chars, spaces, dots, underscores, and hyphens
    safe = "".join(c for c in name if c.isalnum() or c in "._- ")
    # Replace multiple spaces with single space
    safe = " ".join(safe.split())
    # Truncate if needed
    return safe[:max_length].strip()


def select_preview_menu_audio(screen: str, assets: dict) -> Optional[Path]:
    """Return the authored audio source associated with a preview menu."""
    if screen.startswith("trivia:"):
        return assets.get("_trivia_audio_path")
    if screen == "main":
        return assets.get("_theme_path")
    return None


def ensure_default_trivia_audio(assets_dir: Path, log_callback=None) -> Optional[Path]:
    """Ensure the default chill lofi loop track is available for the trivia game."""
    packaged_path = Path(__file__).parent / "resources" / "trivia_bg.mp3"
    if packaged_path.exists():
        return packaged_path
    return None


def get_chapters_string(dur_seconds: float, original_chapters: list[float] = None) -> str:
    """
    Format chapter points as a comma-separated string for dvdauthor.
    """
    if original_chapters:
        time_strs = []
        for ch in original_chapters:
            if ch < dur_seconds:
                h = int(ch // 3600)
                m = int((ch % 3600) // 60)
                s = int(ch % 60)
                time_strs.append(f"{h:02d}:{m:02d}:{s:02d}")
        # Ensure "00:00:00" is at the start
        if "00:00:00" not in time_strs and "0:00:00" not in time_strs:
            time_strs.insert(0, "00:00:00")
        return ",".join(time_strs)
        
    # Fallback: generate chapters every 5 minutes (300 seconds)
    time_strs = ["00:00:00"]
    ch_interval = 300.0
    current_ch = ch_interval
    while current_ch < dur_seconds - 60.0:  # don't place a chapter in the last minute
        h = int(current_ch // 3600)
        m = int((current_ch % 3600) // 60)
        s = int(current_ch % 60)
        time_strs.append(f"{h:02d}:{m:02d}:{s:02d}")
        current_ch += ch_interval
    return ",".join(time_strs)


def parse_people_metadata(series, details):
    """
    Parse People metadata (Actors, Directors, Writers) and save onto the Series/Movie object.
    """
    people_list = details.get("People", [])
    actors = []
    directors = []
    writers = []
    people_details = []
    
    for person in people_list:
        name = person.get("Name")
        p_type = person.get("Type", "Unknown")
        role = person.get("Role")
        person_id = person.get("Id")
        image_tag = person.get("PrimaryImageTag")
        
        if p_type == "Actor":
            actors.append(f"{name} as {role}" if role else name)
        elif p_type == "Director":
            directors.append(name)
        elif p_type == "Writer":
            writers.append(name)
            
        people_details.append({
            "name": name,
            "type": p_type,
            "role": role,
            "id": person_id,
            "primary_image_tag": image_tag,
            "image_path": None
        })
        
    series.actors = actors[:15]  # Support up to 15 actors
    series.directors = directors
    series.writers = writers
    series.people_details = people_details[:30]  # Store top 30 people details


# Configure CustomTkinter (only if available)
if GUI_AVAILABLE:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    _BaseClass = ctk.CTk
else:
    _BaseClass = object


if GUI_AVAILABLE:
    class WorkspaceNavigator(ctk.CTkFrame):
        """Sidebar workspace navigation with a stable tab-like API."""

        PAGE_DETAILS = {
            "1  Connect": ("Connection", "Connect securely to your Jellyfin server"),
            "2  Library": ("Library", "Choose a movie or television season"),
            "3  Preview": ("Design & preview", "Review the package and test the DVD experience"),
            "4  Output": ("Build & output", "Create an ISO or burn the finished disc"),
        }

        def __init__(self, master):
            super().__init__(master, fg_color="transparent")
            self.pages = {}
            self.buttons = {}
            self.current = None
            self.grid_columnconfigure(1, weight=1)
            self.grid_rowconfigure(0, weight=1)

            sidebar = ctk.CTkFrame(self, width=210, corner_radius=0)
            sidebar.grid(row=0, column=0, sticky="nsew")
            sidebar.grid_propagate(False)
            logo_label = ctk.CTkLabel(sidebar, text="")
            logo_label.pack(anchor="w", padx=20, pady=(24, 3))
            logo_path = Path(__file__).resolve().parent.parent / "docs" / "jellydisk-logo.png"
            try:
                with Image.open(logo_path) as source:
                    logo = source.convert("RGB")
                    logo.thumbnail((166, 56), Image.Resampling.LANCZOS)
                self.logo_photo = ImageTk.PhotoImage(
                    logo, master=logo_label._label
                )
                logo_label._label.configure(image=self.logo_photo, text="")
            except Exception:
                logo_label.configure(
                    text="JellyDisk",
                    font=ctk.CTkFont(size=25, weight="bold"),
                )
            ctk.CTkLabel(
                sidebar,
                text="DVD authoring studio",
                font=ctk.CTkFont(size=12),
                text_color=("gray45", "gray65"),
            ).pack(anchor="w", padx=22, pady=(0, 28))
            self.nav_frame = ctk.CTkFrame(sidebar, fg_color="transparent")
            self.nav_frame.pack(fill="x", padx=10)
            ctk.CTkLabel(
                sidebar,
                text="PROJECT WORKFLOW",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=("gray50", "gray58"),
            ).place(x=22, rely=0.93, anchor="sw")

            workspace = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
            workspace.grid(row=0, column=1, sticky="nsew", padx=(20, 22), pady=(16, 0))
            self.page_title = ctk.CTkLabel(
                workspace, text="", font=ctk.CTkFont(size=27, weight="bold")
            )
            self.page_title.pack(anchor="w")
            self.page_subtitle = ctk.CTkLabel(
                workspace,
                text="",
                font=ctk.CTkFont(size=12),
                text_color=("gray45", "gray68"),
            )
            self.page_subtitle.pack(anchor="w", pady=(1, 12))
            self.page_host = ctk.CTkFrame(workspace, fg_color="transparent")
            self.page_host.pack(fill="both", expand=True)

        def add(self, name: str):
            page = ctk.CTkFrame(self.page_host, fg_color="transparent")
            self.pages[name] = page
            number, label = name.split("  ", 1)
            button = ctk.CTkButton(
                self.nav_frame,
                text=f"{number}    {label}",
                height=44,
                anchor="w",
                fg_color="transparent",
                hover_color=("gray82", "gray22"),
                command=lambda target=name: self.set(target),
            )
            button.pack(fill="x", pady=3)
            self.buttons[name] = button
            if self.current is None:
                self.set(name)
            return page

        def set(self, name: str):
            if name not in self.pages:
                return
            if self.current:
                self.pages[self.current].pack_forget()
                self.buttons[self.current].configure(fg_color="transparent")
            self.current = name
            self.pages[name].pack(fill="both", expand=True)
            self.buttons[name].configure(fg_color=("gray78", "gray25"))
            title, subtitle = self.PAGE_DETAILS.get(name, (name, ""))
            self.page_title.configure(text=title)
            self.page_subtitle.configure(text=subtitle)

        def get(self):
            return self.current


@dataclass
class AppConfig:
    """Application configuration."""
    # Working directories (resolve relative to the project package root)
    assets_dir: Path = Path(__file__).resolve().parent.parent / "assets"
    staging_dir: Path = Path(__file__).resolve().parent.parent / "staging"
    output_dir: Path = Path(__file__).resolve().parent.parent / "output"
    
    # Authoring settings
    video_standard: VideoStandard = VideoStandard.NTSC
    audio_language: str = "English"
    include_subtitles: bool = True
    include_trailer: bool = True
    menu_style: MenuStyle = MenuStyle.MODERN
    
    # Burn settings
    burn_speed: int = 4


class JellyDiscApp(_BaseClass):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.title("JellyDisk")
        self.geometry("1320x860")
        self.minsize(1080, 740)
        
        # Application state
        self.config = AppConfig()
        self.jellyfin_client: Optional[JellyfinClient] = None
        self.selected_series: Optional[Series] = None
        self.selected_season: Optional[Season] = None
        self.disc_plans: list[DiscPlan] = []
        
        # Ensure working directories exist
        self.config.assets_dir.mkdir(exist_ok=True)
        self.config.staging_dir.mkdir(exist_ok=True)
        self.config.output_dir.mkdir(exist_ok=True)
        
        # Create UI
        self._create_ui()
        
        # Check dependencies on startup
        self.after(100, self._check_dependencies)

    def destroy(self):
        """Release preview media processes before closing the application."""
        if hasattr(self, "menu_audio_process"):
            self._stop_menu_audio()
        super().destroy()
    
    def _create_ui(self):
        """Create the main UI layout."""
        # A project workspace replaces the old stack of conventional tabs.
        self.tabview = WorkspaceNavigator(self)
        self.tabview.pack(fill="both", expand=True)
        
        # Add tabs
        self.tab_connect = self.tabview.add("1  Connect")
        self.tab_library = self.tabview.add("2  Library")
        self.tab_config = self.tabview.add("3  Preview")
        self.tab_burn = self.tabview.add("4  Output")
        
        # Build each tab
        self._create_connect_tab()
        self._create_library_tab()
        self._create_config_tab()
        self._create_burn_tab()
        
        # Status bar
        self.status_frame = ctk.CTkFrame(self, height=30)
        self.status_frame.pack(fill="x", padx=(230, 22), pady=(4, 12))
        
        self.status_label = ctk.CTkLabel(
            self.status_frame, 
            text="Ready. Please connect to your Jellyfin server.",
            anchor="w"
        )
        self.status_label.pack(fill="x", padx=10, pady=5)
    
    def _create_connect_tab(self):
        """Create the Connect tab for Jellyfin login."""
        frame = ctk.CTkFrame(self.tab_connect)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Center content
        center_frame = ctk.CTkFrame(frame, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")
        
        logo_label = ctk.CTkLabel(center_frame, text="")
        logo_label.pack(pady=(0, 8))
        try:
            logo_path = Path(__file__).resolve().parent.parent / "docs" / "jellydisk-logo.png"
            with Image.open(logo_path) as source:
                logo = source.convert("RGB")
                logo.thumbnail((300, 100), Image.Resampling.LANCZOS)
            self.connect_logo_photo = ImageTk.PhotoImage(
                logo, master=logo_label._label
            )
            logo_label._label.configure(image=self.connect_logo_photo, text="")
        except Exception:
            logo_label.configure(
                text="JellyDisk", font=ctk.CTkFont(size=32, weight="bold")
            )
        
        subtitle = ctk.CTkLabel(
            center_frame,
            text="Connect to your Jellyfin server",
            font=ctk.CTkFont(size=14),
            text_color="gray"
        )
        subtitle.pack(pady=(0, 30))
        
        # Server URL
        url_label = ctk.CTkLabel(center_frame, text="Server URL:")
        url_label.pack(anchor="w")
        
        self.url_entry = ctk.CTkEntry(center_frame, width=400, placeholder_text="http://localhost:8096")
        self.url_entry.pack(pady=(5, 15))
        
        # Load from environment
        env_url = os.environ.get("JELLYFIN_URL", "")
        if env_url:
            self.url_entry.insert(0, env_url)
        
        # Username
        user_label = ctk.CTkLabel(center_frame, text="Username:")
        user_label.pack(anchor="w")
        
        self.user_entry = ctk.CTkEntry(center_frame, width=400, placeholder_text="admin")
        self.user_entry.pack(pady=(5, 15))
        
        env_user = os.environ.get("JELLYFIN_USER", "")
        if env_user:
            self.user_entry.insert(0, env_user)
        
        # Password
        pass_label = ctk.CTkLabel(center_frame, text="Password:")
        pass_label.pack(anchor="w")
        
        self.pass_entry = ctk.CTkEntry(center_frame, width=400, show="•", placeholder_text="password")
        self.pass_entry.pack(pady=(5, 20))
        
        env_pass = os.environ.get("JELLYFIN_PASS", "")
        if env_pass:
            self.pass_entry.insert(0, env_pass)
        
        # Connect button
        self.connect_btn = ctk.CTkButton(
            center_frame,
            text="Connect",
            width=200,
            height=40,
            command=self._on_connect
        )
        self.connect_btn.pack(pady=10)
        
        # Connection status
        self.connect_status = ctk.CTkLabel(
            center_frame,
            text="",
            font=ctk.CTkFont(size=12)
        )
        self.connect_status.pack(pady=10)
    
    def _create_library_tab(self):
        """Create the Library tab for browsing TV shows."""
        # Left panel - Show list
        left_frame = ctk.CTkFrame(self.tab_library)
        left_frame.pack(side="left", fill="both", expand=True, padx=(10, 5), pady=10)
        
        # Header
        header = ctk.CTkLabel(
            left_frame,
            text="TV Shows & Movies",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        header.pack(pady=(10, 5))
        
        # Search Bar
        self.search_var = ctk.StringVar(value="")
        self.search_entry = ctk.CTkEntry(
            left_frame,
            placeholder_text="Search library...",
            textvariable=self.search_var
        )
        self.search_entry.pack(fill="x", padx=10, pady=(0, 10))
        self.search_var.trace_add("write", self._on_search_changed)
        
        # Show scrollable frame for shows
        self.shows_frame = ctk.CTkScrollableFrame(left_frame)
        self.shows_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.show_widgets = []  # Store show buttons
        
        # Right panel - Season/Episode details
        right_frame = ctk.CTkFrame(self.tab_library)
        right_frame.pack(side="right", fill="both", expand=True, padx=(5, 10), pady=10)
        
        # Season selection
        self.season_label = ctk.CTkLabel(
            right_frame,
            text="Select a show",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        self.season_label.pack(pady=10)
        
        # Season dropdown
        self.season_var = ctk.StringVar(value="")
        self.season_dropdown = ctk.CTkComboBox(
            right_frame,
            values=[],
            variable=self.season_var,
            command=self._on_season_selected,
            width=300,
            state="disabled"
        )
        self.season_dropdown.pack(pady=10)
        
        # Episode list
        self.episodes_frame = ctk.CTkScrollableFrame(right_frame)
        self.episodes_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Select button
        self.select_season_btn = ctk.CTkButton(
            right_frame,
            text="Author This Season",
            command=self._on_author_season,
            state="disabled"
        )
        self.select_season_btn.pack(pady=10)
    
    def _create_config_tab(self):
        """Create the Authoring Config tab."""
        frame = ctk.CTkFrame(self.tab_config, fg_color="transparent")
        frame.pack(fill="both", expand=True)

        content = ctk.CTkFrame(frame, fg_color="transparent")
        content.pack(fill="both", expand=True)
        content.grid_columnconfigure(0, weight=0, minsize=335)
        content.grid_columnconfigure(1, weight=1)
        content.grid_rowconfigure(0, weight=1)

        settings_card = ctk.CTkScrollableFrame(
            content, label_text="DVD settings", width=320
        )
        settings_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        settings_card.grid_columnconfigure(1, weight=1)
        
        # Video Standard
        std_label = ctk.CTkLabel(settings_card, text="Video standard")
        std_label.grid(row=0, column=0, sticky="e", padx=10, pady=10)
        
        self.standard_var = ctk.StringVar(value="NTSC")
        std_dropdown = ctk.CTkComboBox(
            settings_card,
            values=["NTSC", "PAL"],
            variable=self.standard_var,
            width=165
        )
        std_dropdown.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        
        # Audio Language
        audio_label = ctk.CTkLabel(settings_card, text="Audio")
        audio_label.grid(row=1, column=0, sticky="e", padx=10, pady=10)
        
        self.audio_var = ctk.StringVar(value="English")
        audio_dropdown = ctk.CTkComboBox(
            settings_card,
            values=["English", "Spanish", "French", "German", "Japanese", "Korean", "Chinese"],
            variable=self.audio_var,
            width=165
        )
        audio_dropdown.grid(row=1, column=1, sticky="w", padx=10, pady=10)
        
        # Include Subtitles
        self.subtitles_var = ctk.BooleanVar(value=True)
        subtitles_check = ctk.CTkCheckBox(
            settings_card,
            text="Include subtitles",
            variable=self.subtitles_var
        )
        subtitles_check.grid(row=2, column=1, sticky="w", padx=10, pady=10)
        
        # Include Trailer
        self.trailer_var = ctk.BooleanVar(value=True)
        trailer_check = ctk.CTkCheckBox(
            settings_card,
            text="Include trailer when available",
            variable=self.trailer_var
        )
        trailer_check.grid(row=3, column=1, sticky="w", padx=10, pady=10)
        
        # Menu Style
        style_label = ctk.CTkLabel(settings_card, text="Menu style")
        style_label.grid(row=4, column=0, sticky="e", padx=10, pady=10)
        
        self.style_var = ctk.StringVar(value="Modern")
        style_dropdown = ctk.CTkComboBox(
            settings_card,
            values=["Modern", "Retro"],
            variable=self.style_var,
            width=165
        )
        style_dropdown.grid(row=4, column=1, sticky="w", padx=10, pady=10)
        
        # Burn Speed
        speed_label = ctk.CTkLabel(settings_card, text="Burn speed")
        speed_label.grid(row=5, column=0, sticky="e", padx=10, pady=10)
        
        self.speed_var = ctk.StringVar(value="4x")
        speed_dropdown = ctk.CTkComboBox(
            settings_card,
            values=["1x", "2x", "4x", "8x", "16x"],
            variable=self.speed_var,
            width=165
        )
        speed_dropdown.grid(row=5, column=1, sticky="w", padx=10, pady=10)
        
        # Generate Printable Cover
        self.cover_art_var = ctk.BooleanVar(value=True)
        cover_art_check = ctk.CTkCheckBox(
            settings_card,
            text="Printable case cover",
            variable=self.cover_art_var
        )
        cover_art_check.grid(row=6, column=1, sticky="w", padx=10, pady=10)

        # Generate Printable Folio
        self.folio_var = ctk.BooleanVar(value=True)
        folio_check = ctk.CTkCheckBox(
            settings_card,
            text="Episode booklet",
            variable=self.folio_var
        )
        folio_check.grid(row=7, column=1, sticky="w", padx=10, pady=10)

        # Generate Printable Disc Label
        self.disc_label_var = ctk.BooleanVar(value=True)
        disc_label_check = ctk.CTkCheckBox(
            settings_card,
            text="Printable disc label",
            variable=self.disc_label_var
        )
        disc_label_check.grid(row=8, column=1, sticky="w", padx=10, pady=10)
        
        # Disc Size
        disc_size_label = ctk.CTkLabel(settings_card, text="Disc capacity")
        disc_size_label.grid(row=9, column=0, sticky="e", padx=10, pady=10)
        
        self.disc_size_var = ctk.StringVar(value="DVD-5 (4.7 GB)")
        disc_size_dropdown = ctk.CTkComboBox(
            settings_card,
            values=["DVD-5 (4.7 GB)", "DVD-9 (8.5 GB)"],
            variable=self.disc_size_var,
            width=165,
            command=self._on_disc_size_changed
        )
        disc_size_dropdown.grid(row=9, column=1, sticky="w", padx=10, pady=10)
        
        # Include Trivia Game
        self.trivia_var = ctk.BooleanVar(value=True)
        trivia_check = ctk.CTkCheckBox(
            settings_card,
            text="Interactive trivia game",
            variable=self.trivia_var
        )
        trivia_check.grid(row=10, column=1, sticky="w", padx=10, pady=10)
        
        preview_card = ctk.CTkFrame(content)
        preview_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        preview_header = ctk.CTkFrame(preview_card, fg_color="transparent")
        preview_header.pack(fill="x", padx=14, pady=(12, 6))
        ctk.CTkLabel(
            preview_header,
            text="Live preview",
            font=ctk.CTkFont(size=17, weight="bold"),
        ).pack(side="left")
        self.refresh_preview_btn = ctk.CTkButton(
            preview_header,
            text="Refresh artwork",
            width=125,
            height=30,
            command=self._request_package_preview,
            state="disabled",
        )
        self.refresh_preview_btn.pack(side="right")

        self.preview_mode = ctk.StringVar(value="Package")
        self.preview_mode_switch = ctk.CTkSegmentedButton(
            preview_card,
            values=["Package", "DVD menu"],
            variable=self.preview_mode,
            command=self._on_preview_mode_changed,
        )
        self.preview_mode_switch.pack(fill="x", padx=14, pady=(2, 4))

        self.preview_label = ctk.CTkLabel(
            preview_card,
            text="Select a season to preview its case and disc.",
            height=350,
            corner_radius=10,
            fg_color=("gray88", "gray14"),
        )
        self.preview_label.pack(fill="both", expand=True, padx=14, pady=6)
        self.preview_ctk_image = None
        self.preview_tk_image = None
        self.preview_loading_bar = ctk.CTkProgressBar(
            preview_card,
            mode="determinate",
            height=6,
        )
        self.preview_frame_paths = []
        self.preview_frame_index = 0
        self.preview_drag_x = None
        self.preview_drag_origin = None
        self.preview_documents = {}
        self.menu_preview_screens = {}
        self.menu_preview_screen = "main"
        self.menu_preview_hover = None
        self.menu_preview_photo = None
        self.menu_audio_process = None
        self.menu_audio_path = None
        self.menu_audio_muted = False
        self.preview_label._label.bind("<ButtonPress-1>", self._on_preview_drag_start)
        self.preview_label._label.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_label._label.bind("<ButtonRelease-1>", self._on_preview_click)
        self.preview_label._label.bind("<Motion>", self._on_menu_preview_motion)
        self.preview_label._label.bind("<Leave>", self._on_menu_preview_leave)
        self.preview_label._label.bind("<Key>", self._on_menu_preview_key)
        self.preview_label._label.configure(takefocus=True)

        self.document_buttons_frame = ctk.CTkFrame(
            preview_card, fg_color="transparent"
        )
        self.document_buttons_frame.pack(fill="x", padx=14, pady=(2, 2))
        self.preview_document_buttons = {}
        for kind, title in (
            ("cover", "Case cover"),
            ("booklet", "Booklet"),
            ("disc", "Disc label"),
        ):
            button = ctk.CTkButton(
                self.document_buttons_frame,
                text=title,
                height=30,
                state="disabled",
                command=lambda selected=kind: self._show_preview_document(selected),
            )
            button.pack(side="left", expand=True, fill="x", padx=3)
            self.preview_document_buttons[kind] = button

        self.menu_preview_controls = ctk.CTkFrame(
            preview_card, fg_color="transparent"
        )
        ctk.CTkButton(
            self.menu_preview_controls,
            text="Main menu",
            height=30,
            command=lambda: self._go_to_preview_menu("main"),
        ).pack(side="left", expand=True, fill="x", padx=3)
        self.menu_sound_btn = ctk.CTkButton(
            self.menu_preview_controls,
            text="Menu music on",
            height=30,
            command=self._toggle_menu_audio,
        )
        self.menu_sound_btn.pack(side="left", expand=True, fill="x", padx=3)

        self.preview_status = ctk.CTkLabel(
            preview_card,
            text="The preview is generated before any episodes are transcoded.",
            font=ctk.CTkFont(size=12),
            text_color=("gray45", "gray70"),
        )
        self.preview_status.pack(pady=(4, 8))

        self.config_summary = ctk.CTkFrame(preview_card)
        self.config_summary.pack(fill="x", padx=14, pady=(0, 10))
        
        self.summary_label = ctk.CTkLabel(
            self.config_summary,
            text="No season selected. Please select a season from the Library tab.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.summary_label.pack(padx=12, pady=10)

        self.continue_btn = ctk.CTkButton(
            preview_card,
            text="Continue to output →",
            height=40,
            command=lambda: self.tabview.set("4  Output"),
            state="disabled",
        )
        self.continue_btn.pack(fill="x", padx=14, pady=(0, 14))
    
    def _create_burn_tab(self):
        """Create the Burn tab with progress tracking."""
        frame = ctk.CTkFrame(self.tab_burn)
        frame.pack(fill="both", expand=True)
        
        # Disc info
        self.disc_info_frame = ctk.CTkFrame(frame)
        self.disc_info_frame.pack(fill="x", pady=5)
        
        self.disc_info_label = ctk.CTkLabel(
            self.disc_info_frame,
            text="No project loaded",
            font=ctk.CTkFont(size=14)
        )
        self.disc_info_label.pack(pady=8)
        
        # === Output Mode Selection ===
        output_mode_frame = ctk.CTkFrame(frame)
        output_mode_frame.pack(fill="x", pady=5)
        
        mode_label = ctk.CTkLabel(
            output_mode_frame,
            text="Output Mode:",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        mode_label.pack(anchor="w", padx=10, pady=(5, 2))
        
        # Toggle switch frame
        toggle_frame = ctk.CTkFrame(output_mode_frame, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=10, pady=2)
        
        # Output mode variable (0 = Save ISO, 1 = Burn to Disc)
        self.output_mode_var = ctk.IntVar(value=0)
        
        # Save ISO radio button
        self.iso_radio = ctk.CTkRadioButton(
            toggle_frame,
            text="💾 Save as ISO File",
            variable=self.output_mode_var,
            value=0,
            command=self._on_output_mode_changed
        )
        self.iso_radio.pack(side="left", padx=20)
        
        # Burn to Disc radio button
        self.burn_radio = ctk.CTkRadioButton(
            toggle_frame,
            text="📀 Burn to Disc",
            variable=self.output_mode_var,
            value=1,
            command=self._on_output_mode_changed
        )
        self.burn_radio.pack(side="left", padx=20)
        
        # === ISO Save Options (shown when Save ISO selected) ===
        self.iso_options_frame = ctk.CTkFrame(output_mode_frame)
        self.iso_options_frame.pack(fill="x", padx=10, pady=5)
        
        iso_path_label = ctk.CTkLabel(self.iso_options_frame, text="Save Location:")
        iso_path_label.pack(anchor="w", padx=10, pady=(2, 0))
        
        iso_path_inner = ctk.CTkFrame(self.iso_options_frame, fg_color="transparent")
        iso_path_inner.pack(fill="x", padx=10, pady=2)
        
        # Default to a full ISO path
        default_iso_path = self.config.output_dir.absolute() / "DVD.iso"
        self.iso_path_var = ctk.StringVar(value=str(default_iso_path))
        self.iso_path_entry = ctk.CTkEntry(
            iso_path_inner,
            textvariable=self.iso_path_var,
            width=400
        )
        self.iso_path_entry.pack(side="left", padx=(0, 10))
        
        self.browse_iso_btn = ctk.CTkButton(
            iso_path_inner,
            text="Browse...",
            width=100,
            command=self._on_browse_iso_path
        )
        self.browse_iso_btn.pack(side="left")
        
        # === Burn Options (hidden initially, shown when Burn selected) ===
        self.burn_options_frame = ctk.CTkFrame(output_mode_frame)
        # Initially hidden
        
        drive_label = ctk.CTkLabel(self.burn_options_frame, text="Select DVD Drive:")
        drive_label.pack(anchor="w", padx=10, pady=(2, 0))
        
        drive_inner = ctk.CTkFrame(self.burn_options_frame, fg_color="transparent")
        drive_inner.pack(fill="x", padx=10, pady=2)
        
        self.drive_var = ctk.StringVar(value="No drives detected")
        self.drive_dropdown = ctk.CTkComboBox(
            drive_inner,
            values=["No drives detected"],
            variable=self.drive_var,
            width=300
        )
        self.drive_dropdown.pack(side="left", padx=(0, 10))
        
        self.refresh_drives_btn = ctk.CTkButton(
            drive_inner,
            text="🔄 Refresh",
            width=100,
            command=self._refresh_drives
        )
        self.refresh_drives_btn.pack(side="left")
        
        self.erase_disc_btn = ctk.CTkButton(
            drive_inner,
            text="🧹 Erase Disc",
            width=100,
            command=self._on_erase_disc
        )
        self.erase_disc_btn.pack(side="left", padx=(10, 0))
        
        # Progress section
        progress_frame = ctk.CTkFrame(frame)
        progress_frame.pack(fill="x", pady=5)
        
        # Overall progress
        overall_label = ctk.CTkLabel(progress_frame, text="Overall Progress:")
        overall_label.pack(anchor="w", padx=10, pady=(5, 2))
        
        self.overall_progress = ctk.CTkProgressBar(progress_frame, width=600)
        self.overall_progress.pack(padx=10, pady=2)
        self.overall_progress.set(0)
        
        # Current task progress
        task_label = ctk.CTkLabel(progress_frame, text="Current Task:")
        task_label.pack(anchor="w", padx=10, pady=(5, 2))
        
        self.task_progress = ctk.CTkProgressBar(progress_frame, width=600)
        self.task_progress.pack(padx=10, pady=2)
        self.task_progress.set(0)
        
        self.task_status = ctk.CTkLabel(
            progress_frame,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.task_status.pack(pady=5)
        
        # Buttons
        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(pady=5)
        
        self.start_btn = ctk.CTkButton(
            button_frame,
            text="Create ISO",
            width=200,
            height=40,
            command=self._on_start,
            state="disabled"
        )
        self.start_btn.pack(side="left", padx=10)

        self.play_finished_btn = ctk.CTkButton(
            button_frame,
            text="Test finished DVD",
            width=170,
            height=40,
            command=self._play_finished_dvd,
            state="disabled",
        )
        self.play_finished_btn.pack(side="left", padx=10)
        self.finished_iso_files = []
        
        # Log output
        log_label = ctk.CTkLabel(frame, text="Log Output:")
        log_label.pack(anchor="w", padx=10)
        
        self.log_text = ctk.CTkTextbox(frame, height=80)
        self.log_text.pack(fill="x", padx=10, pady=2)
    
    def _on_output_mode_changed(self):
        """Handle output mode toggle change."""
        mode = self.output_mode_var.get()
        
        if mode == 0:  # Save ISO
            self.burn_options_frame.pack_forget()
            self.iso_options_frame.pack(fill="x", padx=10, pady=10)
            self.start_btn.configure(text="💾 Create ISO")
        else:  # Burn to Disc
            self.iso_options_frame.pack_forget()
            self.burn_options_frame.pack(fill="x", padx=10, pady=10)
            self.start_btn.configure(text="📀 Burn to Disc")
            self._refresh_drives()
    
    def _on_browse_iso_path(self):
        """Open file dialog to select ISO save location."""
        if not GUI_AVAILABLE:
            return
        
        # Get default filename
        default_name = "DVD.iso"
        if self.selected_series and self.selected_season:
            default_name = sanitize_filename(
                f"{self.selected_series.name}_{self.selected_season.name}"
            ) + ".iso"
        
        filepath = filedialog.asksaveasfilename(
            title="Save ISO File",
            defaultextension=".iso",
            filetypes=[("ISO Image", "*.iso"), ("All Files", "*.*")],
            initialfile=default_name,
            initialdir=str(self.config.output_dir)
        )
        
        if filepath:
            self.iso_path_var.set(filepath)
    
    def _refresh_drives(self):
        """Refresh the list of available DVD drives."""
        burner = Burner(self.config.output_dir)
        drives = burner.detect_drives()
        
        if drives:
            drive_names = [f"{d.device_name} ({d.device_path})" for d in drives]
            self.drive_dropdown.configure(values=drive_names)
            self.drive_var.set(drive_names[0])
            self._log(f"✓ Found {len(drives)} optical drive(s)")
        else:
            self.drive_dropdown.configure(values=["No drives detected"])
            self.drive_var.set("No drives detected")
            self._log("⚠️ No optical drives detected")
            
    def _on_erase_disc(self):
        """Handle Erase Disc button click."""
        if not GUI_AVAILABLE:
            return
            
        drive = self.drive_var.get()
        if "No drives" in drive:
            self._log("⚠️ No DVD drive selected. Please select a drive to erase.")
            return
            
        # Get selected drive - extract device path from format "device_name (device_path)"
        device = None
        import re
        match = re.search(r'\(([^)]+)\)$', drive)
        if match:
            device = match.group(1)
            
        if not device:
            self._log("⚠️ Could not determine device path.")
            return
            
        # Confirm with the user
        if not messagebox.askyesno(
            "Confirm Erase",
            f"Are you sure you want to erase the rewritable disc in {drive}?\nAll data on the disc will be permanently lost."
        ):
            return
            
        self.erase_disc_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self._update_task("Erasing disc...", 0.2)
        
        def process():
            try:
                burner = Burner(self.config.output_dir)
                
                def erase_progress(progress: float, status: str):
                    self.after(
                        0,
                        lambda s=status, p=progress: self._update_task(s, p),
                    )
                    
                success = burner.erase_media(
                    device=device,
                    quick=True,
                    progress_callback=erase_progress
                )
                
                if success:
                    self.after(0, lambda: self._log("✓ Disc erased successfully!"))
                    self.after(0, lambda: self._update_task("Erase complete", 1.0))
                else:
                    self.after(0, lambda: self._log("⚠️ Erase failed"))
                    self.after(0, lambda: self._update_task("Erase failed", 0))
            except Exception as e:
                self.after(0, lambda ex=e: self._log(f"⚠️ Erase error: {ex}"))
                self.after(0, lambda: self._update_task("Erase error", 0))
            finally:
                self.after(0, lambda: self.erase_disc_btn.configure(state="normal"))
                # Enable start button if a project is loaded
                if self.disc_plans:
                    self.after(0, lambda: self.start_btn.configure(state="normal"))
                    
        threading.Thread(target=process, daemon=True).start()
    
    def _on_start(self):
        """Handle Start button click - routes to ISO or Burn based on mode."""
        mode = self.output_mode_var.get()
        
        if mode == 0:  # Save ISO
            self._on_create_iso()
        else:  # Burn to Disc
            self._on_burn()

    def _play_finished_dvd(self):
        """Open the authored ISO in a DVD-capable player for an exact test."""
        if not self.finished_iso_files:
            return
        iso_path = Path(self.finished_iso_files[0])
        try:
            import platform
            import shutil
            if platform.system() == "Darwin" and Path("/Applications/VLC.app").exists():
                subprocess.Popen(["open", "-a", "VLC", str(iso_path)])
            elif shutil.which("vlc"):
                subprocess.Popen(["vlc", str(iso_path)])
            elif shutil.which("mpv"):
                subprocess.Popen(["mpv", str(iso_path)])
            else:
                messagebox.showinfo(
                    "DVD player required",
                    "Install VLC to test the finished ISO with its real menus, "
                    "chapters, subtitles, and encoded video.",
                    parent=self,
                )
        except Exception as exc:
            messagebox.showerror(
                "Finished DVD", f"Could not open the DVD player: {exc}", parent=self
            )
    
    def _check_dependencies(self):
        """Check for required system dependencies."""
        deps = check_transcoder_deps()
        burner_deps = check_burner_dependencies()
        
        missing = []
        
        if not deps.get("ffmpeg"):
            missing.append("ffmpeg")
        if not deps.get("ffprobe"):
            missing.append("ffprobe")
        if not deps.get("dvdauthor"):
            missing.append("dvdauthor")
        
        if missing:
            self._log(f"⚠️ Missing critical dependencies: {', '.join(missing)}")
            import platform
            system = platform.system().lower()
            if system == "darwin":
                self._log("Install with: brew install ffmpeg dvdauthor")
            elif system == "linux":
                self._log("Install with: sudo apt install ffmpeg dvdauthor")
            else:
                self._log("Please install ffmpeg and dvdauthor for your system.")
        else:
            self._log("✓ All transcoding and authoring dependencies available")
            
        if not deps.get("spumux"):
            self._log("⚠️ Missing spumux (optional, but required for active menu button highlights)")
        
        # Check ISO creation tools
        iso_tools = ["mkisofs", "genisoimage", "pycdlib"]
        import platform
        system = platform.system().lower()
        if system == "darwin":
            iso_tools.append("hdiutil")
            
        has_iso = any(burner_deps.get(t) for t in iso_tools)
        
        if has_iso:
            self._log("✓ ISO creation available")
        else:
            self._log("⚠️ No ISO creation tool found (need mkisofs, genisoimage, or python pycdlib)")
    
    def _on_connect(self):
        """Handle connect button click."""
        url = self.url_entry.get().strip()
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        
        if not url or not username or not password:
            self._on_connect_error("Enter the server URL, username, and password.")
            return
        
        self.connect_btn.configure(state="disabled", text="Connecting...")
        self.connect_status.configure(text="Connecting to server...", text_color="gray")
        self.update()
        
        # Run connection in thread
        def connect():
            try:
                client = JellyfinClient(url)
                
                # Test connection first
                info = client.get_server_info()
                server_name = info.get('ServerName', 'Unknown')
                
                # Authenticate
                client.authenticate(username, password)
                
                self.jellyfin_client = client
                
                # Update UI on success
                self.after(
                    0,
                    lambda name=server_name: self._on_connect_success(name),
                )
                
            except JellyfinConnectionError as exc:
                message = f"Could not reach the server: {exc}"
                self.after(0, lambda msg=message: self._on_connect_error(msg))
            except AuthenticationError as exc:
                message = f"Login failed: {exc}"
                self.after(0, lambda msg=message: self._on_connect_error(msg))
            except Exception as exc:
                message = f"Could not connect: {exc}"
                self.after(0, lambda msg=message: self._on_connect_error(msg))
        
        threading.Thread(target=connect, daemon=True).start()
    
    def _on_connect_success(self, server_name: str):
        """Handle successful connection."""
        self.connect_btn.configure(state="normal", text="Connected ✓")
        self.connect_status.configure(
            text=f"Connected to {server_name}",
            text_color="green"
        )
        
        self._set_status(f"Connected to {server_name}")
        self._log(f"✓ Connected to {server_name}")
        
        # Load TV shows
        self._load_tv_shows()
        
        # Switch to library tab
        self.tabview.set("2  Library")
    
    def _on_connect_error(self, message: str):
        """Handle connection error."""
        self.connect_btn.configure(state="normal", text="Connect")
        self.connect_status.configure(text=message, text_color="red")
        self._log(f"✗ {message}")
        if GUI_AVAILABLE:
            try:
                messagebox.showerror("Jellyfin connection", message, parent=self)
            except Exception:
                pass
    
    def _load_tv_shows(self):
        """Load TV shows from Jellyfin."""
        if not self.jellyfin_client:
            return
        
        self._set_status("Loading TV shows...")
        
        def load():
            try:
                shows = self.jellyfin_client.get_tv_shows()
                self.after(0, lambda items=shows: self._populate_shows(items))
            except Exception as e:
                self.after(
                    0,
                    lambda ex=e: self._show_library_error("load the library", ex),
                )
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_shows(self, shows: list[Series]):
        """Populate the shows list on initial load."""
        self.all_shows = shows
        self._populate_search_results(shows, "")
        self._set_status(f"Found {len(shows)} TV shows")
        self._log(f"✓ Loaded {len(shows)} TV shows")

    def _on_search_changed(self, *args):
        """Called when search text changes (debounced search)."""
        if hasattr(self, "_search_timer_id") and self._search_timer_id:
            try:
                self.after_cancel(self._search_timer_id)
            except Exception:
                pass
            
        self._search_timer_id = self.after(400, self._perform_server_search)

    def _perform_server_search(self):
        """Run search query on the Jellyfin server."""
        if not self.jellyfin_client:
            return
            
        query = self.search_var.get().strip()
        if not query:
            # If search is cleared, just show all TV shows loaded on startup
            if hasattr(self, "all_shows"):
                self._populate_search_results(self.all_shows, "")
            return
            
        self._set_status(f"Searching for '{query}'...")
        
        def run_search():
            try:
                results = self.jellyfin_client.search_library(query)
                self.after(
                    0,
                    lambda: self._apply_search_results_if_current(results, query),
                )
            except Exception as e:
                self.after(0, lambda ex=e: self._log(f"Search error: {ex}"))
                
        threading.Thread(target=run_search, daemon=True).start()

    def _apply_search_results_if_current(self, results, query):
        """Apply server search results only if the UI query still matches."""
        if self.search_var.get().strip() == query:
            self._populate_search_results(results, query)

    def _populate_search_results(self, results: list[Series], query: str):
        """Populate the shows sidebar with search results."""
        # Clear existing widgets
        for widget in self.show_widgets:
            widget.destroy()
        self.show_widgets.clear()
        
        for show in results:
            prefix = "🎬" if show.type == "Movie" else "📺"
            btn = ctk.CTkButton(
                self.shows_frame,
                text=f"{prefix} {show.name} ({show.year or 'N/A'})",
                anchor="w",
                command=lambda s=show: self._on_show_selected(s)
            )
            btn.pack(fill="x", pady=2)
            self.show_widgets.append(btn)
            
        if query:
            self._set_status(f"Found {len(results)} matches for '{query}'")
        else:
            self._set_status(f"Found {len(results)} TV shows")
    
    def _on_show_selected(self, series: Series):
        """Handle show selection."""
        self.selected_series = series
        self.selected_season = None
        self.disc_plans = []
        self.season_label.configure(text=series.name)
        self.season_dropdown.configure(values=[], state="disabled")
        self.season_var.set("Loading seasons…")
        self.select_season_btn.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.continue_btn.configure(state="disabled")
        self.refresh_preview_btn.configure(state="disabled")
        self.preview_frame_paths = []
        self._clear_package_preview_image("Choose a season to build its preview.")
        for widget in self.episodes_frame.winfo_children():
            widget.destroy()
        
        # Load seasons and detailed metadata
        if not self.jellyfin_client:
            return
        
        self._set_status(f"Loading details for {series.name}...")
        
        def load():
            try:
                # Fetch detailed metadata (actors & full overview) asynchronously
                try:
                    details = self.jellyfin_client.get_item_details(series.id)
                    parse_people_metadata(series, details)
                    series.overview = details.get("Overview", "")
                except Exception as ex:
                    logger.warning(f"Failed to fetch item details: {ex}")
                
                # Fetch seasons list
                seasons = self.jellyfin_client.get_seasons(series.id)
                self.after(
                    0,
                    lambda: self._populate_seasons(seasons, series.id),
                )
            except Exception as e:
                self.after(
                    0,
                    lambda ex=e: self._show_library_error("load seasons", ex),
                )
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_seasons(self, seasons: list[Season], series_id: str):
        """Populate the seasons dropdown."""
        if not self.selected_series or self.selected_series.id != series_id:
            return
        self.seasons_data = {s.name: s for s in seasons}
        
        season_names = [s.name for s in seasons]
        self.season_dropdown.configure(values=season_names, state="normal")
        
        if season_names:
            self.season_dropdown.set(season_names[0])
            self._on_season_selected(season_names[0])
        
        self._set_status(f"Found {len(seasons)} seasons")
    
    def _on_season_selected(self, season_name: str):
        """Handle season selection from dropdown."""
        if season_name not in self.seasons_data:
            return
        
        season = self.seasons_data[season_name]
        self.selected_season = season
        series = self.selected_series
        
        # Load episodes
        if not self.jellyfin_client or not series:
            return
        
        self._set_status(f"Loading episodes...")
        self.select_season_btn.configure(state="disabled")
        for widget in self.episodes_frame.winfo_children():
            widget.destroy()
        ctk.CTkLabel(
            self.episodes_frame,
            text="Loading episodes…",
            text_color=("gray45", "gray70"),
        ).pack(pady=24)
        
        def load():
            try:
                episodes = self.jellyfin_client.get_episodes(
                    series.id,
                    season.id
                )
                season.episodes = episodes
                self.after(
                    0,
                    lambda: self._populate_episodes(
                        episodes, series.id, season.id
                    ),
                )
            except Exception as e:
                self.after(
                    0,
                    lambda ex=e: self._show_library_error("load episodes", ex),
                )
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_episodes(
        self, episodes: list[Episode], series_id: str, season_id: str
    ):
        """Populate the episodes list."""
        if (
            not self.selected_series
            or not self.selected_season
            or self.selected_series.id != series_id
            or self.selected_season.id != season_id
        ):
            return
        # Clear existing
        for widget in self.episodes_frame.winfo_children():
            widget.destroy()
        
        for ep in episodes:
            frame = ctk.CTkFrame(self.episodes_frame)
            frame.pack(fill="x", pady=2)
            
            label = ctk.CTkLabel(
                frame,
                text=f"E{ep.index_number}: {ep.name} ({ep.runtime_minutes:.0f} min)",
                anchor="w"
            )
            label.pack(fill="x", padx=10, pady=5)
        
        self.select_season_btn.configure(state="normal")
        self._set_status(f"Found {len(episodes)} episodes")

    def _show_library_error(self, action: str, error):
        message = f"Could not {action}: {error}"
        self._set_status(message)
        self._log(f"✗ {message}")
        self.select_season_btn.configure(state="disabled")
        if GUI_AVAILABLE:
            try:
                messagebox.showerror("Jellyfin library", message, parent=self)
            except Exception:
                pass
    
    def _on_author_season(self):
        """Handle author season button click."""
        if not self.selected_season or not self.selected_series:
            return
        
        # Calculate disc requirements
        total_minutes = sum(ep.runtime_minutes for ep in self.selected_season.episodes)
        
        # Update config tab summary
        self.summary_label.configure(
            text=f"Series: {self.selected_series.name}\n"
                 f"Season: {self.selected_season.name}\n"
                 f"Episodes: {len(self.selected_season.episodes)}\n"
                 f"Total Runtime: {total_minutes:.0f} minutes",
            text_color="white"
        )
        
        # Create disc plan
        self._create_disc_plan()
        
        # Switch to config tab
        self.tabview.set("3  Preview")
    
    @property
    def current_staging_dir(self) -> Path:
        """Get the staging directory for the currently selected series and season."""
        if not self.selected_series or not self.selected_season:
            return self.config.staging_dir
        
        series_folder = sanitize_filename(self.selected_series.name)
        season_folder = sanitize_filename(self.selected_season.name)
        folder = self.config.staging_dir / series_folder / season_folder
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _request_package_preview(self):
        """Download lightweight artwork and render the pre-build package preview."""
        if not self.selected_series or not self.selected_season or not self.jellyfin_client:
            return

        series = self.selected_series
        season = self.selected_season
        client = self.jellyfin_client
        series_id = series.id
        season_id = season.id
        disc_count = max(1, len(self.disc_plans))
        dvd_capacity_mb = 7900 if "DVD-9" in self.disc_size_var.get() else 4100
        selected_menu_style = self.style_var.get()
        include_trivia_preview = self.trivia_var.get()
        preview_dir = self.current_staging_dir / "preview"
        preview_dir.mkdir(parents=True, exist_ok=True)

        self.refresh_preview_btn.configure(state="disabled")
        self.preview_frame_paths = []
        self.preview_documents = {}
        self.menu_preview_screens = {}
        for button in self.preview_document_buttons.values():
            button.configure(state="disabled")
        self._clear_package_preview_image("Loading artwork…")
        self._show_preview_loading()
        total_preview_steps = len(season.episodes) + 15
        completed_preview_steps = 0
        self.preview_status.configure(
            text=f"Preparing preview — 0 of {total_preview_steps}"
        )

        def advance_preview(label):
            nonlocal completed_preview_steps
            completed_preview_steps += 1
            completed = completed_preview_steps
            self.after(
                0,
                lambda: self._update_preview_loading(
                    completed,
                    total_preview_steps,
                    label,
                    series_id,
                    season_id,
                ),
            )

        def download_optional(url, path):
            if not url:
                return None
            try:
                client.download_image(url, path)
                return path
            except Exception as exc:
                logger.warning(f"Preview artwork download failed for {url}: {exc}")
                return None

        def build():
            try:
                poster_path = download_optional(
                    season.primary_image_url, preview_dir / "poster.jpg"
                )
                advance_preview("Downloaded season poster")
                backdrop_path = download_optional(
                    series.backdrop_image_url, preview_dir / "backdrop.jpg"
                )
                advance_preview("Downloaded backdrop")
                logo_path = download_optional(
                    series.logo_image_url, preview_dir / "logo.png"
                )
                advance_preview("Downloaded series logo")
                theme_path = None
                try:
                    theme_url = client.get_theme_song_url(series.id)
                    theme_path = download_optional(theme_url, preview_dir / "theme.mp3")
                except Exception as exc:
                    logger.warning(f"Preview theme download failed: {exc}")
                advance_preview("Checked theme music")
                for episode in season.episodes:
                    download_optional(
                        episode.primary_image_url,
                        preview_dir / f"ep_{episode.index_number}_thumb.jpg",
                    )
                    advance_preview(
                        f"Downloaded episode artwork {episode.index_number}"
                    )

                art_gen = ArtGenerator(preview_dir)
                cover_pdf = preview_dir / "case-cover.pdf"
                cover_png = preview_dir / "case-cover.png"
                booklet_pdf = preview_dir / "episode-booklet.pdf"
                booklet_png = preview_dir / "episode-booklet.png"
                disc_pdf = preview_dir / "disc-label.pdf"
                disc_png = preview_dir / "disc-label.png"
                common = {
                    "series_name": series.name,
                    "season_name": season.name,
                    "overview": season.overview or series.overview or "",
                    "episodes": season.episodes,
                    "backdrop_path": backdrop_path,
                    "logo_path": logo_path,
                }
                art_gen.generate_dvd_wrap(
                    **common,
                    season_poster_path=poster_path,
                    output_path=cover_pdf,
                    actors=getattr(series, "actors", []),
                    directors=getattr(series, "directors", []),
                    writers=getattr(series, "writers", []),
                    dvd_capacity_mb=dvd_capacity_mb,
                    preview_path=cover_png,
                )
                advance_preview("Rendered case cover")
                art_gen.generate_episode_folio(
                    **common,
                    output_path=booklet_pdf,
                    actors=getattr(series, "actors", []),
                    directors=getattr(series, "directors", []),
                    writers=getattr(series, "writers", []),
                    preview_path=booklet_png,
                )
                advance_preview("Rendered episode booklet")
                art_gen.generate_disc_label(
                    series_name=series.name,
                    season_name=season.name,
                    disc_num=1,
                    total_discs=disc_count,
                    episodes=season.episodes,
                    backdrop_path=backdrop_path,
                    logo_path=logo_path,
                    output_path=disc_pdf,
                    preview_path=disc_png,
                )
                advance_preview("Rendered disc label")
                documents = {
                    "cover": (cover_pdf, cover_png),
                    "booklet": (booklet_pdf, booklet_png),
                    "disc": (disc_pdf, disc_png),
                }
                menu_style = (
                    MenuStyle.RETRO if selected_menu_style == "Retro"
                    else MenuStyle.MODERN
                )
                menu_config = MenuConfig(
                    style=menu_style,
                    title=f"{series.name} - {season.name}",
                    season_overview=season.overview or "",
                    include_cast=True,
                    actors=getattr(series, "actors", []),
                    directors=getattr(series, "directors", []),
                    writers=getattr(series, "writers", []),
                    people_details=getattr(series, "people_details", []),
                )
                menu_builder = MenuBuilder(preview_dir / "menus", menu_config)
                questions = []
                if include_trivia_preview:
                    questions = generate_trivia_questions(
                        series.name,
                        season.name,
                        getattr(series, "year", ""),
                        season.episodes,
                        getattr(series, "actors", []),
                        getattr(series, "directors", []),
                        getattr(series, "writers", []),
                    )
                main_bg, main_hl, _, main_buttons = menu_builder.generate_main_menu(
                    backdrop_path,
                    logo_path,
                    has_trailer=False,
                    show_episode_select=len(season.episodes) > 1,
                    has_trivia=bool(questions),
                )
                main_actions = ["play_all"]
                if len(season.episodes) > 1:
                    main_actions.append("episodes:0")
                main_actions.append("cast:0")
                if questions:
                    main_actions.append("trivia:0")
                screens = {
                    "main": {
                        "background": main_bg,
                        "highlight": main_hl,
                        "buttons": main_buttons,
                        "actions": main_actions,
                    }
                }
                thumbnails = [
                    EpisodeThumbnail(
                        episode_index=episode.index_number,
                        title=episode.name,
                        thumbnail_path=preview_dir / f"ep_{episode.index_number}_thumb.jpg",
                    )
                    for episode in season.episodes
                ]
                total_pages = max(1, (len(thumbnails) + 5) // 6)
                for page in range(total_pages):
                    bg, hl, _, buttons = menu_builder.generate_episode_menu(
                        backdrop_path, logo_path, thumbnails, page, total_pages
                    )
                    page_episodes = season.episodes[page * 6:(page + 1) * 6]
                    actions = [f"episode:{ep.id}" for ep in page_episodes]
                    if page > 0:
                        actions.append(f"episodes:{page - 1}")
                    actions.append("main")
                    if page < total_pages - 1:
                        actions.append(f"episodes:{page + 1}")
                    screens[f"episodes:{page}"] = {
                        "background": bg,
                        "highlight": hl,
                        "buttons": buttons,
                        "actions": actions,
                    }
                cast_pages = menu_builder.generate_cast_menus(
                    backdrop_path,
                    logo_path,
                    overview=series.overview or "",
                    actors=getattr(series, "actors", []),
                )
                for page, (bg, hl, _, buttons) in enumerate(cast_pages):
                    actions = ["main"]
                    if page > 0:
                        actions.append(f"cast:{page - 1}")
                    if page + 1 < len(cast_pages):
                        actions.append(f"cast:{page + 1}")
                    screens[f"cast:{page}"] = {
                        "background": bg,
                        "highlight": hl,
                        "buttons": buttons,
                        "actions": actions,
                    }
                if questions:
                    trivia_pages, wrong_page, win_page = (
                        menu_builder.generate_trivia_menus(
                            questions, backdrop_path, logo_path
                        )
                    )
                    for page, (bg, hl, _, buttons) in enumerate(trivia_pages):
                        correct = questions[page]["correct_index"]
                        next_screen = (
                            f"trivia:{page + 1}"
                            if page + 1 < len(trivia_pages)
                            else "trivia:win"
                        )
                        actions = [
                            next_screen if option == correct else "trivia:wrong"
                            for option in range(4)
                        ]
                        actions.append("main")
                        screens[f"trivia:{page}"] = {
                            "background": bg,
                            "highlight": hl,
                            "buttons": buttons,
                            "actions": actions,
                        }
                    wrong_bg, wrong_hl, _, wrong_buttons = wrong_page
                    screens["trivia:wrong"] = {
                        "background": wrong_bg,
                        "highlight": wrong_hl,
                        "buttons": wrong_buttons,
                        "actions": ["trivia:0", "main"],
                    }
                    win_bg, win_hl, _, win_buttons = win_page
                    screens["trivia:win"] = {
                        "background": win_bg,
                        "highlight": win_hl,
                        "buttons": win_buttons,
                        "actions": ["main"],
                    }
                screens["_theme_path"] = theme_path
                trivia_audio_path = (
                    Path(__file__).resolve().parent / "resources" / "trivia_bg.mp3"
                )
                screens["_trivia_audio_path"] = (
                    trivia_audio_path if trivia_audio_path.exists() else None
                )
                screens["_trivia_questions"] = questions
                advance_preview("Rendered DVD menus")
                frame_paths = []
                renderer = DVDPreviewRenderer()
                for angle in (-60, -40, -20, 0, 20, 40, 60):
                    output_path = preview_dir / f"package-preview-{angle:+03d}.png"
                    renderer.render_open_case(
                        output_path=output_path,
                        series_name=series.name,
                        season_name=season.name,
                        cover_preview_path=cover_png,
                        booklet_preview_path=booklet_png,
                        disc_preview_path=disc_png,
                        backdrop_path=backdrop_path,
                        case_angle=angle,
                    )
                    frame_paths.append(output_path)
                    advance_preview(
                        f"Rendered package view {len(frame_paths)} of 7"
                    )
                self.after(
                    0,
                    lambda: self._show_package_preview(
                        frame_paths, 3, documents, screens, series_id, season_id
                    ),
                )
            except Exception as exc:
                logger.exception("Could not generate package preview")
                self.after(
                    0,
                    lambda error=exc: self._show_package_preview_error(
                        error, series_id, season_id
                    ),
                )

        threading.Thread(target=build, daemon=True).start()

    def _show_package_preview(
        self,
        frame_paths: list[Path],
        frame_index: int,
        documents: dict,
        menu_screens: dict,
        series_id: str,
        season_id: str,
    ):
        """Display a completed preview if the user has not changed selections."""
        if (
            not self.selected_series
            or not self.selected_season
            or self.selected_series.id != series_id
            or self.selected_season.id != season_id
        ):
            return
        self.preview_frame_paths = frame_paths
        self.preview_frame_index = frame_index
        self.preview_documents = documents
        self.menu_preview_screens = menu_screens
        self._hide_preview_loading()
        for kind, button in self.preview_document_buttons.items():
            button.configure(state="normal" if kind in documents else "disabled")
        self._display_current_preview()
        if self.preview_mode.get() == "Package":
            self.preview_status.configure(
                text="Drag to rotate. Click a part to inspect its printable PDF."
            )
        self.refresh_preview_btn.configure(state="normal")

    def _display_package_preview_frame(self):
        if not self.preview_frame_paths:
            return
        try:
            path = self.preview_frame_paths[self.preview_frame_index]
            with Image.open(path) as source:
                image = source.convert("RGB").resize(
                    (620, 360), Image.Resampling.LANCZOS
                )
            # Explicitly bind the PhotoImage to this label's Tcl interpreter.
            # This avoids Python 3.14/Tk resolving it against a stale default
            # root and later raising: image "pyimageN" does not exist.
            self._clear_package_preview_image("")
            self.preview_tk_image = ImageTk.PhotoImage(
                image, master=self.preview_label._label
            )
            self.preview_label._label.configure(image=self.preview_tk_image, text="")
        except Exception as exc:
            self._show_package_preview_error(exc)

    def _display_current_preview(self):
        if self.preview_mode.get() == "DVD menu":
            self._display_menu_preview()
        else:
            self._stop_menu_audio()
            self._display_package_preview_frame()

    def _on_preview_mode_changed(self, _value=None):
        if self.preview_mode.get() == "DVD menu":
            self.document_buttons_frame.pack_forget()
            self.menu_preview_controls.pack(fill="x", padx=14, pady=(2, 2),
                                            before=self.preview_status)
            self._start_menu_audio()
        else:
            self.menu_preview_controls.pack_forget()
            self.document_buttons_frame.pack(fill="x", padx=14, pady=(2, 2),
                                             before=self.preview_status)
            self._stop_menu_audio()
        self._display_current_preview()

    def _go_to_preview_menu(self, screen: str):
        if screen in self.menu_preview_screens:
            self.menu_preview_screen = screen
            self.menu_preview_hover = None
            self._display_menu_preview()

    def _toggle_menu_audio(self):
        if self.menu_audio_process and self.menu_audio_process.poll() is None:
            self.menu_audio_muted = True
            self._stop_menu_audio()
            self.menu_sound_btn.configure(text="Menu music off")
        else:
            self.menu_audio_muted = False
            self._start_menu_audio()
            self.menu_sound_btn.configure(
                text="Menu music on" if self.menu_audio_process else "No theme music"
            )

    def _display_menu_preview(self):
        screen = self.menu_preview_screens.get(self.menu_preview_screen)
        if not screen:
            self._clear_package_preview_image("DVD menu preview is still loading…")
            return
        try:
            with Image.open(screen["background"]) as source:
                image = source.convert("RGB")
            if self.menu_preview_hover is not None:
                with Image.open(screen["highlight"]) as highlight_source:
                    highlight = highlight_source.convert("RGB")
                # spumux treats black as transparent; mirror that behavior here.
                alpha = highlight.convert("L").point(lambda value: 0 if value < 8 else 255)
                image.paste(highlight, (0, 0), alpha)
            image = image.resize((620, 349), Image.Resampling.LANCZOS)
            self._clear_package_preview_image("")
            self.menu_preview_photo = ImageTk.PhotoImage(
                image, master=self.preview_label._label
            )
            self.preview_label._label.configure(image=self.menu_preview_photo, text="")
            self.preview_status.configure(
                text="This uses the same artwork and button map as the authored DVD."
            )
            self._sync_menu_audio()
        except Exception as exc:
            self._show_package_preview_error(exc)

    def _menu_button_at(self, x: int, y: int) -> Optional[int]:
        screen = self.menu_preview_screens.get(self.menu_preview_screen)
        if not screen:
            return None
        label_width = max(620, self.preview_label._label.winfo_width())
        label_height = max(349, self.preview_label._label.winfo_height())
        image_x = x - (label_width - 620) // 2
        image_y = y - (label_height - 349) // 2
        if not (0 <= image_x <= 620 and 0 <= image_y <= 349):
            return None
        coded_x = int(image_x * 720 / 620)
        coded_y = int(image_y * 480 / 349)
        for index, (x0, y0, x1, y1) in enumerate(screen["buttons"]):
            if x0 <= coded_x <= x1 and y0 <= coded_y <= y1:
                return index
        return None

    def _on_menu_preview_motion(self, event):
        if self.preview_mode.get() != "DVD menu":
            return
        hover = self._menu_button_at(event.x, event.y)
        if hover != self.menu_preview_hover:
            self.menu_preview_hover = hover
            self._display_menu_preview()

    def _on_menu_preview_leave(self, _event):
        if self.preview_mode.get() == "DVD menu" and self.menu_preview_hover is not None:
            self.menu_preview_hover = None
            self._display_menu_preview()

    def _on_menu_preview_key(self, event):
        if self.preview_mode.get() != "DVD menu":
            return
        screen = self.menu_preview_screens.get(self.menu_preview_screen)
        if not screen or not screen["buttons"]:
            return
        if event.keysym in ("Return", "space"):
            index = self.menu_preview_hover if self.menu_preview_hover is not None else 0
            self._activate_menu_preview_button(index)
            return "break"
        if event.keysym in ("Left", "Up", "Right", "Down"):
            direction = -1 if event.keysym in ("Left", "Up") else 1
            current = self.menu_preview_hover if self.menu_preview_hover is not None else 0
            self.menu_preview_hover = (current + direction) % len(screen["buttons"])
            self._display_menu_preview()
            return "break"

    def _start_menu_audio(self):
        self._stop_menu_audio()
        if self.menu_audio_muted:
            return
        audio_path = self._menu_audio_for_current_screen()
        if not audio_path or not Path(audio_path).exists():
            return
        try:
            import shutil
            player = shutil.which("ffplay")
            if player:
                self.menu_audio_process = subprocess.Popen(
                    [
                        player, "-nodisp", "-loglevel", "quiet",
                        "-stream_loop", "-1", str(audio_path),
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.menu_audio_path = Path(audio_path)
        except Exception as exc:
            logger.warning(f"Could not start preview menu audio: {exc}")

    def _menu_audio_for_current_screen(self) -> Optional[Path]:
        return select_preview_menu_audio(
            self.menu_preview_screen, self.menu_preview_screens
        )

    def _sync_menu_audio(self):
        desired = self._menu_audio_for_current_screen()
        running = self.menu_audio_process and self.menu_audio_process.poll() is None
        if self.menu_audio_muted:
            if running:
                self._stop_menu_audio()
            return
        if running and desired and self.menu_audio_path == Path(desired):
            return
        self._start_menu_audio()

    def _stop_menu_audio(self):
        process = self.menu_audio_process
        self.menu_audio_process = None
        self.menu_audio_path = None
        if process and process.poll() is None:
            try:
                process.terminate()
            except Exception:
                pass

    def _activate_menu_preview_button(self, index: int):
        screen = self.menu_preview_screens.get(self.menu_preview_screen)
        if not screen or index >= len(screen["actions"]):
            return
        action = screen["actions"][index]
        if action in self.menu_preview_screens:
            self.menu_preview_screen = action
            self.menu_preview_hover = None
            self._display_menu_preview()
            return
        if action == "play_all":
            if self.selected_season and self.selected_season.episodes:
                self._play_preview_episodes(
                    [episode.id for episode in self.selected_season.episodes]
                )
            return
        if action.startswith("episode:"):
            self._play_preview_episodes([action.split(":", 1)[1]])

    def _play_preview_episodes(self, episode_ids: list[str]):
        if not self.jellyfin_client:
            return
        self._stop_menu_audio()
        urls = [
            self.jellyfin_client.get_stream_url(episode_id)
            for episode_id in episode_ids
        ]
        try:
            import platform
            import shutil
            if platform.system() == "Darwin" and Path("/Applications/VLC.app").exists():
                subprocess.Popen(["open", "-a", "VLC", "--args", *urls])
            elif shutil.which("vlc"):
                subprocess.Popen(["vlc", *urls])
            elif shutil.which("ffplay"):
                subprocess.Popen(
                    [
                        shutil.which("ffplay"), "-autoexit", "-loglevel", "warning",
                        urls[0],
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                webbrowser.open(urls[0])
            self.preview_status.configure(
                text=(
                    "Playing Jellyfin source video. VLC queues the full season "
                    "when PLAY ALL is selected."
                )
            )
        except Exception as exc:
            messagebox.showerror(
                "DVD preview", f"Could not play this episode: {exc}", parent=self
            )

    def _on_preview_drag_start(self, event):
        self.preview_drag_x = event.x
        self.preview_drag_origin = (event.x, event.y)

    def _on_preview_drag(self, event):
        if self.preview_drag_x is None or not self.preview_frame_paths:
            return
        delta = event.x - self.preview_drag_x
        if abs(delta) < 28:
            return
        step = 1 if delta > 0 else -1
        next_index = max(
            0,
            min(len(self.preview_frame_paths) - 1, self.preview_frame_index + step),
        )
        self.preview_drag_x = event.x
        if next_index != self.preview_frame_index:
            self.preview_frame_index = next_index
            self._display_package_preview_frame()

    def _on_preview_click(self, event):
        origin = self.preview_drag_origin
        self.preview_drag_x = None
        self.preview_drag_origin = None
        if not origin or abs(event.x - origin[0]) > 8 or abs(event.y - origin[1]) > 8:
            return
        if self.preview_mode.get() == "DVD menu":
            self.preview_label._label.focus_set()
            button = self._menu_button_at(event.x, event.y)
            if button is not None:
                self._activate_menu_preview_button(button)
            return
        # The open-case model is consistently laid out as booklet-left/disc-right.
        if event.y > 315 or event.x < 55 or event.x > 585:
            kind = "cover"
        elif event.x < 310:
            kind = "booklet"
        else:
            kind = "disc"
        self._show_preview_document(kind)

    def _show_preview_document(self, kind: str):
        document = self.preview_documents.get(kind)
        if not document:
            return
        pdf_path, image_path = document
        titles = {
            "cover": "Printable case cover",
            "booklet": "Episode booklet",
            "disc": "Printable disc label",
        }
        try:
            window = ctk.CTkToplevel(self)
            window.title(titles.get(kind, "Print preview"))
            window.geometry("760x700")
            window.minsize(560, 520)
            window.transient(self)
            with Image.open(image_path) as source:
                image = source.convert("RGB")
                image.thumbnail((700, 590), Image.Resampling.LANCZOS)
            label = ctk.CTkLabel(window, text="", fg_color=("gray88", "gray14"))
            label.pack(fill="both", expand=True, padx=18, pady=(18, 10))
            photo = ImageTk.PhotoImage(image, master=label._label)
            label._label.configure(image=photo, text="")
            label._preview_photo = photo
            ctk.CTkButton(
                window,
                text="Open PDF",
                command=lambda path=pdf_path: webbrowser.open(path.resolve().as_uri()),
            ).pack(pady=(0, 18))
            window.lift()
        except Exception as exc:
            messagebox.showerror(
                "Print preview",
                f"Could not open the {kind} preview: {exc}",
                parent=self,
            )

    def _clear_package_preview_image(self, text: str):
        """Clear the Tk image before changing label text or loading a replacement."""
        try:
            self.preview_label._label.configure(image="", text=text)
        except Exception:
            self.preview_label.configure(text=text)
        self.preview_tk_image = None
        self.preview_ctk_image = None

    def _show_preview_loading(self):
        """Show progress while preview assets are downloaded and rendered."""
        self.preview_loading_bar.set(0)
        self.preview_loading_bar.pack(
            fill="x",
            padx=18,
            pady=(0, 4),
            before=self.document_buttons_frame,
        )

    def _update_preview_loading(
        self,
        completed: int,
        total: int,
        label: str,
        series_id: str,
        season_id: str,
    ):
        """Update progress only for the preview that is still selected."""
        if (
            not self.selected_series
            or not self.selected_season
            or self.selected_series.id != series_id
            or self.selected_season.id != season_id
        ):
            return
        self.preview_loading_bar.set(completed / total)
        self.preview_status.configure(text=f"{label} — {completed} of {total}")

    def _hide_preview_loading(self):
        """Stop and hide the preview activity indicator."""
        self.preview_loading_bar.pack_forget()

    def _show_package_preview_error(
        self,
        error,
        series_id: Optional[str] = None,
        season_id: Optional[str] = None,
    ):
        if series_id is not None and (
            not self.selected_series
            or not self.selected_season
            or self.selected_series.id != series_id
            or self.selected_season.id != season_id
        ):
            return
        self._hide_preview_loading()
        self._clear_package_preview_image(
            "Preview unavailable\nYou can still continue with authoring."
        )
        self.preview_status.configure(text=f"Could not build preview: {error}")
        self.preview_frame_paths = []
        self.preview_documents = {}
        for button in self.preview_document_buttons.values():
            button.configure(state="disabled")
        self.refresh_preview_btn.configure(state="normal")

    def _on_disc_size_changed(self, value):
        if value == "DVD-9 (8.5 GB)":
            from tkinter import messagebox
            messagebox.showwarning(
                "DVD-9 (Dual Layer) Warning",
                "You have selected DVD-9 (Dual Layer).\n\n"
                "Burned dual-layer discs (DVD+R DL) have lower reflectivity and a physical layer break, "
                "which may make them unreadable or prone to freezing/stuttering on older or legacy standalone DVD players.\n\n"
                "If you are burning for legacy hardware compatibility, DVD-5 (Single Layer) is highly recommended."
            )
        self._create_disc_plan()

    def _create_disc_plan(self):
        """Create a disc spanning plan for the selected season."""
        if not self.selected_season:
            return
        
        try:
            dvd_capacity_mb = 7900 if "DVD-9" in self.disc_size_var.get() else 4100
            transcoder = Transcoder(self.current_staging_dir, dvd_capacity_mb=dvd_capacity_mb)
            
            # Migrate any cached transcode files from the root staging directory to the show-specific subfolder
            import shutil
            
            jobs = []
            for ep in self.selected_season.episodes:
                filename = f"ep{ep.index_number:02d}.mpg"
                dest_path = self.current_staging_dir / filename
                src_path = self.config.staging_dir / filename
                
                if src_path.exists() and not dest_path.exists():
                    try:
                        shutil.move(src_path, dest_path)
                        self._log(f"Migrated cached transcode for E{ep.index_number} to series folder")
                    except Exception as e:
                        logger.warning(f"Failed to migrate cached transcode: {e}")
                
                job = TranscodeJob(
                    input_path=self.jellyfin_client.get_stream_url(ep.id) if self.jellyfin_client else "",
                    output_path=dest_path,
                    episode_name=ep.name,
                    episode_index=ep.index_number,
                    duration_seconds=ep.runtime_minutes * 60
                )
                jobs.append(job)
            
            self.disc_plans = transcoder.plan_disc_spanning(jobs)
            
            # Update burn tab
            num_discs = len(self.disc_plans)
            
            if num_discs > 1:
                disc_info_lines = []
                for p in self.disc_plans:
                    if p.episodes:
                        first_ep = p.episodes[0].episode_index
                        last_ep = p.episodes[-1].episode_index
                        disc_info_lines.append(
                            f"Disc {p.disc_number}: Episodes {first_ep}-{last_ep} "
                            f"({p.total_minutes:.0f} min, ~{p.estimated_size_mb:.0f} MB)"
                        )
                self.disc_info_label.configure(
                    text=f"⚠️ This season requires {num_discs} DVDs\n\n" +
                         "\n".join(disc_info_lines),
                    text_color="orange"
                )
            else:
                plan = self.disc_plans[0] if self.disc_plans else None
                if plan and plan.episodes:
                    self.disc_info_label.configure(
                        text=f"✓ Single DVD\n\n"
                             f"Episodes: {len(plan.episodes)}\n"
                             f"Runtime: {plan.total_minutes:.0f} minutes\n"
                             f"Estimated Size: {plan.estimated_size_mb:.0f} MB",
                        text_color="green"
                    )
            
            # Enable start button
            self.start_btn.configure(state="normal")
            self.continue_btn.configure(state="normal")
            self.refresh_preview_btn.configure(state="normal")
            self._request_package_preview()
            
            self._log(f"✓ Disc plan created: {num_discs} disc(s) required")
            
        except Exception as e:
            self._log(f"Error creating disc plan: {e}")
    
    def _on_create_iso(self):
        """Handle Create ISO button click."""
        if not self.disc_plans or not self.selected_season or not self.selected_series:
            return
        
        settings = self._snapshot_authoring_settings()
        self.start_btn.configure(state="disabled")
        
        def process():
            try:
                self._run_authoring_pipeline(burn=False, settings=settings)
            except Exception as e:
                self.after(0, lambda ex=e: self._show_pipeline_error(ex))
            finally:
                self.after(0, lambda: self.start_btn.configure(state="normal"))
        
        threading.Thread(target=process, daemon=True).start()
    
    def _on_burn(self):
        """Handle Burn button click."""
        if not self.disc_plans or not self.selected_season or not self.selected_series:
            return
        
        # Check for burner
        burner = Burner(self.config.output_dir)
        if not burner.is_burner_available():
            self._log("⚠️ No disc burner found. Creating ISO instead.")
            self._on_create_iso()
            return
        
        # Check drive selection
        drive = self.drive_var.get()
        if "No drives" in drive:
            message = "No DVD drive is selected. Choose a drive or use Save ISO mode."
            self._log(f"⚠️ {message}")
            if GUI_AVAILABLE:
                messagebox.showwarning("DVD drive", message, parent=self)
            return
        
        settings = self._snapshot_authoring_settings()
        self.start_btn.configure(state="disabled")
        
        def process():
            try:
                self._run_authoring_pipeline(burn=True, settings=settings)
            except Exception as e:
                self.after(0, lambda ex=e: self._show_pipeline_error(ex))
            finally:
                self.after(0, lambda: self.start_btn.configure(state="normal"))
        
        threading.Thread(target=process, daemon=True).start()

    def _show_pipeline_error(self, error):
        message = str(error)
        self._log(f"✗ Authoring failed: {message}")
        self.task_status.configure(text="Authoring failed")
        if GUI_AVAILABLE:
            try:
                messagebox.showerror("DVD authoring failed", message, parent=self)
            except Exception:
                pass

    def _snapshot_authoring_settings(self) -> dict:
        """Read every Tk-backed build option on the UI thread."""
        return {
            "video_standard": (
                VideoStandard.NTSC
                if self.standard_var.get() == "NTSC"
                else VideoStandard.PAL
            ),
            "menu_style": (
                MenuStyle.MODERN
                if self.style_var.get() == "Modern"
                else MenuStyle.RETRO
            ),
            "include_subs": self.subtitles_var.get(),
            "include_trailer": self.trailer_var.get(),
            "include_trivia": self.trivia_var.get(),
            "dvd_capacity_mb": (
                7900 if "DVD-9" in self.disc_size_var.get() else 4100
            ),
            "iso_path": self.iso_path_var.get(),
            "generate_cover": self.cover_art_var.get(),
            "generate_folio": self.folio_var.get(),
            "generate_labels": self.disc_label_var.get(),
            "drive": self.drive_var.get(),
            "burn_speed": int(self.speed_var.get().replace("x", "")),
        }
    
    def _run_authoring_pipeline(
        self, burn: bool = False, settings: Optional[dict] = None
    ):
        """Run the full DVD authoring pipeline."""
        self._update_task("Initializing...", 0)
        self._update_overall(0)
        
        if settings is None:
            raise RuntimeError("Authoring settings were not captured from the GUI.")
        video_standard = settings["video_standard"]
        menu_style = settings["menu_style"]
        include_subs = settings["include_subs"]
        include_trailer = settings["include_trailer"]
        include_trivia = settings["include_trivia"]
        dvd_capacity_mb = settings["dvd_capacity_mb"]
        
        # Initialize components
        transcoder = Transcoder(
            self.current_staging_dir,
            VideoSettings(video_standard),
            dvd_capacity_mb=dvd_capacity_mb
        )
        
        # Format title cleanly for movies
        if getattr(self.selected_series, "type", "Series") == "Movie":
            menu_title = self.selected_series.name
        else:
            menu_title = f"{self.selected_series.name} - {self.selected_season.name}"
            
        menu_config = MenuConfig(
            style=menu_style,
            title=menu_title,
            season_overview=self.selected_season.overview or "",
            include_subtitles=include_subs,
            include_cast=True,
            actors=getattr(self.selected_series, "actors", []),
            directors=getattr(self.selected_series, "directors", []),
            writers=getattr(self.selected_series, "writers", []),
            people_details=getattr(self.selected_series, "people_details", []),
            include_trailer=include_trailer
        )
        
        menu_builder = MenuBuilder(self.current_staging_dir, menu_config)
        burner = Burner(self.config.output_dir)
        
        # --- Check System Dependencies upfront ---
        self._update_task("Checking system dependencies...", 0)
        self._log("Checking system dependencies...")
        
        transcoder_deps = check_transcoder_deps()
        missing_critical = []
        if not transcoder_deps.get("ffmpeg"):
            missing_critical.append("ffmpeg")
        if not transcoder_deps.get("ffprobe"):
            missing_critical.append("ffprobe")
        if not transcoder_deps.get("dvdauthor"):
            missing_critical.append("dvdauthor")
            
        if missing_critical:
            error_msg = f"Critical dependencies missing: {', '.join(missing_critical)}."
            import platform
            system = platform.system().lower()
            if system == "darwin":
                error_msg += " Please install them. Run: brew install ffmpeg dvdauthor"
            elif system == "linux":
                error_msg += " Please install them. Run: sudo apt install ffmpeg dvdauthor"
            else:
                error_msg += " Please install ffmpeg and dvdauthor for your system."
            self._log(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
            
        if not transcoder_deps.get("spumux"):
            self._log("⚠️ Warning: spumux not found. Menu button highlights will be inactive.")
            
        if include_subs:
            self._log("Checking FFmpeg subtitle filter support...")
            try:
                import shutil
                import subprocess
                ffmpeg_path = shutil.which("ffmpeg")
                if ffmpeg_path:
                    result = subprocess.run([ffmpeg_path, "-filters"], capture_output=True, text=True, check=True)
                    if "subtitles" not in result.stdout:
                        self._log("⚠️ Warning: Your installed FFmpeg was not compiled with subtitle support (requires --enable-libass).")
                        self._log("⚠️ Proceeding without burning in subtitles.")
                        include_subs = False
                    else:
                        self._log("✓ FFmpeg subtitle support verified.")
            except Exception as e:
                self._log(f"⚠️ Could not verify FFmpeg subtitle support: {e}")

        # Check ISO creation tools
        burner_deps = check_burner_dependencies()
        import platform
        system = platform.system().lower()
        
        iso_tools = ["mkisofs", "genisoimage", "pycdlib"]
        if system == "darwin":
            iso_tools.append("hdiutil")
            
        has_iso_tool = any(burner_deps.get(t) for t in iso_tools)
        if not has_iso_tool:
            error_msg = "No ISO creation tool found (need mkisofs, genisoimage, or python pycdlib)."
            self._log(f"❌ {error_msg}")
            raise RuntimeError(error_msg)
            
        # Check burning tools if burning is requested
        if burn:
            if not burner.is_burner_available():
                burner_info = burner.get_burner_info()
                error_msg = "Burning requested, but no burning tool is available on this system.\n"
                error_msg += burner_info["instructions"]
                self._log(f"❌ {error_msg}")
                raise RuntimeError(error_msg)
            
        self._log("✓ All dependencies verified.")
        
        # --- Download assets from Jellyfin ---
        self._update_task("Downloading Series assets...", 0)
        
        backdrop_path = None
        if self.jellyfin_client and self.selected_series.backdrop_image_url:
            self._log("Downloading series backdrop...")
            try:
                backdrop_path = self.config.assets_dir / "backdrop.jpg"
                self.jellyfin_client.download_image(self.selected_series.backdrop_image_url, backdrop_path)
            except Exception as e:
                self._log(f"⚠️ Failed to download backdrop: {e}")
                backdrop_path = None

        logo_path = None
        if self.jellyfin_client and self.selected_series.logo_image_url:
            self._log("Downloading series logo...")
            try:
                logo_path = self.config.assets_dir / "logo.png"
                self.jellyfin_client.download_image(self.selected_series.logo_image_url, logo_path)
            except Exception as e:
                self._log(f"⚠️ Failed to download logo: {e}")
                logo_path = None

        season_poster_path = None
        if self.jellyfin_client and self.selected_season and self.selected_season.primary_image_url:
            self._log("Downloading season poster...")
            try:
                season_poster_path = self.config.assets_dir / "season_poster.jpg"
                self.jellyfin_client.download_image(self.selected_season.primary_image_url, season_poster_path)
            except Exception as e:
                self._log(f"⚠️ Failed to download season poster: {e}")
                season_poster_path = None

        theme_path = None
        if self.jellyfin_client:
            try:
                theme_url = self.jellyfin_client.get_theme_song_url(self.selected_series.id)
                if theme_url:
                    self._log("Downloading theme song loop...")
                    theme_path = self.config.assets_dir / "theme.mp3"
                    self.jellyfin_client.download_image(theme_url, theme_path)
            except Exception as e:
                self._log(f"⚠️ Failed to download theme song: {e}")
                theme_path = None

        # Download episode thumbnails
        ep_thumbs = {}
        if self.jellyfin_client and self.selected_season:
            for ep in self.selected_season.episodes:
                if ep.primary_image_url:
                    self._log(f"Downloading E{ep.index_number} thumbnail...")
                    try:
                        t_path = self.config.assets_dir / f"ep_{ep.index_number}_thumb.jpg"
                        self.jellyfin_client.download_image(ep.primary_image_url, t_path)
                        ep_thumbs[ep.index_number] = t_path
                    except Exception as e:
                        self._log(f"⚠️ Failed to download thumbnail for E{ep.index_number}: {e}")

        # Download people images (actors, directors, writers)
        if self.jellyfin_client:
            self._log("Downloading cast & crew images...")
            people_dir = self.config.assets_dir / "people"
            people_dir.mkdir(parents=True, exist_ok=True)
            
            target_people = []
            actors_count = 0
            for p in getattr(self.selected_series, "people_details", []):
                if p["type"] == "Actor" and p["primary_image_tag"]:
                    if actors_count < 18:
                        target_people.append(p)
                        actors_count += 1
                elif p["type"] in ("Director", "Writer") and p["primary_image_tag"]:
                    target_people.append(p)
                    
            for p in target_people:
                p_id = p["id"]
                img_tag = p["primary_image_tag"]
                save_path = people_dir / f"{p_id}.jpg"
                p["image_path"] = save_path
                if not save_path.exists() or save_path.stat().st_size == 0:
                    try:
                        img_url = f"{self.jellyfin_client.server_url}/Items/{p_id}/Images/Primary?tag={img_tag}&maxWidth=200"
                        self.jellyfin_client.download_image(img_url, save_path)
                    except Exception as e:
                        logger.warning(f"Failed to download image for {p['name']}: {e}")
                        p["image_path"] = None

        # Check and download/transcode series trailer
        trailer_path = None
        if include_trailer and self.jellyfin_client and self.selected_series:
            self._log("Checking for local trailers on server...")
            try:
                trailers = self.jellyfin_client.get_local_trailers(self.selected_series.id)
                if trailers:
                    trailer_item = trailers[0]
                    self._log(f"Found local trailer: {trailer_item.get('Name')}")
                    trailer_path = self.current_staging_dir / "trailer.mpg"
                    
                    if trailer_path.exists() and trailer_path.stat().st_size > 2 * 1024 * 1024:
                        self._log("✓ Trailer already transcoded. Skipping transcode.")
                    else:
                        temp_trailer_input = self.current_staging_dir / "temp_trailer_input.tmp"
                        try:
                            self._log("Downloading trailer from server...")
                            stream_url = self.jellyfin_client.get_stream_url(trailer_item["Id"])
                            response = self.jellyfin_client.session.get(stream_url, stream=True, timeout=30)
                            response.raise_for_status()
                            
                            total_bytes = int(response.headers.get('content-length', 0))
                            downloaded = 0
                            
                            with open(temp_trailer_input, 'wb') as f:
                                for chunk in response.iter_content(chunk_size=65536):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        if total_bytes > 0:
                                            pct = downloaded / total_bytes
                                            self.after(0, lambda p=pct: self.task_progress.set(p * 0.3))
                                            self._update_task(
                                                f"Downloading Trailer ({pct * 100:.1f}%)",
                                                pct * 0.3
                                            )
                            
                            self._log("Finished downloading trailer. Transcoding...")
                            
                            def trailer_transcode_progress(progress: float):
                                self.after(0, lambda p=progress: self.task_progress.set(0.3 + p * 0.7))
                            
                            transcoder.transcode(
                                str(temp_trailer_input),
                                trailer_path,
                                progress_callback=trailer_transcode_progress,
                                extract_subs=False
                            )
                            self._log("✓ Trailer transcode completed.")
                        except Exception as e:
                            self._log(f"⚠️ Trailer transcode failed: {e}")
                            trailer_path = None
                        finally:
                            if temp_trailer_input.exists():
                                try:
                                    temp_trailer_input.unlink()
                                except Exception:
                                    pass
                else:
                    self._log("No local trailers found on server. Checking for remote YouTube trailers...")
                    import shutil
                    import subprocess
                    
                    item_details = self.jellyfin_client.get_item_details(self.selected_series.id)
                    remote_trailers = item_details.get("RemoteTrailers", [])
                    youtube_url = None
                    if remote_trailers:
                        for rt in remote_trailers:
                            rt_url = rt.get("Url", "")
                            if "youtube.com" in rt_url or "youtu.be" in rt_url:
                                youtube_url = rt_url
                                self._log(f"Found remote YouTube trailer: {rt.get('Name')} ({rt_url})")
                                break
                    
                    if youtube_url:
                        trailer_path = self.current_staging_dir / "trailer.mpg"
                        if trailer_path.exists() and trailer_path.stat().st_size > 2 * 1024 * 1024:
                            self._log("✓ Trailer already downloaded and transcoded. Skipping.")
                        else:
                            yt_dlp_path = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
                            if yt_dlp_path and Path(yt_dlp_path).exists():
                                temp_trailer_input = self.current_staging_dir / "temp_trailer_input.mp4"
                                try:
                                    self._log("Downloading YouTube trailer using yt-dlp...")
                                    if temp_trailer_input.exists():
                                        temp_trailer_input.unlink()
                                        
                                    subprocess.run(
                                        [
                                            yt_dlp_path,
                                            "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                                            "--merge-output-format", "mp4",
                                            "-o", str(temp_trailer_input),
                                            youtube_url
                                        ],
                                        capture_output=True,
                                        text=True,
                                        check=True,
                                        timeout=300
                                    )
                                    
                                    if temp_trailer_input.exists() and temp_trailer_input.stat().st_size > 0:
                                        self._log("Finished downloading trailer. Transcoding...")
                                        
                                        def trailer_transcode_progress(progress: float):
                                            self.after(0, lambda p=progress: self.task_progress.set(0.3 + p * 0.7))
                                            
                                        transcoder.transcode(
                                            str(temp_trailer_input),
                                            trailer_path,
                                            progress_callback=trailer_transcode_progress,
                                            extract_subs=False
                                        )
                                        self._log("✓ Trailer transcode completed.")
                                    else:
                                        self._log("⚠️ yt-dlp completed but output file was not created or empty.")
                                        trailer_path = None
                                except Exception as e:
                                    self._log(f"⚠️ YouTube trailer download/transcode failed: {e}")
                                    trailer_path = None
                                finally:
                                    if temp_trailer_input.exists():
                                        try:
                                            temp_trailer_input.unlink()
                                        except Exception:
                                            pass
                            else:
                                self._log("⚠️ yt-dlp is not available. Cannot download YouTube trailer.")
                                trailer_path = None
                    else:
                        self._log("No remote YouTube trailers found on server for this item.")
            except Exception as e:
                self._log(f"⚠️ Failed to retrieve/process trailer: {e}")
                trailer_path = None

        iso_files = []
        
        for disc_plan in self.disc_plans:
            disc_num = disc_plan.disc_number
            self._log(f"\n=== Processing Disc {disc_num} of {len(self.disc_plans)} ===")
            
            # Calculate optimal bitrate for this specific disc
            disc_bitrate = transcoder.calculate_optimal_bitrate(disc_plan.total_minutes)
            total_episodes = len(disc_plan.episodes)
            transcoded_files = []
            ep_chapters = {}
            
            for i, job in enumerate(disc_plan.episodes):
                self._update_task(
                    f"Disc {disc_num}: Processing E{job.episode_index} ({i+1}/{total_episodes})",
                    i / total_episodes
                )
                
                # 1. Download subtitles first if requested
                srt_path = job.output_path.with_suffix('.srt')
                if include_subs:
                    import re
                    try:
                        self._log(f"Downloading subtitles for E{job.episode_index}...")
                        match = re.search(r'/Items/([^/]+)/Download', job.input_path)
                        if match:
                            ep_id = match.group(1)
                            if not srt_path.exists():
                                downloaded = download_episode_subtitles(self.jellyfin_client, ep_id, srt_path)
                                if downloaded:
                                    self._log(f"✓ Subtitles downloaded to {srt_path.name}")
                                else:
                                    self._log("No subtitle tracks found or download failed.")
                            else:
                                self._log(f"✓ Subtitles already cached at {srt_path.name}")
                        else:
                            self._log("⚠️ Could not extract episode ID from input path.")
                    except Exception as e:
                        self._log(f"⚠️ Failed to download subtitles: {e}")
                
                # 2. Check cache first
                skip_transcode = transcoder.is_cached_output_current(job.output_path)
                if skip_transcode and include_subs:
                    if not srt_path.exists():
                        skip_transcode = False
                    elif srt_path.stat().st_mtime > job.output_path.stat().st_mtime:
                        # Subtitle file is newer than the video (newly downloaded)
                        skip_transcode = False
                    
                if skip_transcode:
                    self._log(f"✓ E{job.episode_index} already transcoded. Skipping download and transcode.")
                    transcoded_files.append(job.output_path)
                    continue
                
                temp_input_path = self.current_staging_dir / f"temp_input_{job.episode_index}.tmp"
                
                try:
                    self._log(f"Downloading E{job.episode_index} from server...")
                    
                    # Stream download with progress updates
                    response = self.jellyfin_client.session.get(job.input_path, stream=True, timeout=30)
                    response.raise_for_status()
                    
                    total_bytes = int(response.headers.get('content-length', 0))
                    downloaded = 0
                    
                    with open(temp_input_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total_bytes > 0:
                                    pct = downloaded / total_bytes
                                    self.after(0, lambda p=pct: self.task_progress.set(p * 0.3))
                                    self._update_task(
                                        f"Disc {disc_num}: Downloading E{job.episode_index} ({pct * 100:.1f}%)",
                                        (i + pct * 0.3) / total_episodes
                                    )
                                    
                    self._log(f"Finished downloading E{job.episode_index}. Transcoding locally...")
                            
                    def transcode_progress(progress: float):
                        self.after(0, lambda p=progress: self.task_progress.set(
                            0.3 + p * 0.7
                        ))
                        self.after(0, lambda p=progress: self.overall_progress.set(
                            (i + 0.3 + p * 0.7) / total_episodes
                        ))
                    
                    transcoder.transcode(
                        str(temp_input_path),
                        job.output_path,
                        video_bitrate=disc_bitrate,
                        progress_callback=transcode_progress,
                        extract_subs=include_subs
                    )
                    # Extract original chapters before deleting temp file
                    try:
                        ep_chapters[job.episode_index] = transcoder.get_chapters(str(temp_input_path))
                    except Exception:
                        pass
                    transcoded_files.append(job.output_path)
                    self._log(f"✓ E{job.episode_index} completed.")
                    
                except Exception as e:
                    err_msg = str(e)
                    hint = ""
                    if any(term in err_msg for term in ["Invalid data found", "moov atom not found", "Error opening input"]):
                        hint = "\n💡 Hint: This error usually indicates that the source video file on your Jellyfin server is corrupt, incomplete, or cannot be streamed."
                    self._log(f"❌ Transcode failed for {job.episode_name}: {err_msg}{hint}")
                    raise RuntimeError(f"Transcode failed for {job.episode_name}: {err_msg}{hint}")
                finally:
                    # Clean up temporary local download immediately
                    if temp_input_path.exists():
                        try:
                            temp_input_path.unlink()
                        except Exception:
                            pass
            
            # Determine if trailer is included on this disc (only on Disc 1)
            disc_trailer_path = trailer_path if disc_plan.disc_number == 1 else None
            has_trailer = (disc_trailer_path is not None)
            show_ep_select = len(disc_plan.episodes) > 1
            
            # Step 2: Generate Main Menu
            self._update_task(f"Disc {disc_num}: Generating Main Menu...", 0.5)
            self._log("Generating Main Menu...")
            m_bg, m_hl, m_sel, m_btns = menu_builder.generate_main_menu(
                backdrop_path, logo_path, has_trailer=has_trailer, show_episode_select=show_ep_select, has_trivia=include_trivia
            )
            m_base_vid = menu_builder.generate_menu_video(m_bg, "menu_main_base.mpg", theme_path)
            menu_main_vid = menu_builder.compile_interactive_menu(
                m_base_vid, m_hl, m_sel, m_btns, menu_builder.output_dir / "menu_main.mpg"
            )
            
            # Step 3.5: Generate Cast & Info Menus (Optional, paginated)
            menu_cast_vids = []
            if menu_config.include_cast:
                self._update_task(f"Disc {disc_num}: Generating Cast Menus...", 0.55)
                self._log("Generating Cast & Info Menus...")
                cast_pages = menu_builder.generate_cast_menus(
                    backdrop_path,
                    logo_path,
                    overview=self.selected_series.overview or "",
                    actors=menu_config.actors
                )
                for p_idx, (c_bg, c_hl, c_sel, c_btns) in enumerate(cast_pages):
                    c_base_vid = menu_builder.generate_menu_video(c_bg, f"menu_cast_base_{p_idx+1}.mpg")
                    c_vid = menu_builder.compile_interactive_menu(
                        c_base_vid, c_hl, c_sel, c_btns, menu_builder.output_dir / f"menu_cast_{p_idx+1}.mpg"
                    )
                    menu_cast_vids.append(c_vid)
            
            # Step 4: Generate Episode Sub-Menus (paginated, 6 per page) - Only if we have multiple episodes
            menu_episode_vids = []
            if show_ep_select:
                self._update_task(f"Disc {disc_num}: Generating Episode Menus...", 0.6)
                self._log("Generating Episode selection menus...")
                
                episodes_thumbs_list = []
                for job in disc_plan.episodes:
                    t_path = ep_thumbs.get(job.episode_index)
                    ep_thumb = EpisodeThumbnail(
                        episode_index=job.episode_index,
                        title=job.episode_name,
                        thumbnail_path=t_path
                    )
                    episodes_thumbs_list.append(ep_thumb)
                    
                total_pages = (len(episodes_thumbs_list) + 5) // 6
                
                for p_idx in range(total_pages):
                    self._update_task(f"Disc {disc_num}: Generating Episode Menu Page {p_idx+1}/{total_pages}...", 0.6 + (p_idx / total_pages) * 0.1)
                    self._log(f"Generating Episode Selection Menu (Page {p_idx+1}/{total_pages})...")
                    ep_bg, ep_hl, ep_sel, ep_btns = menu_builder.generate_episode_menu(
                        backdrop_path, logo_path, episodes_thumbs_list, p_idx, total_pages
                    )
                    ep_base_vid = menu_builder.generate_menu_video(ep_bg, f"menu_episodes_base_{p_idx+1}.mpg")
                    ep_vid = menu_builder.compile_interactive_menu(
                        ep_base_vid, ep_hl, ep_sel, ep_btns, menu_builder.output_dir / f"menu_episodes_{p_idx+1}.mpg"
                    )
                    menu_episode_vids.append(ep_vid)
            
            # Step 4.5: Generate Trivia Menus (Optional)
            menu_trivia_vids = []
            menu_trivia_wrong_vid = None
            menu_trivia_win_vid = None
            questions = []
            
            if include_trivia:
                self._update_task(f"Disc {disc_num}: Generating Trivia Menus...", 0.70)
                self._log("Generating Trivia game menus...")
                
                # Download/Ensure default trivia audio loop
                trivia_audio = ensure_default_trivia_audio(self.config.assets_dir, self._log)
                
                from jellydisc.menu_builder import generate_trivia_questions
                rel_year = getattr(self.selected_series, "release_year", "")
                eps_list = self.selected_season.episodes
                act_list = getattr(self.selected_series, "actors", [])
                dir_list = getattr(self.selected_series, "directors", [])
                wri_list = getattr(self.selected_series, "writers", [])
                
                questions = self.menu_preview_screens.get(
                    "_trivia_questions", []
                )
                if not questions:
                    questions = generate_trivia_questions(
                        series_name=self.selected_series.name,
                        season_name=self.selected_season.name,
                        release_year=rel_year,
                        episodes=eps_list,
                        actors=act_list,
                        directors=dir_list,
                        writers=wri_list
                    )
                
                t_questions, t_wrong, t_win = menu_builder.generate_trivia_menus(
                    questions, backdrop_path, logo_path
                )
                
                for q_idx, (q_bg, q_hl, q_sel, q_btns) in enumerate(t_questions):
                    q_base_vid = menu_builder.generate_menu_video(q_bg, f"menu_trivia_q_base_{q_idx+1}.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
                    q_vid = menu_builder.compile_interactive_menu(
                        q_base_vid, q_hl, q_sel, q_btns, menu_builder.output_dir / f"menu_trivia_q_{q_idx+1}.mpg"
                    )
                    menu_trivia_vids.append(q_vid)
                    
                w_bg, w_hl, w_sel, w_btns = t_wrong
                w_base_vid = menu_builder.generate_menu_video(w_bg, "menu_trivia_wrong_base.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
                menu_trivia_wrong_vid = menu_builder.compile_interactive_menu(
                    w_base_vid, w_hl, w_sel, w_btns, menu_builder.output_dir / "menu_trivia_wrong.mpg"
                )
                
                win_bg, win_hl, win_sel, win_btns = t_win
                win_base_vid = menu_builder.generate_menu_video(win_bg, "menu_trivia_win_base.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
                menu_trivia_win_vid = menu_builder.compile_interactive_menu(
                    win_base_vid, win_hl, win_sel, win_btns, menu_builder.output_dir / "menu_trivia_win.mpg"
                )
            
            # Step 5: Generate dvdauthor XML
            self._update_task(f"Disc {disc_num}: Building DVD structure...", 0.75)
            self._log("Building DVD structure...")
            
            # Format chapters for this disc
            chapters_list = []
            for job in disc_plan.episodes:
                orig_ch = ep_chapters.get(job.episode_index)
                ch_str = get_chapters_string(job.duration_seconds, orig_ch)
                chapters_list.append(ch_str)
                
            xml_path = menu_builder.generate_dvdauthor_xml(
                transcoded_files,
                menu_main_vid,
                menu_episode_vids,
                menu_cast_paths=menu_cast_vids if menu_cast_vids else None,
                menu_trailer_path=disc_trailer_path,
                chapters_list=chapters_list,
                menu_trivia_paths=menu_trivia_vids if menu_trivia_vids else None,
                menu_trivia_wrong_path=menu_trivia_wrong_vid,
                menu_trivia_win_path=menu_trivia_win_vid,
                trivia_questions=questions if questions else None
            )
            
            # Step 6: Build DVD structure
            try:
                dvd_dir = menu_builder.build_dvd_structure(xml_path)
            except Exception as e:
                self._log(f"❌ DVD structure build failed (dvdauthor failed or not available): {e}")
                raise RuntimeError(f"DVD structure build failed: {e}")
            
            # Step 6: Create ISO
            self._update_task(f"Disc {disc_num}: Creating ISO...", 0.8)
            self._log("Creating ISO image...")
            
            # Determine ISO output path
            # Use user-selected path for single-disc projects (both ISO and Burn modes use this path)
            if len(self.disc_plans) == 1:
                user_iso_path = settings["iso_path"]
                if user_iso_path and Path(user_iso_path).suffix.lower() == '.iso':
                    iso_path = Path(user_iso_path)
                else:
                    iso_name = sanitize_filename(
                        f"{self.selected_series.name}_{self.selected_season.name}_Disc{disc_num}"
                    ) + ".iso"
                    iso_path = self.config.output_dir / iso_name
            else:
                # Multi-disc: use output directory with auto-generated names
                iso_name = sanitize_filename(
                    f"{self.selected_series.name}_{self.selected_season.name}_Disc{disc_num}"
                ) + ".iso"
                iso_path = self.config.output_dir / iso_name
            
            def iso_progress(progress: float, status: str):
                self.after(
                    0,
                    lambda d=disc_num, s=status, p=progress: self._update_task(
                        f"Disc {d}: {s}", 0.8 + p * 0.2
                    ),
                )
            
            try:
                iso_path = burner.create_iso(
                    dvd_dir,
                    iso_path,
                    volume_label=f"DISC{disc_num}",
                    progress_callback=iso_progress
                )
                iso_files.append(iso_path)
                self._log(f"✓ Created: {iso_path}")
            except Exception as e:
                self._log(f"❌ ISO creation failed: {e}")
                raise RuntimeError(f"ISO creation failed: {e}")
            
            self._update_overall(disc_num / len(self.disc_plans))
        
        # Generate printable cover art and/or booklet guide if selected
        generate_cover = settings["generate_cover"]
        generate_folio = settings["generate_folio"]
        generate_labels = settings["generate_labels"]
        
        if (generate_cover or generate_folio or generate_labels) and self.selected_series and self.selected_season:
            self._update_task("Generating printable artwork PDFs...", 0.9)
            self._log("\n=== Generating Printable Artwork ===")
            try:
                art_gen = ArtGenerator(self.config.assets_dir)
                
                # Make sure filenames are safe
                base_name = sanitize_filename(f"{self.selected_series.name}_{self.selected_season.name}")
                
                if generate_cover:
                    cover_pdf_path = self.config.output_dir / f"{base_name}_DVD_Cover.pdf"
                    self._log("Generating DVD Box Cover Art PDF...")
                    art_gen.generate_dvd_wrap(
                        series_name=self.selected_series.name,
                        season_name=self.selected_season.name,
                        overview=self.selected_season.overview or self.selected_series.overview or "",
                        episodes=self.selected_season.episodes,
                        backdrop_path=backdrop_path,
                        logo_path=logo_path,
                        season_poster_path=season_poster_path,
                        output_path=cover_pdf_path,
                        actors=getattr(self.selected_series, "actors", []),
                        directors=getattr(self.selected_series, "directors", []),
                        writers=getattr(self.selected_series, "writers", []),
                        dvd_capacity_mb=dvd_capacity_mb
                    )
                    self._log(f"✓ DVD Cover PDF saved to: {cover_pdf_path}")
                    
                if generate_folio:
                    folio_pdf_path = self.config.output_dir / f"{base_name}_Episode_Guide.pdf"
                    self._log("Generating Episode Guide Booklet PDF...")
                    art_gen.generate_episode_folio(
                        series_name=self.selected_series.name,
                        season_name=self.selected_season.name,
                        overview=self.selected_season.overview or self.selected_series.overview or "",
                        episodes=self.selected_season.episodes,
                        backdrop_path=backdrop_path,
                        logo_path=logo_path,
                        output_path=folio_pdf_path,
                        actors=getattr(self.selected_series, "actors", []),
                        directors=getattr(self.selected_series, "directors", []),
                        writers=getattr(self.selected_series, "writers", [])
                    )
                    self._log(f"✓ Episode Guide Booklet PDF saved to: {folio_pdf_path}")
                    
                if generate_labels:
                    self._log("Generating CD/DVD Disc Face Label PDFs...")
                    total_discs = len(self.disc_plans) if hasattr(self, 'disc_plans') and self.disc_plans else 1
                    disc_plans_list = self.disc_plans if hasattr(self, 'disc_plans') and self.disc_plans else []
                    
                    if disc_plans_list:
                        for disc_plan in disc_plans_list:
                            disc_num = disc_plan.disc_number
                            label_pdf_path = self.config.output_dir / f"{base_name}_Disc_{disc_num}_Label.pdf"
                            art_gen.generate_disc_label(
                                series_name=self.selected_series.name,
                                season_name=self.selected_season.name,
                                disc_num=disc_num,
                                total_discs=total_discs,
                                episodes=disc_plan.episodes,
                                backdrop_path=backdrop_path,
                                logo_path=logo_path,
                                output_path=label_pdf_path
                            )
                            self._log(f"✓ Disc {disc_num} Label PDF saved to: {label_pdf_path}")
                    else:
                        # Fallback if no disc plans are active (e.g. single disc of all episodes)
                        label_pdf_path = self.config.output_dir / f"{base_name}_Disc_1_Label.pdf"
                        art_gen.generate_disc_label(
                            series_name=self.selected_series.name,
                            season_name=self.selected_season.name,
                            disc_num=1,
                            total_discs=1,
                            episodes=self.selected_season.episodes,
                            backdrop_path=backdrop_path,
                            logo_path=logo_path,
                            output_path=label_pdf_path
                        )
                        self._log(f"✓ Disc 1 Label PDF saved to: {label_pdf_path}")
                    
            except Exception as e:
                self._log(f"⚠️ Printable artwork generation failed: {e}")
        
        # Step 7: Burn if requested
        if burn and iso_files:
            self._update_task("Burning to disc...", 0)
            
            # Get selected drive - extract device path from format "device_name (device_path)"
            drive_str = settings["drive"]
            device = None
            import re
            match = re.search(r'\(([^)]+)\)$', drive_str)
            if match:
                device = match.group(1)
            
            def burn_progress(disc: int, total: int, progress: float, status: str):
                self.after(
                    0,
                    lambda d=disc, t=total, p=progress, s=status: self._update_task(
                        f"Disc {d}/{t}: {s}", p
                    ),
                )
            
            try:
                success = burner.burn_multi_disc(
                    iso_files,
                    device=device,
                    speed=settings["burn_speed"],
                    progress_callback=burn_progress
                )
                
                if success:
                    self._log("✓ All discs burned successfully!")
                else:
                    self._log("⚠️ Burning cancelled or failed")
            except Exception as e:
                self._log(f"⚠️ Burn failed: {e}")
        
        # Complete
        self._update_overall(1.0)
        self._update_task("Complete!", 1.0)
        self._log("\n✓ DVD authoring complete!")
        
        if iso_files:
            self._log(f"\nISO files saved to: {self.config.output_dir}")
            for iso in iso_files:
                self._log(f"  - {iso.name}")
            self.after(
                0,
                lambda files=list(iso_files): self._enable_finished_preview(files),
            )

    def _enable_finished_preview(self, iso_files: list[Path]):
        self.finished_iso_files = iso_files
        self.play_finished_btn.configure(state="normal")
    
    def _update_task(self, status: str, progress: float):
        """Update task progress display."""
        self.after(0, lambda s=status: self.task_status.configure(text=s))
        self.after(0, lambda p=progress: self.task_progress.set(p))
    
    def _update_overall(self, progress: float):
        """Update overall progress display."""
        self.after(0, lambda p=progress: self.overall_progress.set(p))
    
    def _set_status(self, message: str):
        """Update the status bar."""
        self.status_label.configure(text=message)
    
    def _log(self, message: str):
        """Add message to log output."""
        def update():
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        
        self.after(0, update)


def download_episode_subtitles(client, episode_id, srt_save_path):
    """
    Check if the episode has external English/any subtitles on Jellyfin and download them.
    Returns True if downloaded successfully.
    """
    try:
        details = client.get_item_details(episode_id)
        media_sources = details.get("MediaSources", [])
        if not media_sources:
            return False
            
        source = media_sources[0]
        media_source_id = source.get("Id")
        streams = source.get("MediaStreams", [])
        
        # Look for English subtitle streams first
        sub_stream = None
        for s in streams:
            if s.get("Type") == "Subtitle" and s.get("Language") == "eng":
                sub_stream = s
                break
                
        # If no English, look for any subtitle stream
        if not sub_stream:
            for s in streams:
                if s.get("Type") == "Subtitle":
                    sub_stream = s
                    break
                    
        if sub_stream and sub_stream.get("IsExternal", False):
            stream_index = sub_stream.get("Index")
            sub_url = f"{client.server_url}/Videos/{episode_id}/{media_source_id}/Subtitles/{stream_index}/0/Stream.srt"
            response = client.session.get(sub_url, params={"api_key": client.access_token}, timeout=10)
            response.raise_for_status()
            srt_save_path.parent.mkdir(parents=True, exist_ok=True)
            srt_save_path.write_text(response.text, encoding='utf-8')
            return True
    except Exception as e:
        logger.warning(f"Failed to check/download external subtitles: {e}")
    return False


def run_cli(args):
    """Run JellyDisc in headless CLI mode."""
    # Configure logging for CLI
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    # 1. Handle list-drives
    if args.list_drives:
        burner = Burner()
        drives = burner.detect_drives()
        if not drives:
            print("No optical drives detected.")
        else:
            print("Detected Optical Drives:")
            for d in drives:
                print(f"  - {d.name} ({d.device_path})")
        return

    # 2. Handle erase
    if args.erase and not args.show: # Standalone erase
        burner = Burner()
        drive = args.drive
        if not drive:
            drives = burner.detect_drives()
            if drives:
                drive = drives[0].device_path
                print(f"No drive specified. Defaulting to first detected drive: {drives[0].name} ({drive})")
            else:
                print("❌ No optical drives detected.")
                sys.exit(1)
        print(f"Erasing media in drive: {drive}...")
        success = burner.erase_media(device=drive)
        if success:
            print("✓ Disc erased successfully!")
        else:
            print("❌ Erase failed.")
            sys.exit(1)
        return

    # 3. Connection details
    server_url = args.server or os.environ.get("JELLYFIN_URL")
    username = args.username or os.environ.get("JELLYFIN_USER")
    password = args.password or os.environ.get("JELLYFIN_PASS")
    show_query = args.show
    
    is_interactive = sys.stdin.isatty()
    missing_args = not server_url or not username or not password or not show_query
    
    if missing_args:
        if not is_interactive:
            print("❌ Error: Missing required connection parameters (--server, --username, --password, --show) in non-interactive environment.")
            sys.exit(1)
            
        print("\n==================================================")
        print("    JellyDisc - Interactive DVD Creator Wizard")
        print("==================================================\n")
        
        if not server_url:
            server_url = input("🔗 Jellyfin Server URL (e.g. https://your-jellyfin-server.com): ").strip()
            while not server_url:
                server_url = input("🔗 Jellyfin Server URL: ").strip()
        if not username:
            username = input("👤 Username: ").strip()
            while not username:
                username = input("👤 Username: ").strip()
        if not password:
            import getpass
            password = getpass.getpass("🔑 Password: ").strip()
            while not password:
                password = getpass.getpass("🔑 Password: ").strip()

    print(f"Connecting to: {server_url}...")
    client = JellyfinClient(server_url)
    try:
        client.authenticate(username, password)
        print("✓ Connected successfully!")
    except Exception as e:
        print(f"❌ Connection failed: {e}")
        sys.exit(1)
        
    if missing_args and not show_query:
        show_query = input("🔍 Enter TV Show or Movie name to search: ").strip()
        while not show_query:
            show_query = input("🔍 Enter TV Show or Movie name to search: ").strip()

    # Search show
    print(f"Searching for '{show_query}'...")
    shows = client.search_library(show_query)
    while not shows:
        print(f"❌ Media '{show_query}' not found.")
        if is_interactive:
            show_query = input("🔍 Enter TV Show or Movie name to search (or 'exit' to quit): ").strip()
            if show_query.lower() == 'exit':
                sys.exit(0)
            shows = client.search_library(show_query)
        else:
            sys.exit(1)
        
    series = None
    if len(shows) > 1 and is_interactive:
        print("\nMultiple matching titles found:")
        for idx, s in enumerate(shows):
            media_type = getattr(s, "type", "Series")
            print(f"  [{idx + 1}] {s.name} ({media_type})")
        while True:
            sel_idx_str = input(f"Select a title [1-{len(shows)}]: ").strip()
            try:
                sel_idx = int(sel_idx_str)
                if 1 <= sel_idx <= len(shows):
                    series = shows[sel_idx - 1]
                    break
            except ValueError:
                pass
            print(f"Please enter a number between 1 and {len(shows)}.")
    else:
        series = shows[0]
        
    print(f"✓ Found media: {series.name} (ID: {series.id})")
    
    try:
        details = client.get_item_details(series.id)
        parse_people_metadata(series, details)
        series.overview = details.get("Overview", "")
    except Exception as e:
        print(f"Warning: Failed to fetch metadata: {e}")
        
    # Seasons
    seasons = client.get_seasons(series.id)
    if not seasons:
        print("❌ No seasons found.")
        sys.exit(1)
        
    season = None
    if getattr(series, "type", "Series") == "Movie":
        season = seasons[0]
    elif args.season:
        for s in seasons:
            if str(s.index_number) == str(args.season) or args.season.lower() in s.name.lower():
                season = s
                break
        if not season:
            print(f"❌ Season '{args.season}' not found.")
            sys.exit(1)
    else:
        if len(seasons) == 1:
            season = seasons[0]
            print(f"Selected Season: {season.name}")
        elif len(seasons) > 1 and is_interactive:
            print(f"\nSeasons available for {series.name}:")
            for idx, s in enumerate(seasons):
                print(f"  [{idx + 1}] {s.name}")
            while True:
                sel_idx_str = input(f"Select a season [1-{len(seasons)}]: ").strip()
                try:
                    sel_idx = int(sel_idx_str)
                    if 1 <= sel_idx <= len(seasons):
                        season = seasons[sel_idx - 1]
                        break
                except ValueError:
                    pass
                print(f"Please enter a number between 1 and {len(seasons)}.")
        else:
            season = seasons[0]
            print(f"Defaulting to Season: {season.name}")
        
    # Episodes
    print("Fetching episode details...")
    try:
        season = client.get_season_details(series.id, season.id)
    except Exception as e:
        print(f"❌ Failed to fetch season details: {e}")
        sys.exit(1)
        
    if not season.episodes:
        print("❌ No episodes found.")
        sys.exit(1)
        
    print(f"✓ Selected: {season.name} with {len(season.episodes)} episodes.")
    
    # Setup working folders
    assets_dir = Path("assets").resolve()
    staging_dir = Path("staging").resolve()
    output_dir = Path("output").resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    series_folder = sanitize_filename(series.name)
    season_folder = sanitize_filename(season.name)
    current_staging_dir = staging_dir / series_folder / season_folder
    current_staging_dir.mkdir(parents=True, exist_ok=True)
    
    video_standard = VideoStandard.NTSC if args.standard == "NTSC" else VideoStandard.PAL
    menu_style = MenuStyle.MODERN if args.style == "Modern" else MenuStyle.RETRO
    include_subs = not args.no_subs
    include_trailer = not args.no_trailer
    include_trivia = not args.no_trivia
    
    burn_disc = args.burn
    erase_disc = args.erase
    drive_path = args.drive
    dvd_capacity_mb = 7900 if args.disc_size == "dvd-9" else 4100
    
    if args.disc_size == "dvd-9":
        print("⚠️ Warning: You selected DVD-9 (Dual Layer). Burned dual-layer media may suffer from playback compatibility issues on legacy players.")
        
    if missing_args and is_interactive:
        # Prompt for optional configs
        if not args.no_subs:
            sub_choice = input("💬 Include subtitles on the DVD? (Y/n): ").strip().lower()
            if sub_choice in ('n', 'no'):
                include_subs = False
        if not args.no_trailer:
            trail_choice = input("🎥 Include trailer (YouTube lookup)? (Y/n): ").strip().lower()
            if trail_choice in ('n', 'no'):
                include_trailer = False
                
        if not args.no_trivia:
            trivia_choice = input("🎮 Include interactive trivia game on the DVD? (Y/n): ").strip().lower()
            if trivia_choice in ('n', 'no'):
                include_trivia = False
                
        style_choice = input("🎨 Menu layout style: [1] Modern (clean dark), [2] Retro (classic) [Default: 1]: ").strip()
        if style_choice == '2':
            menu_style = MenuStyle.RETRO
            
        std_choice = input("📺 DVD format standard: [1] NTSC (US/Japan), [2] PAL (Europe/Asia) [Default: 1]: ").strip()
        if std_choice == '2':
            video_standard = VideoStandard.PAL
            
        # Prompt for disc size
        print("📀 Select target disc size:")
        print("  [1] DVD-5 (Single Layer - 4.7 GB) [Default]")
        print("  [2] DVD-9 (Dual Layer - 8.5 GB)")
        disc_choice = input("Select option [1-2]: ").strip()
        if disc_choice == '2':
            print("\n⚠️ WARNING: Burned dual-layer discs (DVD+R DL) have much lower reflectivity")
            print("   and a physical layer break. This can cause freezing, stuttering, or read")
            print("   failures on older/legacy standalone DVD players.\n")
            confirm_dl = input("Are you sure you want to proceed with DVD-9? (y/N): ").strip().lower()
            if confirm_dl in ('y', 'yes'):
                dvd_capacity_mb = 7900
            else:
                dvd_capacity_mb = 4100
                print("Resetting back to DVD-5 capacity.")
                
        if not args.burn:
            burn_choice = input("💿 Do you want to burn the final ISO to a physical DVD disc? (y/N): ").strip().lower()
            if burn_choice in ('y', 'yes'):
                burn_disc = True
                
                burner = Burner()
                drives = burner.detect_drives()
                
                import platform
                is_in_docker = os.path.exists("/.dockerenv")
                is_docker_desktop = is_in_docker and "linuxkit" in platform.release().lower()
                
                if not drives:
                    print("\n⚠️ No optical drives detected.")
                    if is_docker_desktop:
                        print("   Note: You are running inside Docker Desktop on a macOS/Windows host.")
                        print("   Docker Desktop does not support optical drive (device) passthrough.")
                        print("   Please generate the ISO here and burn it using your host computer instead.\n")
                    burn_disc = False
                else:
                    print("\nDetected optical drives:")
                    for idx, d in enumerate(drives):
                        print(f"  [{idx + 1}] {d.name} ({d.device_path})")
                    while True:
                        drive_choice = input(f"Select a drive number [1-{len(drives)}]: ").strip()
                        try:
                            sel_idx = int(drive_choice)
                            if 1 <= sel_idx <= len(drives):
                                drive_path = drives[sel_idx - 1].device_path
                                break
                        except ValueError:
                            pass
                        print(f"Please enter a number between 1 and {len(drives)}.")
                        
                    erase_choice = input("🧹 Erase/Format rewritable media in the drive first? (y/N): ").strip().lower()
                    if erase_choice in ('y', 'yes'):
                        erase_disc = True
                        
        # Final wizard confirmation
        print("\n" + "="*40)
        print("       DVD Authoring Summary")
        print("="*40)
        print(f"  Show/Movie : {series.name}")
        if getattr(series, "type", "Series") != "Movie":
            print(f"  Season     : {season.name}")
        print(f"  Subtitles  : {'Yes' if include_subs else 'No'}")
        print(f"  Trailers   : {'Yes' if include_trailer else 'No'}")
        print(f"  Trivia Game: {'Yes' if include_trivia else 'No'}")
        print(f"  Menu Style : {menu_style.name}")
        print(f"  Standard   : {video_standard.name}")
        print(f"  Disc Size  : {'DVD-9 (Dual Layer) ⚠️ Prone to issues on legacy players' if dvd_capacity_mb == 7900 else 'DVD-5 (Single Layer)'}")
        print(f"  Burn Disc  : {'Yes' if burn_disc else 'No'}")
        if burn_disc:
            print(f"    - Drive  : {drive_path}")
            print(f"    - Erase  : {'Yes' if erase_disc else 'No'}")
        print("="*40)
        confirm = input("\nProceed with DVD creation? (Y/n): ").strip().lower()
        if confirm in ('n', 'no'):
            print("Aborted.")
            sys.exit(0)
    
    transcoder = Transcoder(current_staging_dir, VideoSettings(video_standard), dvd_capacity_mb=dvd_capacity_mb)
    burner = Burner(output_dir)
    
    # Check dependencies upfront in CLI
    print("Checking system dependencies...")
    transcoder_deps = check_transcoder_deps()
    missing_critical = []
    if not transcoder_deps.get("ffmpeg"):
        missing_critical.append("ffmpeg")
    if not transcoder_deps.get("ffprobe"):
        missing_critical.append("ffprobe")
    if not transcoder_deps.get("dvdauthor"):
        missing_critical.append("dvdauthor")
        
    if missing_critical:
        error_msg = f"Critical dependencies missing: {', '.join(missing_critical)}."
        import platform
        system = platform.system().lower()
        if system == "darwin":
            error_msg += " Please install them. Run: brew install ffmpeg dvdauthor"
        elif system == "linux":
            error_msg += " Please install them. Run: sudo apt install ffmpeg dvdauthor"
        else:
            error_msg += " Please install ffmpeg and dvdauthor for your system."
        print(f"❌ {error_msg}")
        sys.exit(1)
        
    if not transcoder_deps.get("spumux"):
        print("⚠️ Warning: spumux not found. Menu button highlights will be inactive.")
        
    if include_subs:
        print("Checking FFmpeg subtitle filter support...")
        try:
            import shutil
            import subprocess
            ffmpeg_path = shutil.which("ffmpeg")
            if ffmpeg_path:
                result = subprocess.run([ffmpeg_path, "-filters"], capture_output=True, text=True, check=True)
                if "subtitles" not in result.stdout:
                    print("⚠️ Warning: Your installed FFmpeg was not compiled with subtitle support (requires --enable-libass).")
                    print("⚠️ Proceeding without burning in subtitles.")
                    include_subs = False
                else:
                    print("✓ FFmpeg subtitle support verified.")
        except Exception as e:
            print(f"⚠️ Could not verify FFmpeg subtitle support: {e}")

    # Check ISO creation tools
    burner_deps = check_burner_dependencies()
    import platform
    system = platform.system().lower()
    
    iso_tools = ["mkisofs", "genisoimage", "pycdlib"]
    if system == "darwin":
        iso_tools.append("hdiutil")
        
    has_iso_tool = any(burner_deps.get(t) for t in iso_tools)
    if not has_iso_tool:
        print("❌ Error: No ISO creation tool found (need mkisofs, genisoimage, or python pycdlib).")
        sys.exit(1)
        
    # Check burning tools if burning is requested
    if burn_disc:
        if not burner.is_burner_available():
            burner_info = burner.get_burner_info()
            print("❌ Error: Burning requested, but no burning tool is available on this system.")
            print(burner_info["instructions"])
            sys.exit(1)
            
        # Verify drive presence
        if not drive_path:
            detected = burner.detect_drives()
            if not detected:
                print("❌ Error: Burning requested, but no optical drives were detected on this system.")
                sys.exit(1)
        
    print("✓ All dependencies verified.")
    
    jobs = []
    for ep in season.episodes:
        filename = f"ep{ep.index_number:02d}.mpg"
        dest_path = current_staging_dir / filename
        job = TranscodeJob(
            input_path=client.get_stream_url(ep.id),
            output_path=dest_path,
            episode_name=ep.name,
            episode_index=ep.index_number,
            duration_seconds=ep.runtime_minutes * 60
        )
        jobs.append(job)
        
    disc_plans = transcoder.plan_disc_spanning(jobs)
    print(f"\n--- Disc Spanning Plan ({len(disc_plans)} disc(s) required) ---")
    for p in disc_plans:
        first = p.episodes[0].episode_index
        last = p.episodes[-1].episode_index
        print(f"  Disc {p.disc_number}: Episodes {first}-{last} ({p.total_minutes:.0f} min, ~{p.estimated_size_mb:.0f} MB)")
        
    # Download Series/Season images
    print("\nDownloading show assets...")
    backdrop_path = None
    if series.backdrop_image_url:
        try:
            backdrop_path = assets_dir / "backdrop.jpg"
            client.download_image(series.backdrop_image_url, backdrop_path)
        except Exception as e:
            print(f"Warning: Failed to download backdrop: {e}")
            backdrop_path = None
            
    logo_path = None
    if series.logo_image_url:
        try:
            logo_path = assets_dir / "logo.png"
            client.download_image(series.logo_image_url, logo_path)
        except Exception as e:
            print(f"Warning: Failed to download logo: {e}")
            logo_path = None
            
    season_poster_path = None
    if season.primary_image_url:
        try:
            season_poster_path = assets_dir / "season_poster.jpg"
            client.download_image(season.primary_image_url, season_poster_path)
        except Exception as e:
            print(f"Warning: Failed to download season poster: {e}")
            season_poster_path = None
            
    theme_path = None
    try:
        theme_url = client.get_theme_song_url(series.id)
        if theme_url:
            theme_path = assets_dir / "theme.mp3"
            client.download_image(theme_url, theme_path)
    except Exception as e:
        print(f"Warning: Failed to download theme song: {e}")
        theme_path = None
        
    # Download episode thumbnails
    ep_thumbs = {}
    for ep in season.episodes:
        if ep.primary_image_url:
            t_path = assets_dir / f"ep_{ep.index_number}_thumb.jpg"
            try:
                client.download_image(ep.primary_image_url, t_path)
                ep_thumbs[ep.index_number] = t_path
            except Exception:
                pass
                
    # Download people images (actors, directors, writers)
    print("Downloading cast & crew images...")
    people_dir = assets_dir / "people"
    people_dir.mkdir(parents=True, exist_ok=True)
    
    # We will limit the image downloads to actors that will be shown in the menu (top 18 actors for 3 pages)
    # plus any directors and writers.
    target_people = []
    actors_count = 0
    for p in getattr(series, "people_details", []):
        if p["type"] == "Actor" and p["primary_image_tag"]:
            if actors_count < 18:
                target_people.append(p)
                actors_count += 1
        elif p["type"] in ("Director", "Writer") and p["primary_image_tag"]:
            target_people.append(p)
            
    for p in target_people:
        p_id = p["id"]
        img_tag = p["primary_image_tag"]
        save_path = people_dir / f"{p_id}.jpg"
        p["image_path"] = save_path
        if not save_path.exists() or save_path.stat().st_size == 0:
            try:
                img_url = f"{client.server_url}/Items/{p_id}/Images/Primary?tag={img_tag}&maxWidth=200"
                client.download_image(img_url, save_path)
            except Exception as e:
                print(f"  Warning: Failed to download image for {p['name']}: {e}")
                p["image_path"] = None
                
    # Download/Transcode trailer if requested
    trailer_path = None
    if include_trailer:
        print("Checking for trailers...")
        try:
            # 1. Try local trailers first
            trailers = client.get_local_trailers(series.id)
            if trailers:
                trailer_item = trailers[0]
                trailer_path = current_staging_dir / "trailer.mpg"
                if not trailer_path.exists():
                    temp_trailer = current_staging_dir / "temp_trailer.tmp"
                    print("  Downloading local trailer...")
                    def prog_t(dl, tot):
                        percent = 100 * (dl / tot)
                        filled = int(30 * dl // tot)
                        bar = '█' * filled + '-' * (30 - filled)
                        sys.stdout.write(f"\r    |{bar}| {percent:.1f}% ({dl / 1024 / 1024:.1f}/{tot / 1024 / 1024:.1f} MB)")
                        sys.stdout.flush()
                    client.download_media_file(trailer_item["Id"], temp_trailer, progress_callback=prog_t)
                    print()
                    print("  Transcoding local trailer...")
                    transcoder.transcode(str(temp_trailer), trailer_path, extract_subs=False)
                    temp_trailer.unlink()
            else:
                # 2. Try remote YouTube trailers via yt-dlp
                print("  No local trailers found. Checking for remote YouTube trailers...")
                import shutil
                import subprocess
                
                item_details = client.get_item_details(series.id)
                remote_trailers = item_details.get("RemoteTrailers", [])
                youtube_url = None
                if remote_trailers:
                    for rt in remote_trailers:
                        rt_url = rt.get("Url", "")
                        if "youtube.com" in rt_url or "youtu.be" in rt_url:
                            youtube_url = rt_url
                            print(f"  Found remote YouTube trailer URL: {youtube_url}")
                            break
                            
                if youtube_url:
                    trailer_path = current_staging_dir / "trailer.mpg"
                    if trailer_path.exists() and trailer_path.stat().st_size > 2 * 1024 * 1024:
                        print("  ✓ Remote trailer already downloaded and transcoded. Skipping.")
                    else:
                        yt_dlp_path = shutil.which("yt-dlp") or "/opt/homebrew/bin/yt-dlp"
                        if yt_dlp_path and Path(yt_dlp_path).exists():
                            temp_trailer = current_staging_dir / "temp_trailer_input.mp4"
                            try:
                                print("  Downloading remote YouTube trailer using yt-dlp...")
                                if temp_trailer.exists():
                                    temp_trailer.unlink()
                                    
                                subprocess.run(
                                    [
                                        yt_dlp_path,
                                        "-f", "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                                        "--merge-output-format", "mp4",
                                        "-o", str(temp_trailer),
                                        youtube_url
                                    ],
                                    capture_output=True,
                                    text=True,
                                    check=True,
                                    timeout=300
                                )
                                
                                if temp_trailer.exists() and temp_trailer.stat().st_size > 0:
                                    print("  Transcoding remote trailer...")
                                    transcoder.transcode(str(temp_trailer), trailer_path, extract_subs=False)
                                    temp_trailer.unlink()
                                    print("  ✓ Remote trailer transcode complete.")
                            except Exception as e:
                                print(f"  Warning: yt-dlp download failed: {e}")
                                if temp_trailer.exists():
                                    temp_trailer.unlink()
                                trailer_path = None
                        else:
                            print("  Warning: Remote trailer found but yt-dlp is not installed on this system.")
                            trailer_path = None
        except Exception as e:
            print(f"Warning: Failed to download/transcode trailer: {e}")
            trailer_path = None

    # Process each disc plan
    menu_config = MenuConfig(
        style=menu_style,
        title=f"{series.name} - {season.name}" if getattr(series, "type", "Series") != "Movie" else series.name,
        season_overview=season.overview or series.overview or "",
        include_subtitles=include_subs,
        include_cast=True,
        actors=series.actors,
        directors=series.directors,
        writers=series.writers,
        people_details=series.people_details,
        include_trailer=(trailer_path is not None)
    )
    
    menu_builder = MenuBuilder(current_staging_dir, menu_config)
    iso_files = []
    
    for disc_plan in disc_plans:
        disc_num = disc_plan.disc_number
        print(f"\n--- Authoring Disc {disc_num} of {len(disc_plans)} ---")
        
        disc_bitrate = transcoder.calculate_optimal_bitrate(disc_plan.total_minutes)
        print(f"Optimal video bitrate calculated: {disc_bitrate} kbps")
        
        # Transcode episodes
        transcoded_files = []
        ep_chapters = {}
        for job in disc_plan.episodes:
            # 1. Download subtitles first if requested
            srt_path = job.output_path.with_suffix('.srt')
            if include_subs:
                import re
                match = re.search(r'/Items/([^/]+)/Download', job.input_path)
                if match:
                    ep_id = match.group(1)
                    if not srt_path.exists():
                        download_episode_subtitles(client, ep_id, srt_path)
                    
            # 2. Check if we can skip transcode
            skip_transcode = (
                transcoder.is_cached_output_current(job.output_path)
                and job.output_path.stat().st_size > 10 * 1024 * 1024
            )
            if skip_transcode and include_subs:
                if not srt_path.exists():
                     skip_transcode = False
                elif srt_path.stat().st_mtime > job.output_path.stat().st_mtime:
                    # Subtitle file is newer than the video (newly downloaded)
                    skip_transcode = False
                
            if skip_transcode:
                print(f"  E{job.episode_index} already transcoded. Skipping.")
                transcoded_files.append(job.output_path)
                continue
                
            temp_input = current_staging_dir / f"temp_input_{job.episode_index}.tmp"
            print(f"  Downloading E{job.episode_index}...")
            def prog_ep(dl, tot):
                percent = 100 * (dl / tot)
                filled = int(30 * dl // tot)
                bar = '█' * filled + '-' * (30 - filled)
                sys.stdout.write(f"\r    |{bar}| {percent:.1f}% ({dl / 1024 / 1024:.1f}/{tot / 1024 / 1024:.1f} MB)")
                sys.stdout.flush()
            
            try:
                client.download_media_file(season.episodes[job.episode_index - 1].id, temp_input, progress_callback=prog_ep)
                print()
                
                print(f"  Transcoding E{job.episode_index}...")
                transcoder.transcode(str(temp_input), job.output_path, video_bitrate=disc_bitrate, extract_subs=include_subs)
                # Extract original chapters before deleting temp file
                try:
                    ep_chapters[job.episode_index] = transcoder.get_chapters(str(temp_input))
                except Exception:
                    pass
                transcoded_files.append(job.output_path)
                print(f"  ✓ E{job.episode_index} transcode complete.")
            except Exception as e:
                err_msg = str(e)
                hint = ""
                if any(term in err_msg for term in ["Invalid data found", "moov atom not found", "Error opening input"]):
                    hint = "\n💡 Hint: This error usually indicates that the source video file on your Jellyfin server is corrupt, incomplete, or cannot be streamed."
                print(f"\n❌ Transcode failed for {job.episode_name}: {err_msg}{hint}")
                raise RuntimeError(f"Transcode failed for {job.episode_name}: {err_msg}{hint}")
            finally:
                if temp_input.exists():
                    try:
                        temp_input.unlink()
                    except Exception:
                        pass
            
        # Menus
        print("  Generating menus...")
        disc_trailer = trailer_path if disc_num == 1 else None
        show_ep_select = len(disc_plan.episodes) > 1
        
        m_bg, m_hl, m_sel, m_btns = menu_builder.generate_main_menu(
            backdrop_path, logo_path, has_trailer=(disc_trailer is not None), show_episode_select=show_ep_select, has_trivia=include_trivia
        )
        m_base_vid = menu_builder.generate_menu_video(m_bg, "menu_main_base.mpg", theme_path)
        menu_main_vid = menu_builder.compile_interactive_menu(m_base_vid, m_hl, m_sel, m_btns, current_staging_dir / "menu_main.mpg")
        
        menu_cast_vids = []
        if menu_config.include_cast:
            cast_pages = menu_builder.generate_cast_menus(
                backdrop_path, logo_path, overview=series.overview, actors=series.actors
            )
            for p_idx, (c_bg, c_hl, c_sel, c_btns) in enumerate(cast_pages):
                c_base_vid = menu_builder.generate_menu_video(c_bg, f"menu_cast_base_{p_idx+1}.mpg")
                c_vid = menu_builder.compile_interactive_menu(c_base_vid, c_hl, c_sel, c_btns, current_staging_dir / f"menu_cast_{p_idx+1}.mpg")
                menu_cast_vids.append(c_vid)
            
        menu_episode_vids = []
        if show_ep_select:
            episodes_thumbs_list = []
            for job in disc_plan.episodes:
                episodes_thumbs_list.append(
                    EpisodeThumbnail(
                        episode_index=job.episode_index,
                        title=job.episode_name,
                        thumbnail_path=ep_thumbs.get(job.episode_index)
                    )
                )
            total_pages = (len(episodes_thumbs_list) + 5) // 6
            for p_idx in range(total_pages):
                ep_bg, ep_hl, ep_sel, ep_btns = menu_builder.generate_episode_menu(backdrop_path, logo_path, episodes_thumbs_list, p_idx, total_pages)
                ep_base_vid = menu_builder.generate_menu_video(ep_bg, f"menu_episodes_base_{p_idx+1}.mpg")
                ep_vid = menu_builder.compile_interactive_menu(ep_base_vid, ep_hl, ep_sel, ep_btns, current_staging_dir / f"menu_episodes_{p_idx+1}.mpg")
                menu_episode_vids.append(ep_vid)
                
        # Step 4.5: Generate Trivia Menus (Optional)
        menu_trivia_vids = []
        menu_trivia_wrong_vid = None
        menu_trivia_win_vid = None
        questions = []
        
        if include_trivia:
            print("  Generating Trivia game menus...")
            
            # Download/Ensure default trivia audio loop
            trivia_audio = ensure_default_trivia_audio(assets_dir, None)
            
            from jellydisc.menu_builder import generate_trivia_questions
            rel_year = getattr(series, "release_year", "")
            eps_list = season.episodes
            act_list = getattr(series, "actors", [])
            dir_list = getattr(series, "directors", [])
            wri_list = getattr(series, "writers", [])
            
            questions = generate_trivia_questions(
                series_name=series.name,
                season_name=season.name,
                release_year=rel_year,
                episodes=eps_list,
                actors=act_list,
                directors=dir_list,
                writers=wri_list
            )
            
            t_questions, t_wrong, t_win = menu_builder.generate_trivia_menus(
                questions, backdrop_path, logo_path
            )
            
            for q_idx, (q_bg, q_hl, q_sel, q_btns) in enumerate(t_questions):
                q_base_vid = menu_builder.generate_menu_video(q_bg, f"menu_trivia_q_base_{q_idx+1}.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
                q_vid = menu_builder.compile_interactive_menu(
                    q_base_vid, q_hl, q_sel, q_btns, current_staging_dir / f"menu_trivia_q_{q_idx+1}.mpg"
                )
                menu_trivia_vids.append(q_vid)
                
            w_bg, w_hl, w_sel, w_btns = t_wrong
            w_base_vid = menu_builder.generate_menu_video(w_bg, "menu_trivia_wrong_base.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
            menu_trivia_wrong_vid = menu_builder.compile_interactive_menu(
                w_base_vid, w_hl, w_sel, w_btns, current_staging_dir / "menu_trivia_wrong.mpg"
            )
            
            win_bg, win_hl, win_sel, win_btns = t_win
            win_base_vid = menu_builder.generate_menu_video(win_bg, "menu_trivia_win_base.mpg", audio_path=trivia_audio, duration=30 if trivia_audio else 2)
            menu_trivia_win_vid = menu_builder.compile_interactive_menu(
                win_base_vid, win_hl, win_sel, win_btns, current_staging_dir / "menu_trivia_win.mpg"
            )
            
        # dvdauthor structure
        print("  Assembling DVD filesystem structure...")
        
        # Format chapters for this disc
        chapters_list = []
        for job in disc_plan.episodes:
            orig_ch = ep_chapters.get(job.episode_index)
            ch_str = get_chapters_string(job.duration_seconds, orig_ch)
            chapters_list.append(ch_str)
            
        xml_path = menu_builder.generate_dvdauthor_xml(
            transcoded_files,
            menu_main_vid,
            menu_episode_vids,
            menu_cast_paths=menu_cast_vids if menu_cast_vids else None,
            menu_trailer_path=disc_trailer,
            chapters_list=chapters_list,
            menu_trivia_paths=menu_trivia_vids if menu_trivia_vids else None,
            menu_trivia_wrong_path=menu_trivia_wrong_vid,
            menu_trivia_win_path=menu_trivia_win_vid,
            trivia_questions=questions if questions else None
        )
        dvd_dir = menu_builder.build_dvd_structure(xml_path)
        
        # ISO
        print("  Packaging to ISO image...")
        clean_name = sanitize_filename(f"{series.name}_{season.name}_Disc{disc_num}")
        iso_path = output_dir / f"{clean_name}.iso"
        if not output_dir.exists():
            output_dir.mkdir(parents=True, exist_ok=True)
        burner.create_iso(dvd_dir, iso_path, volume_label=f"DISC{disc_num}")
        iso_files.append(iso_path)
        print(f"  ✓ ISO Created: {iso_path}")

    # Generate printables
    print("\n--- Generating Printable Artwork ---")
    art_gen = ArtGenerator(assets_dir)
    base_name = sanitize_filename(f"{series.name}_{season.name}")
    
    cover_pdf = output_dir / f"{base_name}_DVD_Cover.pdf"
    print("Generating Cover wrap PDF...")
    art_gen.generate_dvd_wrap(
        series_name=series.name,
        season_name=season.name,
        overview=season.overview or series.overview or "",
        episodes=season.episodes,
        backdrop_path=backdrop_path,
        logo_path=logo_path,
        season_poster_path=season_poster_path,
        output_path=cover_pdf,
        actors=getattr(series, "actors", []),
        directors=getattr(series, "directors", []),
        writers=getattr(series, "writers", []),
        dvd_capacity_mb=dvd_capacity_mb
    )
    print(f"✓ DVD Cover wrap PDF saved to: {cover_pdf}")
    
    folio_pdf = output_dir / f"{base_name}_Episode_Guide.pdf"
    print("Generating Booklet Insert PDF...")
    art_gen.generate_episode_folio(
        series_name=series.name,
        season_name=season.name,
        overview=season.overview or series.overview or "",
        episodes=season.episodes,
        backdrop_path=backdrop_path,
        logo_path=logo_path,
        output_path=folio_pdf,
        actors=series.actors,
        directors=series.directors,
        writers=series.writers
    )
    print(f"✓ Episode Guide Booklet PDF saved to: {folio_pdf}")
    
    print("Generating Disc Face Label PDFs...")
    total_discs = len(disc_plans)
    for p in disc_plans:
        label_pdf = output_dir / f"{base_name}_Disc_{p.disc_number}_Label.pdf"
        art_gen.generate_disc_label(
            series_name=series.name,
            season_name=season.name,
            disc_num=p.disc_number,
            total_discs=total_discs,
            episodes=p.episodes,
            backdrop_path=backdrop_path,
            logo_path=logo_path,
            output_path=label_pdf
        )
        print(f"✓ Disc {p.disc_number} Label PDF saved to: {label_pdf}")
        
    # Erase / Burn if requested
    if burn_disc and iso_files:
        print("\n--- Burning to Optical Media ---")
        drive = drive_path
        if not drive:
            detected = burner.detect_drives()
            if detected:
                drive = detected[0].device_path
                print(f"No drive specified. Defaulting to first detected drive: {detected[0].name} ({drive})")
            else:
                print("❌ No optical drives detected for burning.")
                sys.exit(1)
                
        # Prompt for first disc insertion
        print(f"\n==========================================")
        print(f"  Please insert a blank/rewritable DVD into drive {drive}")
        print(f"==========================================")
        print("Press Enter once the disc is loaded to begin...")
        try:
            input()
        except (KeyboardInterrupt, EOFError):
            print("❌ Burning cancelled.")
            sys.exit(1)
            
        if erase_disc:
            print(f"Erasing rewritable media in drive {drive}...")
            burner.erase_media(device=drive)
            
        print(f"Burning ISO(s) to drive {drive} at speed {args.speed}x...")
        success = burner.burn_multi_disc(iso_files, device=drive, speed=args.speed)
        if success:
            print("✓ All discs burned successfully!")
        else:
            print("❌ Burning failed.")
            sys.exit(1)

    print("\n🎉 Headless DVD Authoring Process Completed Successfully!")


def main():
    """Run the JellyDisc application."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="JellyDisc - Desktop & Headless DVD Authoring Suite",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument("--headless", action="store_true", help="Run in headless CLI mode without opening GUI")
    parser.add_argument("--server", help="Jellyfin server URL (or JELLYFIN_URL environment variable)")
    parser.add_argument("--username", help="Jellyfin username (or JELLYFIN_USER environment variable)")
    parser.add_argument("--password", help="Jellyfin password (or JELLYFIN_PASS environment variable)")
    parser.add_argument("--show", help="Name of TV Show or Movie to fetch and author")
    parser.add_argument("--season", help="Season number or name (e.g. '1' or 'Season 1')")
    parser.add_argument("--standard", choices=["NTSC", "PAL"], default="NTSC", help="DVD video standard")
    parser.add_argument("--disc-size", choices=["dvd-5", "dvd-9"], default="dvd-5", help="Target DVD disc size capacity")
    parser.add_argument("--style", choices=["Modern", "Retro"], default="Modern", help="Interactive menu layout style")
    parser.add_argument("--no-subs", action="store_true", help="Disable parsing and importing subtitles")
    parser.add_argument("--no-trailer", action="store_true", help="Disable inclusion of local trailers")
    parser.add_argument("--no-trivia", action="store_true", help="Disable inclusion of interactive trivia game")
    parser.add_argument("--burn", action="store_true", help="Automatically burn created ISOs to disc")
    parser.add_argument("--drive", help="Optical drive mount path or system dev path (e.g. /dev/rdisk4)")
    parser.add_argument("--speed", type=int, default=4, help="Write speed for optical disc burning")
    parser.add_argument("--erase", action="store_true", help="Erase/Format rewritable media in the optical drive")
    parser.add_argument("--list-drives", action="store_true", help="List all detected system optical drives and exit")
    
    args = parser.parse_args()

    # Determine if CLI execution is forced or fallback
    is_cli = args.headless or args.list_drives or args.erase or args.show or not GUI_AVAILABLE
    
    if is_cli:
        run_cli(args)
    else:
        # Launch GUI
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        app = JellyDiscApp()
        app.mainloop()


if __name__ == "__main__":
    main()
