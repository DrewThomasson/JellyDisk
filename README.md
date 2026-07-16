# JellyDisk

An automated DVD authoring suite that connects to your Jellyfin server, downloads TV show seasons, and creates commercial-grade DVD ISOs with interactive menus, metadata, and subtitles.

> [!IMPORTANT]
> Want to see what show's dvd would look like without burning an ISO? Checkout the [JellyDisk Web Interface](JellyDiskWeb/README.md)

<img width="5712" height="4284" alt="IMG_2098" src="https://github.com/user-attachments/assets/0e3f5a7c-2b64-4552-bf19-54656681f7da" />
<img width="5712" height="4284" alt="IMG_2095" src="https://github.com/user-attachments/assets/e26b6e79-5218-4838-be1e-cc80e9dda3c6" />
<img width="5712" height="4284" alt="IMG_2094" src="https://github.com/user-attachments/assets/7e1df3df-df37-4800-a380-b93632dcd6ed" />

<img width="5712" height="4284" alt="IMG_2100" src="https://github.com/user-attachments/assets/7d0f1644-f6dc-4696-a559-1e4db4f0e80e" />


[Smiling Friends_Season 1_Episode_Guide.pdf](https://github.com/user-attachments/files/29831463/Smiling.Friends_Season.1_Episode_Guide.pdf)


[Smiling Friends_Season 1_Disc_1_Label.pdf](https://github.com/user-attachments/files/29831461/Smiling.Friends_Season.1_Disc_1_Label.pdf)


[Smiling Friends_Season 1_DVD_Cover.pdf](https://github.com/user-attachments/files/29831462/Smiling.Friends_Season.1_DVD_Cover.pdf)




## Features

- **Jellyfin Integration**: Connect to your Jellyfin media server to browse and select TV shows and seasons.
- **Automatic Transcoding**: Convert media to DVD-compliant MPEG-2 format with optimal bitrate calculation scaled to fit the entire disc.
- **Professional Menus**: Generate paginated DVD menus with show artwork, episode select thumbnails, cast info pages, and theme music loops.
- **Subtitle Support**: Extract and render subtitles as DVD-compliant bitmap overlays (soft-subs) or hardcode them directly.
- **Erase Utilities**: Wipes and formats rewritable media (`DVD-RW` / `CD-RW`) directly from the UI.
- **Cross-Platform Burner**: Integrated burner utility using `hdiutil` (macOS), `growisofs`/`wodim` (Linux), and `ImgBurn` (Windows).
- **Apple Silicon Optimized**: Automatically bypasses macOS `Inappropriate ioctl` USB power drive bugs on Apple Silicon (M-series) Macs during burning.
- **ISO Export**: Generate clean DVD ISO files for previewing or storage.
- **Printable Cover Art, Booklets & Disc Labels**: Automatically generate high-resolution, print-ready PDF box covers (front, spine, back), multi-page episode guide booklets, and circular CD/DVD disc face labels based on Jellyfin metadata.

## Requirements

### Python
- Python 3.12+

### System Dependencies
- `ffmpeg` - Media transcoding. **Note:** If you want subtitle support, your `ffmpeg` binary must be compiled with `--enable-libass` (which is included by default in standard packages installed via Ubuntu `apt` or macOS `brew`, but may be missing in minimal or custom builds like Linuxbrew's default recipe).
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
sudo apt install ffmpeg dvdauthor dvd+rw-tools wodim yt-dlp
```

**macOS (Homebrew):**
```bash
brew install ffmpeg dvdauthor yt-dlp
```

**Windows:**
Download ffmpeg from https://ffmpeg.org/download.html, dvdauthor from available Windows ports, and yt-dlp from https://github.com/yt-dlp/yt-dlp.
*(Note: `yt-dlp` is optional, and is only needed if you want to download remote YouTube trailers for your menus).*

## Usage

### Running the Desktop Application

Make sure your virtual environment is active, then launch the main GUI application:
```bash
python -m jellydisc.main
```
### Running in Headless CLI Mode

JellyDisc can be run completely headless from the command line (ideal for home servers like Unraid, TrueNAS, or remote Linux boxes).

To view all command line options and arguments:
```bash
python -m jellydisc.main --help
```

#### Automate DVD Creation
To fetch, transcode, build DVD menus, generate ISOs, and print cover art in a single command:
```bash
python -m jellydisc.main --headless \
  --server "https://yourjellyfin.com" \
  --username "User" \
  --password "Password" \
  --show "Smiling Friends" \
  --season "Season 1"
```

#### Automate Erasing and Burning
To automatically erase a rewritable disc (`DVD-RW` / `CD-RW`) and burn the resulting ISOs directly to a specific burner:
```bash
python -m jellydisc.main --headless \
  --server "https://yourjellyfin.com" \
  --username "User" \
  --password "Password" \
  --show "Smiling Friends" \
  --season "Season 1" \
  --erase \
  --burn \
  --drive "/dev/rdisk4" \
  --speed 4
```

#### Standalone Disc Utilities
* **List detected optical drives:**
  ```bash
  python -m jellydisc.main --list-drives
  ```
* **Erase/Format a rewritable disc:**
  ```bash
  python -m jellydisc.main --erase --drive "/dev/rdisk4"
  ```

### Running via Docker (Compose)

JellyDisc is fully dockerized and supports a guided **Interactive Terminal Wizard** so you can author DVDs without needing to install Python, FFmpeg, or `dvdauthor` on your host machine.

#### 1. Setup Environment Credentials (Optional)
To avoid typing your credentials, create a `.env` file in the root directory:
```env
JELLYFIN_URL=https://your-jellyfin-server.com
JELLYFIN_USER=your_username
JELLYFIN_PASS=your_password
```

#### 2. Run the Interactive Wizard
Simply execute the container:
```bash
docker compose run --rm jellydisc
```
This will start the interactive setup wizard inside your terminal, prompting you to search for a media title, choose a season, configure subtitles, and select options.

#### 3. Run directly with CLI Flags
If you want to run it headlessly without the interactive prompts, supply standard CLI flags:
```bash
docker compose run --rm jellydisc --show "Smiling Friends" --season "2"
```

#### 4. Burning to Physical Discs (Linux/Ubuntu only)
Uncomment the `devices` configuration in your `docker-compose.yml` file to expose `/dev/sr0` to the container, then run:
```bash
docker compose run --rm jellydisc --show "Smiling Friends" --season "2" --burn --drive "/dev/sr0"
```
*(Note: Docker Desktop for macOS/Windows does not support optical drive device passthrough. You must compile the ISO inside Docker and burn it on the host instead).*

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

## Printing Guidelines

All generated artwork PDFs are configured at high-resolution **300 DPI** to match standard optical media packaging sizes exactly:

- **DVD Cover Wrap:** 273mm x 183mm (Fits standard 14mm spine DVD cases).
- **Episode Booklet:** 120mm x 180mm (Fits booklet clips inside standard DVD cases).
- **Disc Label:** 118mm x 118mm (Standard printable CD/DVD disc face size).

> [!IMPORTANT]
> When printing the generated PDFs, you **must** configure your printer settings as follows:
> - Set **Page Scaling / Scale** to **"Actual Size"** or **"100%"**.
> - Do **not** select *"Fit to Page"*, *"Scale to Fit"*, or *"Shrink to Fit"*, as this will stretch the images to fill the entire sheet of paper, making them too large to fit in your DVD cases.

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
