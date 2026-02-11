#!/usr/bin/env python3
"""
JellyDisc - Main Application

A cross-platform desktop application that connects to a Jellyfin server,
downloads TV show seasons, and authors commercial-grade DVD ISOs with
interactive menus, metadata, and subtitles.
"""

import logging
import os
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Callable

try:
    import customtkinter as ctk
    from PIL import Image, ImageTk
    from tkinter import filedialog
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
    EpisodeThumbnail
)
from .burner import (
    Burner,
    check_burner_dependencies
)

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


# Configure CustomTkinter (only if available)
if GUI_AVAILABLE:
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    _BaseClass = ctk.CTk
else:
    _BaseClass = object


@dataclass
class AppConfig:
    """Application configuration."""
    # Working directories
    assets_dir: Path = Path("assets")
    staging_dir: Path = Path("staging")
    output_dir: Path = Path("output")
    
    # Authoring settings
    video_standard: VideoStandard = VideoStandard.NTSC
    audio_language: str = "English"
    include_subtitles: bool = True
    menu_style: MenuStyle = MenuStyle.MODERN
    
    # Burn settings
    burn_speed: int = 4


class JellyDiscApp(_BaseClass):
    """Main application window."""
    
    def __init__(self):
        super().__init__()
        
        self.title("JellyDisc - DVD Authoring Suite")
        self.geometry("1000x700")
        self.minsize(800, 600)
        
        # Application state
        self.config = AppConfig()
        self.jellyfin_client: Optional[JellyfinClient] = None
        self.selected_series: Optional[Series] = None
        self.selected_season: Optional[Season] = None
        self.disc_plans: list[DiscPlan] = []
        
        # Editor state - stores edited/customized data
        self.editor_episodes: list[dict] = []  # [{"title": str, "thumbnail_path": Path|None, "overview": str}, ...]
        self.editor_backdrop_path: Optional[Path] = None
        self.editor_theme_music_path: Optional[Path] = None
        self.editor_widgets: list = []  # Store editor episode widgets for cleanup
        
        # Ensure working directories exist
        self.config.assets_dir.mkdir(exist_ok=True)
        self.config.staging_dir.mkdir(exist_ok=True)
        self.config.output_dir.mkdir(exist_ok=True)
        
        # Create UI
        self._create_ui()
        
        # Check dependencies on startup
        self.after(100, self._check_dependencies)
    
    def _create_ui(self):
        """Create the main UI layout."""
        # Create tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Add tabs
        self.tab_connect = self.tabview.add("Connect")
        self.tab_library = self.tabview.add("Library")
        self.tab_editor = self.tabview.add("Editor")
        self.tab_config = self.tabview.add("Authoring")
        self.tab_burn = self.tabview.add("Burn")
        
        # Build each tab
        self._create_connect_tab()
        self._create_library_tab()
        self._create_editor_tab()
        self._create_config_tab()
        self._create_burn_tab()
        
        # Status bar
        self.status_frame = ctk.CTkFrame(self, height=30)
        self.status_frame.pack(fill="x", padx=10, pady=(0, 10))
        
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
        
        # Title
        title = ctk.CTkLabel(
            center_frame, 
            text="🎬 JellyDisc", 
            font=ctk.CTkFont(size=32, weight="bold")
        )
        title.pack(pady=(0, 5))
        
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
            text="TV Shows",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        header.pack(pady=10)
        
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
    
    def _create_editor_tab(self):
        """Create the Editor/Staging tab for reviewing and modifying assets before burning."""
        # Main frame with two panels
        main_frame = ctk.CTkFrame(self.tab_editor)
        main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Configure grid
        main_frame.grid_columnconfigure(0, weight=2)  # Left panel (episodes)
        main_frame.grid_columnconfigure(1, weight=1)  # Right panel (menu assets)
        main_frame.grid_rowconfigure(0, weight=1)
        
        # === Left Panel: Episode List ===
        left_panel = ctk.CTkFrame(main_frame)
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=0)
        
        # Episode list header
        ep_header = ctk.CTkLabel(
            left_panel,
            text="📺 Episode List (Click to edit)",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        ep_header.pack(pady=10)
        
        # Scrollable episode list
        self.editor_episodes_frame = ctk.CTkScrollableFrame(left_panel)
        self.editor_episodes_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        # === Right Panel: Menu Assets ===
        right_panel = ctk.CTkFrame(main_frame)
        right_panel.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=0)
        
        # Menu assets header
        assets_header = ctk.CTkLabel(
            right_panel,
            text="🎨 Menu Assets",
            font=ctk.CTkFont(size=16, weight="bold")
        )
        assets_header.pack(pady=10)
        
        # Backdrop image section
        backdrop_frame = ctk.CTkFrame(right_panel)
        backdrop_frame.pack(fill="x", padx=10, pady=5)
        
        backdrop_label = ctk.CTkLabel(
            backdrop_frame,
            text="Background Image:",
            font=ctk.CTkFont(weight="bold")
        )
        backdrop_label.pack(anchor="w", padx=5, pady=(5, 0))
        
        # Backdrop preview/button
        self.backdrop_preview_frame = ctk.CTkFrame(backdrop_frame, height=100)
        self.backdrop_preview_frame.pack(fill="x", padx=5, pady=5)
        
        self.backdrop_status_label = ctk.CTkLabel(
            self.backdrop_preview_frame,
            text="No backdrop loaded",
            text_color="gray"
        )
        self.backdrop_status_label.pack(pady=20)
        
        backdrop_btn_frame = ctk.CTkFrame(backdrop_frame, fg_color="transparent")
        backdrop_btn_frame.pack(fill="x", padx=5, pady=5)
        
        self.upload_backdrop_btn = ctk.CTkButton(
            backdrop_btn_frame,
            text="📁 Upload Custom",
            command=self._on_upload_backdrop,
            width=120
        )
        self.upload_backdrop_btn.pack(side="left", padx=2)
        
        self.clear_backdrop_btn = ctk.CTkButton(
            backdrop_btn_frame,
            text="🎨 Use Color",
            command=self._on_use_solid_backdrop,
            width=100
        )
        self.clear_backdrop_btn.pack(side="left", padx=2)
        
        # Theme music section
        music_frame = ctk.CTkFrame(right_panel)
        music_frame.pack(fill="x", padx=10, pady=5)
        
        music_label = ctk.CTkLabel(
            music_frame,
            text="Theme Music:",
            font=ctk.CTkFont(weight="bold")
        )
        music_label.pack(anchor="w", padx=5, pady=(5, 0))
        
        self.music_status_label = ctk.CTkLabel(
            music_frame,
            text="No theme music (silent)",
            text_color="gray"
        )
        self.music_status_label.pack(anchor="w", padx=5, pady=5)
        
        music_btn_frame = ctk.CTkFrame(music_frame, fg_color="transparent")
        music_btn_frame.pack(fill="x", padx=5, pady=5)
        
        self.upload_music_btn = ctk.CTkButton(
            music_btn_frame,
            text="📁 Upload Audio",
            command=self._on_upload_theme_music,
            width=120
        )
        self.upload_music_btn.pack(side="left", padx=2)
        
        self.clear_music_btn = ctk.CTkButton(
            music_btn_frame,
            text="🔇 Silent",
            command=self._on_clear_theme_music,
            width=80
        )
        self.clear_music_btn.pack(side="left", padx=2)
        
        # === Bottom buttons ===
        button_frame = ctk.CTkFrame(self.tab_editor, fg_color="transparent")
        button_frame.pack(fill="x", padx=10, pady=10)
        
        self.preview_menu_btn = ctk.CTkButton(
            button_frame,
            text="👁 Preview Menu",
            command=self._on_preview_menu,
            width=150,
            height=40
        )
        self.preview_menu_btn.pack(side="left", padx=10)
        
        self.confirm_burn_btn = ctk.CTkButton(
            button_frame,
            text="✓ Confirm & Proceed to Authoring",
            command=self._on_confirm_and_proceed,
            width=250,
            height=40,
            fg_color="green",
            hover_color="darkgreen"
        )
        self.confirm_burn_btn.pack(side="right", padx=10)
        
        # Info label
        self.editor_info_label = ctk.CTkLabel(
            button_frame,
            text="",
            text_color="gray"
        )
        self.editor_info_label.pack(side="left", padx=20)

    def _populate_editor_tab(self):
        """Populate the editor tab with episode data from the selected season."""
        if not self.selected_season or not self.selected_series:
            return
        
        # Clear existing widgets
        for widget in self.editor_widgets:
            try:
                widget.destroy()
            except Exception:
                pass
        self.editor_widgets.clear()
        self.editor_episodes.clear()
        
        # Reset menu assets
        self.editor_backdrop_path = None
        self.editor_theme_music_path = None
        
        # Fetch series backdrop URL
        backdrop_url = None
        theme_url = None
        if self.jellyfin_client and self.selected_series:
            backdrop_url = self.jellyfin_client._get_image_url(
                self.selected_series.id, "Backdrop", max_width=1280
            )
            theme_url = self.jellyfin_client.get_theme_song_url(self.selected_series.id)
        
        # Update backdrop status
        if backdrop_url:
            self.backdrop_status_label.configure(
                text="✓ Using Jellyfin backdrop",
                text_color="green"
            )
            # Store the URL for later download
            self._jellyfin_backdrop_url = backdrop_url
        else:
            self.backdrop_status_label.configure(
                text="⚠ No backdrop found - upload one or use a solid color",
                text_color="orange"
            )
            self._jellyfin_backdrop_url = None
        
        # Update theme music status
        if theme_url:
            self.music_status_label.configure(
                text="✓ Using Jellyfin theme song",
                text_color="green"
            )
            self._jellyfin_theme_url = theme_url
        else:
            self.music_status_label.configure(
                text="No theme music (will be silent)",
                text_color="gray"
            )
            self._jellyfin_theme_url = None
        
        # Create episode entries
        for ep in self.selected_season.episodes:
            # Prepare episode data with fallbacks
            ep_data = {
                "id": ep.id,
                "index": ep.index_number,
                "title": ep.name if ep.name else f"S{self.selected_season.index_number:02d}E{ep.index_number:02d}",
                "overview": ep.overview if ep.overview else "No description available.",
                "thumbnail_path": None,  # Will be downloaded or set by user
                "thumbnail_url": ep.primary_image_url,  # Jellyfin URL (may be None)
                "runtime_minutes": ep.runtime_minutes
            }
            self.editor_episodes.append(ep_data)
            
            # Create UI for this episode
            self._create_episode_editor_widget(ep_data, len(self.editor_episodes) - 1)
        
        # Update info label
        total_minutes = sum(ep.runtime_minutes for ep in self.selected_season.episodes)
        self.editor_info_label.configure(
            text=f"{len(self.editor_episodes)} episodes • {total_minutes:.0f} min total"
        )
        
        self._log(f"✓ Loaded {len(self.editor_episodes)} episodes into editor")
    
    def _create_episode_editor_widget(self, ep_data: dict, index: int):
        """Create an editable episode widget in the editor."""
        frame = ctk.CTkFrame(self.editor_episodes_frame)
        frame.pack(fill="x", pady=3, padx=2)
        self.editor_widgets.append(frame)
        
        # Configure grid columns
        frame.grid_columnconfigure(1, weight=1)
        
        # Thumbnail button (left side)
        thumb_frame = ctk.CTkFrame(frame, width=80, height=60)
        thumb_frame.grid(row=0, column=0, rowspan=2, padx=5, pady=5)
        thumb_frame.grid_propagate(False)
        
        # Thumbnail status
        if ep_data["thumbnail_url"]:
            thumb_text = "🖼"
            thumb_color = "gray"
        else:
            thumb_text = "⬜"
            thumb_color = "darkgray"
        
        thumb_btn = ctk.CTkButton(
            thumb_frame,
            text=thumb_text,
            font=ctk.CTkFont(size=24),
            fg_color=thumb_color,
            width=70,
            height=50,
            command=lambda idx=index: self._on_upload_episode_thumbnail(idx)
        )
        thumb_btn.place(relx=0.5, rely=0.5, anchor="center")
        
        # Store reference for updates
        ep_data["_thumb_btn"] = thumb_btn
        
        # Episode number label
        ep_num_label = ctk.CTkLabel(
            frame,
            text=f"E{ep_data['index']}:",
            font=ctk.CTkFont(weight="bold"),
            width=40
        )
        ep_num_label.grid(row=0, column=1, sticky="w", padx=(5, 0), pady=(5, 0))
        
        # Editable title entry
        title_entry = ctk.CTkEntry(frame, width=300)
        title_entry.insert(0, ep_data["title"])
        title_entry.grid(row=0, column=2, sticky="ew", padx=5, pady=(5, 0))
        
        # Bind entry changes to update data
        def on_title_change(event, idx=index):
            self.editor_episodes[idx]["title"] = title_entry.get()
        
        title_entry.bind("<KeyRelease>", on_title_change)
        ep_data["_title_entry"] = title_entry
        
        # Runtime label
        runtime_label = ctk.CTkLabel(
            frame,
            text=f"({ep_data['runtime_minutes']:.0f} min)",
            text_color="gray",
            width=60
        )
        runtime_label.grid(row=0, column=3, padx=5, pady=(5, 0))
        
        # Overview (truncated)
        overview_text = ep_data["overview"]
        if len(overview_text) > 80:
            overview_text = overview_text[:77] + "..."
        
        overview_label = ctk.CTkLabel(
            frame,
            text=overview_text,
            text_color="gray",
            anchor="w"
        )
        overview_label.grid(row=1, column=1, columnspan=3, sticky="ew", padx=5, pady=(0, 5))
    
    def _on_upload_episode_thumbnail(self, episode_index: int):
        """Handle uploading a custom thumbnail for an episode."""
        filepath = filedialog.askopenfilename(
            title=f"Select Thumbnail for Episode {self.editor_episodes[episode_index]['index']}",
            filetypes=[
                ("Image Files", "*.jpg *.jpeg *.png *.bmp *.gif"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("All Files", "*.*")
            ]
        )
        
        if filepath:
            self.editor_episodes[episode_index]["thumbnail_path"] = Path(filepath)
            self.editor_episodes[episode_index]["thumbnail_url"] = None  # Override Jellyfin URL
            
            # Update button appearance
            if "_thumb_btn" in self.editor_episodes[episode_index]:
                self.editor_episodes[episode_index]["_thumb_btn"].configure(
                    text="✓",
                    fg_color="green"
                )
            
            self._log(f"✓ Custom thumbnail set for E{self.editor_episodes[episode_index]['index']}")
    
    def _on_upload_backdrop(self):
        """Handle uploading a custom backdrop image."""
        filepath = filedialog.askopenfilename(
            title="Select Background Image",
            filetypes=[
                ("Image Files", "*.jpg *.jpeg *.png *.bmp"),
                ("JPEG", "*.jpg *.jpeg"),
                ("PNG", "*.png"),
                ("All Files", "*.*")
            ]
        )
        
        if filepath:
            self.editor_backdrop_path = Path(filepath)
            self._jellyfin_backdrop_url = None  # Override Jellyfin URL
            self.backdrop_status_label.configure(
                text=f"✓ Custom: {Path(filepath).name}",
                text_color="green"
            )
            self._log(f"✓ Custom backdrop set: {Path(filepath).name}")
    
    def _on_use_solid_backdrop(self):
        """Use a solid color backdrop instead of an image."""
        # Create a solid gray backdrop
        from PIL import Image as PILImage
        
        solid_path = self.config.assets_dir / "solid_backdrop.png"
        img = PILImage.new('RGB', (1280, 720), color=(30, 30, 40))
        img.save(solid_path)
        
        self.editor_backdrop_path = solid_path
        self._jellyfin_backdrop_url = None
        self.backdrop_status_label.configure(
            text="✓ Using solid color background",
            text_color="green"
        )
        self._log("✓ Using solid color backdrop")
    
    def _on_upload_theme_music(self):
        """Handle uploading custom theme music."""
        filepath = filedialog.askopenfilename(
            title="Select Theme Music",
            filetypes=[
                ("Audio Files", "*.mp3 *.wav *.ogg *.m4a *.flac"),
                ("MP3", "*.mp3"),
                ("WAV", "*.wav"),
                ("All Files", "*.*")
            ]
        )
        
        if filepath:
            self.editor_theme_music_path = Path(filepath)
            self._jellyfin_theme_url = None  # Override Jellyfin URL
            self.music_status_label.configure(
                text=f"✓ Custom: {Path(filepath).name}",
                text_color="green"
            )
            self._log(f"✓ Custom theme music set: {Path(filepath).name}")
    
    def _on_clear_theme_music(self):
        """Clear theme music (use silent)."""
        self.editor_theme_music_path = None
        self._jellyfin_theme_url = None
        self.music_status_label.configure(
            text="No theme music (will be silent)",
            text_color="gray"
        )
        self._log("✓ Theme music cleared (will be silent)")
    
    def _on_preview_menu(self):
        """Generate and display a preview of the DVD menu."""
        if not self.editor_episodes:
            self._log("⚠ No episodes loaded. Select a season first.")
            return
        
        self._log("Generating menu preview...")
        
        def generate_preview():
            try:
                # Prepare episode thumbnails
                episode_thumbs = []
                for ep in self.editor_episodes:
                    thumb = EpisodeThumbnail(
                        episode_index=ep["index"],
                        title=ep["title"],
                        thumbnail_path=ep.get("thumbnail_path")
                    )
                    episode_thumbs.append(thumb)
                
                # Get backdrop path
                backdrop_path = None
                if self.editor_backdrop_path and self.editor_backdrop_path.exists():
                    backdrop_path = self.editor_backdrop_path
                elif hasattr(self, '_jellyfin_backdrop_url') and self._jellyfin_backdrop_url:
                    # Download from Jellyfin
                    backdrop_path = self.config.assets_dir / "preview_backdrop.jpg"
                    if self.jellyfin_client:
                        result = self.jellyfin_client.download_image(
                            self._jellyfin_backdrop_url,
                            backdrop_path
                        )
                        if result:
                            backdrop_path = result
                        else:
                            backdrop_path = None
                
                # Create menu config
                menu_style = MenuStyle.MODERN if self.style_var.get() == "Modern" else MenuStyle.RETRO
                menu_config = MenuConfig(
                    style=menu_style,
                    title=f"{self.selected_series.name} - {self.selected_season.name}" if self.selected_series and self.selected_season else "DVD Menu",
                    season_overview=self.selected_season.overview if self.selected_season and self.selected_season.overview else ""
                )
                
                # Generate menu image
                preview_dir = Path("/tmp/jellydisc_preview")
                preview_dir.mkdir(exist_ok=True)
                
                builder = MenuBuilder(preview_dir, menu_config)
                menu_path = builder.generate_menu_background(
                    backdrop_path=backdrop_path,
                    episodes=episode_thumbs
                )
                
                # Display in popup
                self.after(0, lambda: self._show_preview_popup(menu_path))
                
            except Exception as e:
                self.after(0, lambda: self._log(f"⚠ Preview generation failed: {e}"))
        
        threading.Thread(target=generate_preview, daemon=True).start()
    
    def _show_preview_popup(self, image_path: Path):
        """Show the menu preview in a popup window."""
        if not image_path.exists():
            self._log("⚠ Preview image not found")
            return
        
        # Create popup window
        popup = ctk.CTkToplevel(self)
        popup.title("Menu Preview")
        popup.geometry("800x550")
        popup.transient(self)
        popup.grab_set()
        
        # Load and display image
        from PIL import Image as PILImage
        
        img = PILImage.open(image_path)
        # Scale to fit popup while maintaining aspect ratio
        img.thumbnail((760, 480), PILImage.Resampling.LANCZOS)
        
        photo = ImageTk.PhotoImage(img)
        
        label = ctk.CTkLabel(popup, text="", image=photo)
        label.image = photo  # Keep a reference
        label.pack(padx=20, pady=20)
        
        # Close button
        close_btn = ctk.CTkButton(
            popup,
            text="Close Preview",
            command=popup.destroy
        )
        close_btn.pack(pady=10)
        
        self._log("✓ Menu preview displayed")
    
    def _on_confirm_and_proceed(self):
        """Confirm editor changes and proceed to authoring."""
        if not self.editor_episodes:
            self._log("⚠ No episodes loaded. Select a season first.")
            return
        
        # Update episode titles from editor entries
        for i, ep_data in enumerate(self.editor_episodes):
            if "_title_entry" in ep_data:
                ep_data["title"] = ep_data["_title_entry"].get()
        
        # Update config tab summary with edited data
        total_minutes = sum(ep["runtime_minutes"] for ep in self.editor_episodes)
        
        self.summary_label.configure(
            text=f"Series: {self.selected_series.name if self.selected_series else 'Unknown'}\n"
                 f"Season: {self.selected_season.name if self.selected_season else 'Unknown'}\n"
                 f"Episodes: {len(self.editor_episodes)}\n"
                 f"Total Runtime: {total_minutes:.0f} minutes\n"
                 f"(Using customized episode data from Editor)",
            text_color="white"
        )
        
        # Create disc plan
        self._create_disc_plan()
        
        # Switch to authoring tab
        self.tabview.set("Authoring")
        self._log("✓ Editor data confirmed. Proceed to Authoring settings.")

    def _create_config_tab(self):
        """Create the Authoring Config tab."""
        frame = ctk.CTkFrame(self.tab_config)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title = ctk.CTkLabel(
            frame,
            text="Authoring Configuration",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title.pack(pady=(0, 20))
        
        # Settings grid
        settings_frame = ctk.CTkFrame(frame, fg_color="transparent")
        settings_frame.pack(fill="x", pady=10)
        
        # Video Standard
        std_label = ctk.CTkLabel(settings_frame, text="Video Standard:")
        std_label.grid(row=0, column=0, sticky="e", padx=10, pady=10)
        
        self.standard_var = ctk.StringVar(value="NTSC")
        std_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["NTSC", "PAL"],
            variable=self.standard_var,
            width=200
        )
        std_dropdown.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        
        # Audio Language
        audio_label = ctk.CTkLabel(settings_frame, text="Audio Language:")
        audio_label.grid(row=1, column=0, sticky="e", padx=10, pady=10)
        
        self.audio_var = ctk.StringVar(value="English")
        audio_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["English", "Spanish", "French", "German", "Japanese", "Korean", "Chinese"],
            variable=self.audio_var,
            width=200
        )
        audio_dropdown.grid(row=1, column=1, sticky="w", padx=10, pady=10)
        
        # Include Subtitles
        self.subtitles_var = ctk.BooleanVar(value=True)
        subtitles_check = ctk.CTkCheckBox(
            settings_frame,
            text="Include Subtitles",
            variable=self.subtitles_var
        )
        subtitles_check.grid(row=2, column=1, sticky="w", padx=10, pady=10)
        
        # Menu Style
        style_label = ctk.CTkLabel(settings_frame, text="Menu Style:")
        style_label.grid(row=3, column=0, sticky="e", padx=10, pady=10)
        
        self.style_var = ctk.StringVar(value="Modern")
        style_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["Modern", "Retro"],
            variable=self.style_var,
            width=200
        )
        style_dropdown.grid(row=3, column=1, sticky="w", padx=10, pady=10)
        
        # Burn Speed
        speed_label = ctk.CTkLabel(settings_frame, text="Burn Speed:")
        speed_label.grid(row=4, column=0, sticky="e", padx=10, pady=10)
        
        self.speed_var = ctk.StringVar(value="4x")
        speed_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["1x", "2x", "4x", "8x", "16x"],
            variable=self.speed_var,
            width=200
        )
        speed_dropdown.grid(row=4, column=1, sticky="w", padx=10, pady=10)
        
        # Summary frame
        self.config_summary = ctk.CTkFrame(frame)
        self.config_summary.pack(fill="x", pady=20)
        
        self.summary_label = ctk.CTkLabel(
            self.config_summary,
            text="No season selected. Please select a season from the Library tab.",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.summary_label.pack(pady=20)
    
    def _create_burn_tab(self):
        """Create the Burn tab with progress tracking."""
        frame = ctk.CTkFrame(self.tab_burn)
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title = ctk.CTkLabel(
            frame,
            text="DVD Authoring & Burning",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title.pack(pady=(0, 20))
        
        # Disc info
        self.disc_info_frame = ctk.CTkFrame(frame)
        self.disc_info_frame.pack(fill="x", pady=10)
        
        self.disc_info_label = ctk.CTkLabel(
            self.disc_info_frame,
            text="No project loaded",
            font=ctk.CTkFont(size=14)
        )
        self.disc_info_label.pack(pady=15)
        
        # === Output Mode Selection ===
        output_mode_frame = ctk.CTkFrame(frame)
        output_mode_frame.pack(fill="x", pady=10)
        
        mode_label = ctk.CTkLabel(
            output_mode_frame,
            text="Output Mode:",
            font=ctk.CTkFont(size=14, weight="bold")
        )
        mode_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        # Toggle switch frame
        toggle_frame = ctk.CTkFrame(output_mode_frame, fg_color="transparent")
        toggle_frame.pack(fill="x", padx=10, pady=5)
        
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
        self.iso_options_frame.pack(fill="x", padx=10, pady=10)
        
        iso_path_label = ctk.CTkLabel(self.iso_options_frame, text="Save Location:")
        iso_path_label.pack(anchor="w", padx=10, pady=(5, 0))
        
        iso_path_inner = ctk.CTkFrame(self.iso_options_frame, fg_color="transparent")
        iso_path_inner.pack(fill="x", padx=10, pady=5)
        
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
        drive_label.pack(anchor="w", padx=10, pady=(5, 0))
        
        drive_inner = ctk.CTkFrame(self.burn_options_frame, fg_color="transparent")
        drive_inner.pack(fill="x", padx=10, pady=5)
        
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
        
        # Progress section
        progress_frame = ctk.CTkFrame(frame)
        progress_frame.pack(fill="x", pady=20)
        
        # Overall progress
        overall_label = ctk.CTkLabel(progress_frame, text="Overall Progress:")
        overall_label.pack(anchor="w", padx=10, pady=(10, 5))
        
        self.overall_progress = ctk.CTkProgressBar(progress_frame, width=600)
        self.overall_progress.pack(padx=10, pady=5)
        self.overall_progress.set(0)
        
        # Current task progress
        task_label = ctk.CTkLabel(progress_frame, text="Current Task:")
        task_label.pack(anchor="w", padx=10, pady=(15, 5))
        
        self.task_progress = ctk.CTkProgressBar(progress_frame, width=600)
        self.task_progress.pack(padx=10, pady=5)
        self.task_progress.set(0)
        
        self.task_status = ctk.CTkLabel(
            progress_frame,
            text="Ready",
            font=ctk.CTkFont(size=12),
            text_color="gray"
        )
        self.task_status.pack(pady=10)
        
        # Buttons
        button_frame = ctk.CTkFrame(frame, fg_color="transparent")
        button_frame.pack(pady=20)
        
        self.start_btn = ctk.CTkButton(
            button_frame,
            text="▶ Start",
            width=200,
            height=40,
            command=self._on_start,
            state="disabled"
        )
        self.start_btn.pack(side="left", padx=10)
        
        # Log output
        log_label = ctk.CTkLabel(frame, text="Log Output:")
        log_label.pack(anchor="w", padx=10)
        
        self.log_text = ctk.CTkTextbox(frame, height=120)
        self.log_text.pack(fill="x", padx=10, pady=5)
    
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
    
    def _on_start(self):
        """Handle Start button click - routes to ISO or Burn based on mode."""
        mode = self.output_mode_var.get()
        
        if mode == 0:  # Save ISO
            self._on_create_iso()
        else:  # Burn to Disc
            self._on_burn()
    
    def _check_dependencies(self):
        """Check for required system dependencies."""
        deps = check_transcoder_deps()
        burner_deps = check_burner_dependencies()
        
        missing = []
        
        if not deps.get("ffmpeg"):
            missing.append("ffmpeg")
        if not deps.get("ffprobe"):
            missing.append("ffprobe")
        
        if missing:
            self._log(f"⚠️ Missing dependencies: {', '.join(missing)}")
            self._log("Install with: sudo apt install ffmpeg")
        else:
            self._log("✓ All transcoding dependencies available")
        
        # Check ISO creation tools
        iso_tools = ["mkisofs", "genisoimage", "pycdlib"]
        has_iso = any(burner_deps.get(t) for t in iso_tools)
        
        if has_iso:
            self._log("✓ ISO creation available")
        else:
            self._log("⚠️ No ISO creation tool found")
    
    def _on_connect(self):
        """Handle connect button click."""
        url = self.url_entry.get().strip()
        username = self.user_entry.get().strip()
        password = self.pass_entry.get()
        
        if not url or not username or not password:
            self.connect_status.configure(text="Please fill in all fields", text_color="red")
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
                self.after(0, lambda: self._on_connect_success(server_name))
                
            except JellyfinConnectionError as e:
                self.after(0, lambda: self._on_connect_error(f"Connection failed: {e}"))
            except AuthenticationError as e:
                self.after(0, lambda: self._on_connect_error(f"Login failed: {e}"))
            except Exception as e:
                self.after(0, lambda: self._on_connect_error(f"Error: {e}"))
        
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
        self.tabview.set("Library")
    
    def _on_connect_error(self, message: str):
        """Handle connection error."""
        self.connect_btn.configure(state="normal", text="Connect")
        self.connect_status.configure(text=message, text_color="red")
        self._log(f"✗ {message}")
    
    def _load_tv_shows(self):
        """Load TV shows from Jellyfin."""
        if not self.jellyfin_client:
            return
        
        self._set_status("Loading TV shows...")
        
        def load():
            try:
                shows = self.jellyfin_client.get_tv_shows()
                self.after(0, lambda: self._populate_shows(shows))
            except Exception as e:
                self.after(0, lambda: self._log(f"Error loading shows: {e}"))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_shows(self, shows: list[Series]):
        """Populate the shows list."""
        # Clear existing widgets
        for widget in self.show_widgets:
            widget.destroy()
        self.show_widgets.clear()
        
        for show in shows:
            btn = ctk.CTkButton(
                self.shows_frame,
                text=f"📺 {show.name} ({show.year or 'N/A'})",
                anchor="w",
                command=lambda s=show: self._on_show_selected(s)
            )
            btn.pack(fill="x", pady=2)
            self.show_widgets.append(btn)
        
        self._set_status(f"Found {len(shows)} TV shows")
        self._log(f"✓ Loaded {len(shows)} TV shows")
    
    def _on_show_selected(self, series: Series):
        """Handle show selection."""
        self.selected_series = series
        self.season_label.configure(text=series.name)
        
        # Load seasons
        if not self.jellyfin_client:
            return
        
        self._set_status(f"Loading seasons for {series.name}...")
        
        def load():
            try:
                seasons = self.jellyfin_client.get_seasons(series.id)
                self.after(0, lambda: self._populate_seasons(seasons))
            except Exception as e:
                self.after(0, lambda: self._log(f"Error loading seasons: {e}"))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_seasons(self, seasons: list[Season]):
        """Populate the seasons dropdown."""
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
        
        # Load episodes
        if not self.jellyfin_client or not self.selected_series:
            return
        
        self._set_status(f"Loading episodes...")
        
        def load():
            try:
                episodes = self.jellyfin_client.get_episodes(
                    self.selected_series.id, 
                    season.id
                )
                season.episodes = episodes
                self.after(0, lambda: self._populate_episodes(episodes))
            except Exception as e:
                self.after(0, lambda: self._log(f"Error loading episodes: {e}"))
        
        threading.Thread(target=load, daemon=True).start()
    
    def _populate_episodes(self, episodes: list[Episode]):
        """Populate the episodes list."""
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
    
    def _on_author_season(self):
        """Handle author season button click - switches to Editor tab."""
        if not self.selected_season or not self.selected_series:
            return
        
        # Populate the editor tab with season data
        self._populate_editor_tab()
        
        # Switch to editor tab
        self.tabview.set("Editor")
        
        self._set_status(f"Edit assets for {self.selected_series.name} - {self.selected_season.name}")
    
    def _create_disc_plan(self):
        """Create a disc spanning plan for the selected season."""
        if not self.selected_season:
            return
        
        try:
            transcoder = Transcoder(self.config.staging_dir)
            
            jobs = []
            for ep in self.selected_season.episodes:
                job = TranscodeJob(
                    input_path=self.jellyfin_client.get_stream_url(ep.id) if self.jellyfin_client else "",
                    output_path=self.config.staging_dir / f"ep{ep.index_number:02d}.mpg",
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
            
            self._log(f"✓ Disc plan created: {num_discs} disc(s) required")
            
        except Exception as e:
            self._log(f"Error creating disc plan: {e}")
    
    def _on_create_iso(self):
        """Handle Create ISO button click."""
        if not self.disc_plans or not self.selected_season or not self.selected_series:
            return
        
        self.start_btn.configure(state="disabled")
        
        def process():
            try:
                self._run_authoring_pipeline(burn=False)
            except Exception as e:
                self.after(0, lambda: self._log(f"Error: {e}"))
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
            self._log("⚠️ No DVD drive selected. Please select a drive or use Save ISO mode.")
            return
        
        self.start_btn.configure(state="disabled")
        
        def process():
            try:
                self._run_authoring_pipeline(burn=True)
            except Exception as e:
                self.after(0, lambda: self._log(f"Error: {e}"))
            finally:
                self.after(0, lambda: self.start_btn.configure(state="normal"))
        
        threading.Thread(target=process, daemon=True).start()
    
    def _run_authoring_pipeline(self, burn: bool = False):
        """Run the full DVD authoring pipeline."""
        self._update_task("Initializing...", 0)
        self._update_overall(0)
        
        # Get settings
        video_standard = VideoStandard.NTSC if self.standard_var.get() == "NTSC" else VideoStandard.PAL
        menu_style = MenuStyle.MODERN if self.style_var.get() == "Modern" else MenuStyle.RETRO
        include_subs = self.subtitles_var.get()
        
        # Initialize components
        transcoder = Transcoder(
            self.config.staging_dir,
            VideoSettings(video_standard)
        )
        
        menu_config = MenuConfig(
            style=menu_style,
            title=f"{self.selected_series.name} - {self.selected_season.name}" if self.selected_series and self.selected_season else "DVD Menu",
            season_overview=self.selected_season.overview if self.selected_season and self.selected_season.overview else "",
            include_subtitles=include_subs
        )
        
        # Use custom theme music path if set from editor
        if self.editor_theme_music_path and self.editor_theme_music_path.exists():
            menu_config.audio_loop_path = self.editor_theme_music_path
        elif hasattr(self, '_jellyfin_theme_url') and self._jellyfin_theme_url and self.jellyfin_client:
            # Download theme from Jellyfin
            theme_path = self.config.assets_dir / "theme_music.mp3"
            try:
                result = self.jellyfin_client.download_image(self._jellyfin_theme_url, theme_path)
                if result:
                    menu_config.audio_loop_path = result
            except Exception:
                pass  # Silent menu if download fails
        
        menu_builder = MenuBuilder(self.config.staging_dir, menu_config)
        burner = Burner(self.config.output_dir)
        
        # Prepare backdrop path from editor
        backdrop_path = None
        if self.editor_backdrop_path and self.editor_backdrop_path.exists():
            backdrop_path = self.editor_backdrop_path
        elif hasattr(self, '_jellyfin_backdrop_url') and self._jellyfin_backdrop_url and self.jellyfin_client:
            # Download backdrop from Jellyfin
            backdrop_dl_path = self.config.assets_dir / "backdrop.jpg"
            result = self.jellyfin_client.download_image(self._jellyfin_backdrop_url, backdrop_dl_path)
            if result:
                backdrop_path = result
        
        iso_files = []
        
        for disc_plan in self.disc_plans:
            disc_num = disc_plan.disc_number
            self._log(f"\n=== Processing Disc {disc_num} of {len(self.disc_plans)} ===")
            
            # Step 1: Transcode episodes
            self._update_task(f"Disc {disc_num}: Transcoding episodes...", 0)
            
            total_episodes = len(disc_plan.episodes)
            transcoded_files = []
            
            for i, job in enumerate(disc_plan.episodes):
                # Use customized episode name from editor if available
                episode_name = job.episode_name
                for ed_ep in self.editor_episodes:
                    if ed_ep.get("index") == job.episode_index:
                        episode_name = ed_ep.get("title", job.episode_name)
                        break
                
                self._update_task(
                    f"Disc {disc_num}: Transcoding E{job.episode_index} ({i+1}/{total_episodes})",
                    i / total_episodes
                )
                self._log(f"Transcoding: {episode_name}")
                
                def transcode_progress(progress: float):
                    self.after(0, lambda p=progress: self.task_progress.set(
                        (i + p) / total_episodes
                    ))
                
                try:
                    transcoder.transcode(
                        job.input_path,
                        job.output_path,
                        progress_callback=transcode_progress,
                        extract_subs=include_subs
                    )
                    transcoded_files.append(job.output_path)
                except Exception as e:
                    self._log(f"⚠️ Transcode failed for {episode_name}: {e}")
            
            # Step 2: Generate menus - use editor data for customized titles/thumbnails
            self._update_task(f"Disc {disc_num}: Generating menus...", 0.5)
            self._log("Generating DVD menus...")
            
            episodes = []
            for job in disc_plan.episodes:
                # Find matching editor episode data
                ep_title = job.episode_name
                ep_thumb_path = None
                
                for ed_ep in self.editor_episodes:
                    if ed_ep.get("index") == job.episode_index:
                        ep_title = ed_ep.get("title", job.episode_name)
                        ep_thumb_path = ed_ep.get("thumbnail_path")
                        break
                
                episodes.append(EpisodeThumbnail(
                    episode_index=job.episode_index,
                    title=ep_title,
                    thumbnail_path=ep_thumb_path
                ))
            
            bg_path = menu_builder.generate_menu_background(
                backdrop_path=backdrop_path,
                episodes=episodes
            )
            hl_path = menu_builder.generate_highlight_mask(episodes)
            sel_path = menu_builder.generate_select_mask(episodes)
            
            # Step 3: Generate menu video
            self._update_task(f"Disc {disc_num}: Creating menu video...", 0.6)
            self._log("Creating menu video...")
            
            menu_video = menu_builder.generate_menu_video(bg_path)
            
            # Step 4: Generate dvdauthor XML
            self._update_task(f"Disc {disc_num}: Building DVD structure...", 0.7)
            self._log("Building DVD structure...")
            
            xml_path = menu_builder.generate_dvdauthor_xml(
                transcoded_files,
                menu_video,
                hl_path,
                sel_path
            )
            
            # Step 5: Build DVD structure
            try:
                dvd_dir = menu_builder.build_dvd_structure(xml_path)
            except Exception as e:
                self._log(f"⚠️ DVD structure build skipped (dvdauthor not available): {e}")
                dvd_dir = self.config.staging_dir
            
            # Step 6: Create ISO
            self._update_task(f"Disc {disc_num}: Creating ISO...", 0.8)
            self._log("Creating ISO image...")
            
            # Determine ISO output path
            # Use user-selected path for single-disc projects (both ISO and Burn modes use this path)
            if len(self.disc_plans) == 1:
                user_iso_path = self.iso_path_var.get()
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
                self.after(0, lambda: self._update_task(f"Disc {disc_num}: {status}", 0.8 + progress * 0.2))
            
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
                self._log(f"⚠️ ISO creation failed: {e}")
            
            self._update_overall(disc_num / len(self.disc_plans))
        
        # Step 7: Burn if requested
        if burn and iso_files:
            self._update_task("Burning to disc...", 0)
            
            # Get selected drive - extract device path from format "device_name (device_path)"
            drive_str = self.drive_var.get()
            device = None
            import re
            match = re.search(r'\(([^)]+)\)$', drive_str)
            if match:
                device = match.group(1)
            
            def burn_progress(disc: int, total: int, progress: float, status: str):
                self.after(0, lambda: self._update_task(f"Disc {disc}/{total}: {status}", progress))
            
            try:
                success = burner.burn_multi_disc(
                    iso_files,
                    device=device,
                    speed=int(self.speed_var.get().replace('x', '')),
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
    
    def _update_task(self, status: str, progress: float):
        """Update task progress display."""
        self.after(0, lambda: self.task_status.configure(text=status))
        self.after(0, lambda: self.task_progress.set(progress))
    
    def _update_overall(self, progress: float):
        """Update overall progress display."""
        self.after(0, lambda: self.overall_progress.set(progress))
    
    def _set_status(self, message: str):
        """Update the status bar."""
        self.status_label.configure(text=message)
    
    def _log(self, message: str):
        """Add message to log output."""
        def update():
            self.log_text.insert("end", message + "\n")
            self.log_text.see("end")
        
        self.after(0, update)


def main():
    """Run the JellyDisc application."""
    if not GUI_AVAILABLE:
        print("Error: GUI dependencies not available.")
        print(f"Missing: {GUI_ERROR}")
        print("\nTo install GUI dependencies:")
        print("  pip install customtkinter Pillow")
        print("\nOn Linux, you may also need:")
        print("  sudo apt install python3-tk")
        sys.exit(1)
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    app = JellyDiscApp()
    app.mainloop()


if __name__ == "__main__":
    main()
