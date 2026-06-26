# JellyDisk

An automated DVD authoring suite that connects to your Jellyfin server, downloads TV show seasons, and creates commercial-grade DVD ISOs with interactive menus, metadata, and subtitles.

## Features

- **Jellyfin Integration**: Connect to your Jellyfin media server to browse and select TV shows and seasons.
- **Automatic Transcoding**: Convert media to DVD-compliant MPEG-2 format with optimal bitrate calculation scaled to fit the entire disc.
- **Professional Menus**: Generate paginated DVD menus with show artwork, episode select thumbnails, cast info pages, and theme music loops.
- **Subtitle Support**: Extract and render subtitles as DVD-compliant bitmap overlays (soft-subs) or hardcode them directly.
- **Erase Utilities**: Wipes and formats rewritable media (`DVD-RW` / `CD-RW`) directly from the UI.
- **Cross-Platform Burner**: Integrated burner utility using `hdiutil` (macOS), `growisofs`/`wodim` (Linux), and `ImgBurn` (Windows).
- **Apple Silicon Optimized**: Automatically bypasses macOS `Inappropriate ioctl` USB power drive bugs on Apple Silicon (M-series) Macs during burning.
- **ISO Export**: Generate clean DVD ISO files for previewing or storage.

## Requirements

### Python
- Python 3.12+

### System Dependencies
- `ffmpeg` - Media transcoding
- `dvdauthor` - DVD structure creation
- `spumux` (part of dvdauthor) - Subtitle and interactive highlight rendering

### Optional (for burning)
- **Windows**: ImgBurn
- **Linux**: growisofs / dvd+rw-format / wodim
- **Mac**: hdiutil (built-in) / drutil (built-in)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/DrewThomasson/JellyDisk.git
cd JellyDisk
```

2. Create a virtual environment and install dependencies:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

3. Install system dependencies:

**Ubuntu/Debian:**
```bash
sudo apt install ffmpeg dvdauthor dvd+rw-tools wodim
```

**macOS (Homebrew):**
```bash
brew install ffmpeg dvdauthor
```

**Windows:**
Download ffmpeg from https://ffmpeg.org/download.html and dvdauthor from available Windows ports.

## Usage

### Running the Desktop Application

Make sure your virtual environment is active, then launch the main GUI application:
```bash
python -m jellydisc.main
```

### Project Structure

```
JellyDisc/
├── assets/          # Downloaded images and theme songs
├── staging/         # Temporary transcoded MPEG files and DVD author folders
├── output/          # Final DVD ISO files
├── jellydisc/       # Main package
│   ├── __init__.py
│   ├── main.py      # CustomTkinter GUI & Authoring pipeline
│   ├── burner.py    # Cross-platform disc burner & eraser
│   ├── transcoder.py# FFmpeg wrapper and bitrate manager
│   ├── menu_builder.py # Menu image and spumux generator
│   └── jellyfin_client.py # Connection client
├── requirements.txt
└── README.md
```

## Development Roadmap

- [x] **Phase 1: Scaffolding**
  - [x] Project structure
  - [x] Requirements
  - [x] Jellyfin client module
- [x] **Phase 2: The Engine**
  - [x] Transcoder (ffmpeg wrapper)
  - [x] Bitrate scaling and disc spanning
  - [x] Menu builder (Pillow + dvdauthor + spumux highlights)
- [x] **Phase 3: The UI**
  - [x] Login screen
  - [x] Library browser & visual poster previews
  - [x] Authoring & burn dashboard with log console
- [x] **Phase 4: Output**
  - [x] ISO creation
  - [x] Standalone disc erasing tool
  - [x] Cross-platform burner integration (hdiutil, ImgBurn, growisofs)

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
