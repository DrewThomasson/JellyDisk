<p align="center">
  <img src="docs/jellydisk-logo.png" alt="JellyDisk" width="760">
</p>

<p align="center">Turn a Jellyfin movie or TV season into a real DVD.</p>

<p align="center">
  <a href="https://github.com/DrewThomasson/JellyDisk/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/DrewThomasson/JellyDisk?style=flat-square&color=7c5cff"></a>
  <a href="LICENSE"><img alt="Apache 2.0 license" src="https://img.shields.io/badge/license-Apache--2.0-20b8cd?style=flat-square"></a>
  <img alt="Python 3.12+" src="https://img.shields.io/badge/Python-3.12%2B-3776ab?style=flat-square&logo=python&logoColor=white">
</p>

JellyDisk pulls media and metadata from Jellyfin, converts the video to
DVD-compatible MPEG-2, builds interactive menus, and writes an ISO. It can also
make the printable case wrap, booklet, and disc labels.

Use the desktop app for the full visual workflow. The CLI and Docker image are
available for servers and automation.

## What it makes

- DVD-Video ISOs with episode, cast, subtitle, trailer, and trivia menus
- Multi-disc sets when a season does not fit on one DVD
- Multi-season projects that keep each season in its own disc set
- Printable case wraps, episode booklets, and disc labels
- DVD-5 or DVD-9 output in NTSC or PAL

The live preview lets you inspect the package artwork, rotate the open case,
switch between discs and seasons, and try the DVD menu before starting a build.

> [!TIP]
> Want to explore the menu without authoring a disc? See the
> [JellyDisk Web Interface](JellyDiskWeb/README.md).

## Screenshots

<table>
  <tr>
    <td width="50%"><img alt="JellyDisk DVD menu on a television" src="https://github.com/user-attachments/assets/0e3f5a7c-2b64-4552-bf19-54656681f7da"></td>
    <td width="50%"><img alt="JellyDisk episode selection menu" src="https://github.com/user-attachments/assets/e26b6e79-5218-4838-be1e-cc80e9dda3c6"></td>
  </tr>
  <tr>
    <td width="50%"><img alt="JellyDisk authored DVD playback" src="https://github.com/user-attachments/assets/7e1df3df-df37-4800-a380-b93632dcd6ed"></td>
    <td width="50%"><img alt="JellyDisk physical DVD package" src="https://github.com/user-attachments/assets/7d0f1644-f6dc-4696-a559-1e4db4f0e80e"></td>
  </tr>
</table>

Sample files:
[episode booklet](https://github.com/user-attachments/files/29831463/Smiling.Friends_Season.1_Episode_Guide.pdf)
· [disc label](https://github.com/user-attachments/files/29831461/Smiling.Friends_Season.1_Disc_1_Label.pdf)
· [case wrap](https://github.com/user-attachments/files/29831462/Smiling.Friends_Season.1_DVD_Cover.pdf)

## Install

JellyDisk requires Python 3.12 or newer.

```bash
git clone https://github.com/DrewThomasson/JellyDisk.git
cd JellyDisk

python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

It also needs FFmpeg and dvdauthor:

**Ubuntu or Debian**

```bash
sudo apt install ffmpeg dvdauthor dvd+rw-tools wodim yt-dlp
```

**macOS with Homebrew**

```bash
brew install ffmpeg dvdauthor yt-dlp
```

**Windows**

Install [FFmpeg](https://ffmpeg.org/download.html) and a Windows build of
dvdauthor. [yt-dlp](https://github.com/yt-dlp/yt-dlp) is optional and is only
used for remote trailers.

Subtitle rendering requires an FFmpeg build with `libass`. The standard
Homebrew and Debian/Ubuntu packages include it.

## Desktop app

Start JellyDisk with the virtual environment active:

```bash
python -m jellydisc.main
```

Then:

1. Connect to Jellyfin. Enable **Remember login securely** if you want JellyDisk
   to use Keychain, Windows Credential Manager, or your Linux secret service.
2. Browse or search the library and choose one or more seasons.
3. Check the package and menu in Live Preview.
4. Choose ISO or physical-disc output and start the build.

JellyDisk keeps downloaded artwork and transcoded files in `assets/` and
`staging/`. Finished files are written to `output/`.

## Command line

Run the guided terminal workflow:

```bash
python -m jellydisc.main --headless
```

Or provide everything in one command:

```bash
python -m jellydisc.main --headless \
  --server "https://jellyfin.example.com" \
  --username "User" \
  --password "Password" \
  --show "Smiling Friends" \
  --season "Season 1"
```

Passing a password as an argument may expose it in shell history. For repeated
local use, save it in the system credential vault:

```bash
python -m jellydisc.main --headless --save-login \
  --server "https://jellyfin.example.com" \
  --username "User" \
  --show "Smiling Friends" \
  --season "Season 1"

python -m jellydisc.main --headless --use-saved-login \
  --show "Smiling Friends" --season "Season 1"
```

Remove the saved login with `--forget-login`. Run
`python -m jellydisc.main --help` for all authoring and burning options.

Disc utilities:

```bash
python -m jellydisc.main --list-drives
python -m jellydisc.main --erase --drive "/dev/rdisk4"
```

## Docker

Docker is useful for headless ISO creation because FFmpeg and dvdauthor are
already included:

```bash
docker compose run --rm jellydisc
```

You can supply credentials through the shell or a local `.env` file:

```env
JELLYFIN_URL=https://jellyfin.example.com
JELLYFIN_USER=your_username
JELLYFIN_PASS=your_password
```

Then run a non-interactive build:

```bash
docker compose run --rm jellydisc \
  --show "Smiling Friends" --season "Season 2"
```

Linux can expose an optical drive to the container by adding it under
`devices` in `docker-compose.yml`. Docker Desktop on macOS and Windows does not
support optical-drive passthrough; create the ISO in Docker and burn it from
the host.

## Printing the artwork

The PDFs are generated at 300 DPI for standard DVD packaging:

| File | Size |
| --- | --- |
| Case wrap | 273 × 183 mm, including a 14 mm spine |
| Episode booklet | 120 × 180 mm |
| Disc label | 118 × 118 mm |

Print at **Actual Size** or **100%**. Disable “Fit to Page,” “Scale to Fit,” and
similar options or the artwork will not fit the case.

## License

JellyDisk is licensed under the [Apache License 2.0](LICENSE).
