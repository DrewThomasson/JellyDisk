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
        
        self.title("JellyDisc - DVD Authoring Suite")
        self.geometry("1000x780")
        self.minsize(800, 680)
        
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
    
    def _create_ui(self):
        """Create the main UI layout."""
        # Create tab view
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Add tabs
        self.tab_connect = self.tabview.add("Connect")
        self.tab_library = self.tabview.add("Library")
        self.tab_config = self.tabview.add("Authoring")
        self.tab_burn = self.tabview.add("Burn")
        
        # Build each tab
        self._create_connect_tab()
        self._create_library_tab()
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
        
        # Include Trailer
        self.trailer_var = ctk.BooleanVar(value=True)
        trailer_check = ctk.CTkCheckBox(
            settings_frame,
            text="Include Trailer (if available)",
            variable=self.trailer_var
        )
        trailer_check.grid(row=3, column=1, sticky="w", padx=10, pady=10)
        
        # Menu Style
        style_label = ctk.CTkLabel(settings_frame, text="Menu Style:")
        style_label.grid(row=4, column=0, sticky="e", padx=10, pady=10)
        
        self.style_var = ctk.StringVar(value="Modern")
        style_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["Modern", "Retro"],
            variable=self.style_var,
            width=200
        )
        style_dropdown.grid(row=4, column=1, sticky="w", padx=10, pady=10)
        
        # Burn Speed
        speed_label = ctk.CTkLabel(settings_frame, text="Burn Speed:")
        speed_label.grid(row=5, column=0, sticky="e", padx=10, pady=10)
        
        self.speed_var = ctk.StringVar(value="4x")
        speed_dropdown = ctk.CTkComboBox(
            settings_frame,
            values=["1x", "2x", "4x", "8x", "16x"],
            variable=self.speed_var,
            width=200
        )
        speed_dropdown.grid(row=5, column=1, sticky="w", padx=10, pady=10)
        
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
        frame.pack(fill="both", expand=True, padx=20, pady=10)
        
        # Title
        title = ctk.CTkLabel(
            frame,
            text="DVD Authoring & Burning",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title.pack(pady=(0, 10))
        
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
                    self.after(0, lambda: self._update_task(status, progress))
                    
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
                self.after(0, lambda: self._log(f"⚠️ Erase error: {e}"))
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
        """Populate the shows list on initial load."""
        self.all_shows = shows
        self._populate_search_results(shows, "")
        self._set_status(f"Found {len(shows)} TV shows")
        self._log(f"✓ Loaded {len(shows)} TV shows")

    def _on_search_changed(self, *args):
        """Called when search text changes (debounced search)."""
        if hasattr(self, "_search_timer_id") and self._search_timer_id:
            self.after_cancel(self._search_timer_id)
            
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
                # Verify the query hasn't changed since this thread started
                if self.search_var.get().strip() == query:
                    self.after(0, lambda: self._populate_search_results(results, query))
            except Exception as e:
                self.after(0, lambda: self._log(f"Search error: {e}"))
                
        threading.Thread(target=run_search, daemon=True).start()

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
        self.season_label.configure(text=series.name)
        
        # Load seasons and detailed metadata
        if not self.jellyfin_client:
            return
        
        self._set_status(f"Loading details for {series.name}...")
        
        def load():
            try:
                # Fetch detailed metadata (actors & full overview) asynchronously
                try:
                    details = self.jellyfin_client.get_item_details(series.id)
                    actors = []
                    for person in details.get("People", []):
                        if person.get("Type") == "Actor":
                            name = person.get("Name")
                            role = person.get("Role")
                            if role:
                                actors.append(f"{name} as {role}")
                            else:
                                actors.append(name)
                    series.actors = actors[:10]
                    series.overview = details.get("Overview", "")
                except Exception as ex:
                    logger.warning(f"Failed to fetch item details: {ex}")
                
                # Fetch seasons list
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
        self.tabview.set("Authoring")
    
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

    def _create_disc_plan(self):
        """Create a disc spanning plan for the selected season."""
        if not self.selected_season:
            return
        
        try:
            transcoder = Transcoder(self.current_staging_dir)
            
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
        include_trailer = self.trailer_var.get()
        
        # Initialize components
        transcoder = Transcoder(
            self.current_staging_dir,
            VideoSettings(video_standard)
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
            include_trailer=include_trailer
        )
        
        menu_builder = MenuBuilder(self.current_staging_dir, menu_config)
        burner = Burner(self.config.output_dir)
        
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
                    self._log("No local trailers found on server for this item.")
            except Exception as e:
                self._log(f"⚠️ Failed to retrieve/process trailer: {e}")
                trailer_path = None

        iso_files = []
        
        for disc_plan in self.disc_plans:
            disc_num = disc_plan.disc_number
            self._log(f"\n=== Processing Disc {disc_num} of {len(self.disc_plans)} ===")
            
            # Calculate optimal bitrate for this specific disc
            disc_bitrate = transcoder.calculate_optimal_bitrate(disc_plan.total_minutes)
            
            # Step 1: Transcode episodes
            self._update_task(f"Disc {disc_num}: Transcoding episodes...", 0.7)
            
            total_episodes = len(disc_plan.episodes)
            transcoded_files = []
            
            for i, job in enumerate(disc_plan.episodes):
                self._update_task(
                    f"Disc {disc_num}: Processing E{job.episode_index} ({i+1}/{total_episodes})",
                    i / total_episodes
                )
                
                if job.output_path.exists() and job.output_path.stat().st_size > 10 * 1024 * 1024:
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
                    transcoded_files.append(job.output_path)
                    self._log(f"✓ E{job.episode_index} completed.")
                    
                except Exception as e:
                    self._log(f"⚠️ Transcode failed for {job.episode_name}: {e}")
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
                backdrop_path, logo_path, has_trailer=has_trailer, show_episode_select=show_ep_select
            )
            m_base_vid = menu_builder.generate_menu_video(m_bg, "menu_main_base.mpg", theme_path)
            menu_main_vid = menu_builder.compile_interactive_menu(
                m_base_vid, m_hl, m_sel, m_btns, menu_builder.output_dir / "menu_main.mpg"
            )
            
            # Step 3.5: Generate Cast & Info Menu (Optional)
            menu_cast_vid = None
            if menu_config.include_cast:
                self._update_task(f"Disc {disc_num}: Generating Cast Menu...", 0.55)
                self._log("Generating Cast & Info Menu...")
                c_bg, c_hl, c_sel, c_btns = menu_builder.generate_cast_menu(
                    backdrop_path,
                    logo_path,
                    overview=self.selected_series.overview or "",
                    actors=menu_config.actors
                )
                c_base_vid = menu_builder.generate_menu_video(c_bg, "menu_cast_base.mpg")
                menu_cast_vid = menu_builder.compile_interactive_menu(
                    c_base_vid, c_hl, c_sel, c_btns, menu_builder.output_dir / "menu_cast.mpg"
                )
            
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
            
            # Step 5: Generate dvdauthor XML
            self._update_task(f"Disc {disc_num}: Building DVD structure...", 0.75)
            self._log("Building DVD structure...")
            
            xml_path = menu_builder.generate_dvdauthor_xml(
                transcoded_files,
                menu_main_vid,
                menu_episode_vids,
                menu_cast_path=menu_cast_vid,
                menu_trailer_path=disc_trailer_path
            )
            
            # Step 6: Build DVD structure
            try:
                dvd_dir = menu_builder.build_dvd_structure(xml_path)
            except Exception as e:
                self._log(f"⚠️ DVD structure build skipped (dvdauthor failed or not available): {e}")
                dvd_dir = self.current_staging_dir
            
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
