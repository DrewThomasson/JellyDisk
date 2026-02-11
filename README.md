# JellyDisk

An automated DVD authoring suite that connects to your Jellyfin server, downloads TV show seasons, and creates commercial-grade DVD ISOs with interactive menus, metadata, and subtitles.

## Features

- **Jellyfin Integration**: Connect to your Jellyfin media server to browse and select TV shows
- **Automatic Transcoding**: Convert media to DVD-compliant MPEG-2 format with optimized bitrate
- **Professional Menus**: Generate DVD menus with show artwork, episode selection, and theme music
- **Subtitle Support**: Extract and render subtitles as DVD-compliant bitmap overlays
- **Cross-Platform**: Works on Windows, Mac, and Linux
- **ISO Export**: Create ISO images for testing without burning physical discs

## Requirements

### Python
- Python 3.12+

### System Dependencies
- `ffmpeg` - Media transcoding
- `dvdauthor` - DVD structure creation
- `spumux` (part of dvdauthor) - Subtitle rendering

### Optional (for burning)
- **Windows**: ImgBurn
- **Linux**: growisofs
- **Mac**: hdiutil (built-in)

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
sudo apt install ffmpeg dvdauthor
```

**macOS (Homebrew):**
```bash
brew install ffmpeg dvdauthor
```

**Windows:**
Download ffmpeg from https://ffmpeg.org/download.html and dvdauthor from available Windows ports.

## Usage

### Testing Jellyfin Connection

Set environment variables and run the client test:
```bash
export JELLYFIN_URL='http://your-server:8096'
export JELLYFIN_USER='your-username'
export JELLYFIN_PASS='your-password'

python -m jellydisc.jellyfin_client
```

### Project Structure

```
JellyDisc/
├── assets/          # Downloaded images and theme songs
├── staging/         # Temporary transcoded MPEG files
├── output/          # Final DVD ISO files
├── jellydisc/       # Main package
│   ├── __init__.py
│   └── jellyfin_client.py
├── requirements.txt
└── README.md
```

## Development Roadmap

- [x] **Phase 1: Scaffolding**
  - [x] Project structure
  - [x] Requirements
  - [x] Jellyfin client module

- [ ] **Phase 2: The Engine**
  - [ ] Transcoder (ffmpeg wrapper)
  - [ ] Menu builder (Pillow + dvdauthor)

- [ ] **Phase 3: The UI**
  - [ ] Login screen
  - [ ] Library browser
  - [ ] Burn dashboard

- [ ] **Phase 4: Output**
  - [ ] ISO creation
  - [ ] Cross-platform burner integration

## License

Apache License 2.0 - See [LICENSE](LICENSE) for details.
