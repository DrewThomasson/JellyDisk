"""
Transcoder Module

This module provides FFmpeg-based transcoding functionality to convert
media files to DVD-compliant MPEG-2 format with proper audio encoding.
"""

import os
import logging
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

try:
    import ffmpeg
except ImportError:
    ffmpeg = None

logger = logging.getLogger(__name__)


class VideoStandard(Enum):
    """DVD video standards."""
    NTSC = "ntsc"
    PAL = "pal"


@dataclass
class VideoSettings:
    """Video encoding settings for DVD compliance."""
    standard: VideoStandard = VideoStandard.NTSC
    
    @property
    def resolution(self) -> tuple[int, int]:
        """Get resolution for the video standard."""
        if self.standard == VideoStandard.NTSC:
            return (720, 480)
        return (720, 576)  # PAL
    
    @property
    def framerate(self) -> str:
        """Get framerate for the video standard."""
        if self.standard == VideoStandard.NTSC:
            return "30000/1001"  # 29.97 fps
        return "25"  # 25 fps for PAL
    
    @property
    def aspect_ratio(self) -> str:
        """Get aspect ratio string."""
        return "16:9"


@dataclass
class AudioSettings:
    """Audio encoding settings for DVD compliance."""
    codec: str = "ac3"  # Dolby Digital
    channels: int = 2  # Stereo (can be 6 for 5.1)
    bitrate: str = "192k"
    sample_rate: int = 48000


@dataclass 
class TranscodeJob:
    """Represents a single transcode job."""
    input_path: str
    output_path: Path
    episode_name: str
    episode_index: int
    duration_seconds: float = 0.0
    
    # Status tracking
    progress: float = 0.0
    status: str = "pending"
    error_message: Optional[str] = None


@dataclass
class DiscPlan:
    """Plan for splitting content across multiple discs."""
    disc_number: int
    episodes: list[TranscodeJob]
    total_minutes: float
    estimated_size_mb: float


class TranscoderError(Exception):
    """Base exception for transcoder errors."""
    pass


class FFmpegNotFoundError(TranscoderError):
    """Raised when FFmpeg binary is not found."""
    pass


class TranscodeFailedError(TranscoderError):
    """Raised when transcoding fails."""
    pass


class Transcoder:
    """
    FFmpeg-based transcoder for converting media to DVD-compliant format.
    
    Converts video files to MPEG-2 with AC3 audio suitable for DVD authoring.
    Includes smart bitrate calculation to maximize quality within disc limits.
    """
    
    # DVD capacity in bytes (4.7 GB single-layer, using 4.5 GB for safety)
    DVD_CAPACITY_BYTES = 4.5 * 1024 * 1024 * 1024
    DVD_CAPACITY_MB = 4500
    
    # Reserved space for menus and overhead (MB)
    MENU_OVERHEAD_MB = 100
    
    def __init__(
        self,
        staging_dir: Path,
        video_settings: Optional[VideoSettings] = None,
        audio_settings: Optional[AudioSettings] = None
    ):
        """
        Initialize the transcoder.
        
        Args:
            staging_dir: Directory to store transcoded files
            video_settings: Video encoding settings (defaults to NTSC)
            audio_settings: Audio encoding settings (defaults to AC3 stereo)
        """
        self.staging_dir = Path(staging_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        
        self.video_settings = video_settings or VideoSettings()
        self.audio_settings = audio_settings or AudioSettings()
        
        # Verify FFmpeg is available
        self._ffmpeg_path = self._find_ffmpeg()
        self._ffprobe_path = self._find_ffprobe()
        
    def _find_ffmpeg(self) -> str:
        """Find the FFmpeg binary path."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            raise FFmpegNotFoundError(
                "FFmpeg not found. Please install FFmpeg:\n"
                "  Ubuntu/Debian: sudo apt install ffmpeg\n"
                "  macOS: brew install ffmpeg\n"
                "  Windows: Download from https://ffmpeg.org/download.html"
            )
        return ffmpeg_path
    
    def _find_ffprobe(self) -> str:
        """Find the FFprobe binary path."""
        ffprobe_path = shutil.which("ffprobe")
        if not ffprobe_path:
            raise FFmpegNotFoundError(
                "FFprobe not found. Please install FFmpeg (includes ffprobe)."
            )
        return ffprobe_path
    
    def get_media_duration(self, input_path: str) -> float:
        """
        Get duration of a media file in seconds.
        
        Args:
            input_path: Path or URL to the input media
            
        Returns:
            Duration in seconds
        """
        try:
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    input_path
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                logger.warning(f"Could not get duration for {input_path}: {result.stderr}")
                return 0.0
            
            return float(result.stdout.strip())
            
        except (subprocess.TimeoutExpired, ValueError) as e:
            logger.warning(f"Error getting duration: {e}")
            return 0.0
    
    def get_media_info(self, input_path: str) -> dict:
        """
        Get detailed media information.
        
        Args:
            input_path: Path or URL to the input media
            
        Returns:
            Dictionary with media info (duration, video_codec, audio_codec, etc.)
        """
        try:
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "error",
                    "-show_entries", 
                    "format=duration,size,bit_rate:stream=codec_type,codec_name,width,height,channels,sample_rate",
                    "-of", "json",
                    input_path
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode != 0:
                return {}
            
            import json
            return json.loads(result.stdout)
            
        except (subprocess.TimeoutExpired, ValueError) as e:
            logger.warning(f"Error getting media info: {e}")
            return {}
    
    def calculate_optimal_bitrate(
        self,
        total_duration_minutes: float,
        available_space_mb: Optional[float] = None
    ) -> int:
        """
        Calculate optimal video bitrate to fit content on disc.
        
        Uses the formula: bitrate = (available_space * 8) / (duration * 60)
        
        Args:
            total_duration_minutes: Total duration of all content in minutes
            available_space_mb: Available space in MB (defaults to DVD capacity minus overhead)
            
        Returns:
            Optimal video bitrate in bits per second
        """
        if available_space_mb is None:
            available_space_mb = self.DVD_CAPACITY_MB - self.MENU_OVERHEAD_MB
        
        # Account for audio bitrate
        audio_bitrate_kbps = int(self.audio_settings.bitrate.replace('k', ''))
        
        # Calculate available space for video
        audio_size_mb = (audio_bitrate_kbps * total_duration_minutes * 60) / 8 / 1024
        video_space_mb = available_space_mb - audio_size_mb
        
        # Calculate video bitrate
        if total_duration_minutes <= 0:
            return 6000000  # Default 6 Mbps
        
        video_bitrate_bps = int((video_space_mb * 8 * 1024 * 1024) / (total_duration_minutes * 60))
        
        # Clamp to DVD-compliant range (1-9.8 Mbps for video)
        video_bitrate_bps = max(1000000, min(9800000, video_bitrate_bps))
        
        logger.info(
            f"Calculated optimal bitrate: {video_bitrate_bps / 1_000_000:.2f} Mbps "
            f"for {total_duration_minutes:.0f} minutes"
        )
        
        return video_bitrate_bps
    
    def plan_disc_spanning(
        self,
        jobs: list[TranscodeJob],
        target_bitrate: Optional[int] = None
    ) -> list[DiscPlan]:
        """
        Plan how to split episodes across multiple discs if needed.
        
        Args:
            jobs: List of transcode jobs with duration info
            target_bitrate: Target video bitrate (calculated if not provided)
            
        Returns:
            List of DiscPlan objects, one per disc needed
        """
        if not jobs:
            return []
        
        # Calculate total duration
        total_minutes = sum(job.duration_seconds / 60 for job in jobs)
        
        # Calculate bitrate if not provided
        if target_bitrate is None:
            target_bitrate = self.calculate_optimal_bitrate(total_minutes)
        
        # Estimate total size
        audio_bitrate = int(self.audio_settings.bitrate.replace('k', '')) * 1000
        total_bitrate = target_bitrate + audio_bitrate
        total_size_mb = (total_bitrate * total_minutes * 60) / 8 / 1024 / 1024
        
        # Check if spanning is needed
        usable_capacity = self.DVD_CAPACITY_MB - self.MENU_OVERHEAD_MB
        
        if total_size_mb <= usable_capacity:
            # Everything fits on one disc
            return [DiscPlan(
                disc_number=1,
                episodes=jobs,
                total_minutes=total_minutes,
                estimated_size_mb=total_size_mb
            )]
        
        # Need to span multiple discs
        discs = []
        current_episodes = []
        current_minutes = 0.0
        disc_number = 1
        
        for job in jobs:
            episode_minutes = job.duration_seconds / 60
            episode_size_mb = (total_bitrate * episode_minutes * 60) / 8 / 1024 / 1024
            
            # Check if adding this episode would exceed disc capacity
            current_size_mb = (total_bitrate * current_minutes * 60) / 8 / 1024 / 1024
            
            if current_size_mb + episode_size_mb > usable_capacity and current_episodes:
                # Start a new disc
                discs.append(DiscPlan(
                    disc_number=disc_number,
                    episodes=current_episodes.copy(),
                    total_minutes=current_minutes,
                    estimated_size_mb=current_size_mb
                ))
                disc_number += 1
                current_episodes = []
                current_minutes = 0.0
            
            current_episodes.append(job)
            current_minutes += episode_minutes
        
        # Add remaining episodes to last disc
        if current_episodes:
            current_size_mb = (total_bitrate * current_minutes * 60) / 8 / 1024 / 1024
            discs.append(DiscPlan(
                disc_number=disc_number,
                episodes=current_episodes,
                total_minutes=current_minutes,
                estimated_size_mb=current_size_mb
            ))
        
        logger.info(f"Content requires {len(discs)} disc(s)")
        return discs
    
    def extract_subtitles(self, input_path: str, output_path: Path) -> Optional[Path]:
        """
        Extract SRT subtitles from a media file.
        
        Args:
            input_path: Path to input media file
            output_path: Path where to save the SRT file
            
        Returns:
            Path to extracted subtitles, or None if no subtitles found
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # First, probe for subtitle streams
            result = subprocess.run(
                [
                    self._ffprobe_path,
                    "-v", "error",
                    "-select_streams", "s",
                    "-show_entries", "stream=index,codec_name",
                    "-of", "csv=p=0",
                    input_path
                ],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if not result.stdout.strip():
                logger.info(f"No subtitles found in {input_path}")
                return None
            
            # Extract first subtitle stream to SRT
            extract_result = subprocess.run(
                [
                    self._ffmpeg_path,
                    "-y",
                    "-i", input_path,
                    "-map", "0:s:0",
                    "-c:s", "srt",
                    str(output_path)
                ],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if extract_result.returncode == 0 and output_path.exists():
                logger.info(f"Extracted subtitles to {output_path}")
                return output_path
            else:
                logger.warning(f"Failed to extract subtitles: {extract_result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            logger.warning("Subtitle extraction timed out")
            return None
    
    def transcode(
        self,
        input_path: str,
        output_path: Path,
        video_bitrate: Optional[int] = None,
        progress_callback: Optional[Callable[[float], None]] = None,
        extract_subs: bool = True
    ) -> Path:
        """
        Transcode a media file to DVD-compliant MPEG-2.
        
        Args:
            input_path: Path or URL to input media
            output_path: Path for output MPEG file
            video_bitrate: Video bitrate in bps (auto-calculated if not provided)
            progress_callback: Optional callback(progress: 0.0-1.0)
            extract_subs: Whether to extract subtitles
            
        Returns:
            Path to transcoded file
            
        Raises:
            TranscodeFailedError: If transcoding fails
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Get input duration for progress tracking
        duration = self.get_media_duration(input_path)
        
        # Calculate bitrate if not provided
        if video_bitrate is None:
            video_bitrate = self.calculate_optimal_bitrate(duration / 60 if duration else 30)
        
        width, height = self.video_settings.resolution
        
        # Build FFmpeg command
        cmd = [
            self._ffmpeg_path,
            "-y",  # Overwrite output
            "-i", input_path,
            
            # Video settings
            "-c:v", "mpeg2video",
            "-b:v", str(video_bitrate),
            "-maxrate", str(int(video_bitrate * 1.1)),
            "-bufsize", str(int(video_bitrate * 2)),
            "-g", "15",  # GOP size
            "-bf", "2",  # B-frames
            "-s", f"{width}x{height}",
            "-aspect", self.video_settings.aspect_ratio,
            "-r", self.video_settings.framerate,
            "-pix_fmt", "yuv420p",
            
            # Audio settings
            "-c:a", self.audio_settings.codec,
            "-b:a", self.audio_settings.bitrate,
            "-ar", str(self.audio_settings.sample_rate),
            "-ac", str(self.audio_settings.channels),
            
            # Output format
            "-f", "vob",
            "-target", f"{self.video_settings.standard.value}-dvd",
            
            # Progress output
            "-progress", "pipe:1",
            "-nostats",
            
            str(output_path)
        ]
        
        logger.info(f"Transcoding: {input_path} -> {output_path}")
        logger.debug(f"Command: {' '.join(cmd)}")
        
        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Parse progress output
            while True:
                line = process.stdout.readline()
                if not line and process.poll() is not None:
                    break
                
                if line.startswith("out_time_us="):
                    try:
                        time_us = int(line.split("=")[1].strip())
                        time_seconds = time_us / 1_000_000
                        
                        if duration > 0 and progress_callback:
                            progress = min(1.0, time_seconds / duration)
                            progress_callback(progress)
                    except ValueError:
                        pass
            
            # Get return code
            return_code = process.wait()
            
            if return_code != 0:
                stderr = process.stderr.read()
                raise TranscodeFailedError(f"FFmpeg failed with code {return_code}: {stderr}")
            
            if not output_path.exists():
                raise TranscodeFailedError(f"Output file was not created: {output_path}")
            
            logger.info(f"Transcoding complete: {output_path}")
            
            # Extract subtitles if requested
            if extract_subs:
                srt_path = output_path.with_suffix('.srt')
                self.extract_subtitles(input_path, srt_path)
            
            if progress_callback:
                progress_callback(1.0)
            
            return output_path
            
        except subprocess.SubprocessError as e:
            raise TranscodeFailedError(f"Transcode failed: {e}")
    
    def transcode_batch(
        self,
        jobs: list[TranscodeJob],
        progress_callback: Optional[Callable[[int, int, float], None]] = None
    ) -> list[TranscodeJob]:
        """
        Transcode multiple files with optimized bitrate.
        
        Args:
            jobs: List of TranscodeJob objects
            progress_callback: Optional callback(job_index, total_jobs, job_progress)
            
        Returns:
            List of completed TranscodeJob objects with status updated
        """
        if not jobs:
            return jobs
        
        # Get durations for all jobs
        for job in jobs:
            if job.duration_seconds <= 0:
                job.duration_seconds = self.get_media_duration(job.input_path)
        
        # Calculate optimal bitrate for all content
        total_minutes = sum(job.duration_seconds / 60 for job in jobs)
        optimal_bitrate = self.calculate_optimal_bitrate(total_minutes)
        
        total_jobs = len(jobs)
        
        for i, job in enumerate(jobs):
            job.status = "transcoding"
            
            def job_progress(progress: float):
                job.progress = progress
                if progress_callback:
                    progress_callback(i, total_jobs, progress)
            
            try:
                self.transcode(
                    job.input_path,
                    job.output_path,
                    video_bitrate=optimal_bitrate,
                    progress_callback=job_progress
                )
                job.status = "complete"
                job.progress = 1.0
                
            except TranscodeFailedError as e:
                job.status = "failed"
                job.error_message = str(e)
                logger.error(f"Failed to transcode {job.episode_name}: {e}")
        
        return jobs
    
    def create_chapter_file(
        self,
        jobs: list[TranscodeJob],
        output_path: Path
    ) -> Path:
        """
        Create a chapter file for DVD authoring.
        
        Args:
            jobs: List of transcoded episodes
            output_path: Path for the chapter file
            
        Returns:
            Path to the chapter file
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        chapters = []
        current_time = 0.0
        chapter_num = 1
        
        for job in jobs:
            # Format time as HH:MM:SS.mmm
            hours = int(current_time // 3600)
            minutes = int((current_time % 3600) // 60)
            seconds = current_time % 60
            
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:06.3f}"
            chapters.append(f"CHAPTER{chapter_num:02d}={time_str}")
            chapters.append(f"CHAPTER{chapter_num:02d}NAME={job.episode_name}")
            chapter_num += 1
            
            current_time += job.duration_seconds
        
        with open(output_path, 'w') as f:
            f.write('\n'.join(chapters))
        
        logger.info(f"Created chapter file: {output_path}")
        return output_path


def check_dependencies() -> dict[str, bool]:
    """
    Check for required system dependencies.
    
    Returns:
        Dictionary of dependency names and their availability
    """
    deps = {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "dvdauthor": shutil.which("dvdauthor") is not None,
        "spumux": shutil.which("spumux") is not None,
    }
    
    return deps


def get_dependency_instructions() -> str:
    """Get installation instructions for missing dependencies."""
    import platform
    
    system = platform.system().lower()
    
    if system == "linux":
        return """
Install dependencies on Ubuntu/Debian:
    sudo apt update
    sudo apt install ffmpeg dvdauthor

Install dependencies on Fedora:
    sudo dnf install ffmpeg dvdauthor
"""
    elif system == "darwin":
        return """
Install dependencies on macOS using Homebrew:
    brew install ffmpeg dvdauthor
"""
    elif system == "windows":
        return """
Install dependencies on Windows:
    1. FFmpeg: Download from https://ffmpeg.org/download.html
       Extract and add bin folder to PATH
    
    2. dvdauthor: Download from available Windows ports or use WSL
"""
    else:
        return "Please install ffmpeg and dvdauthor for your system."


def main():
    """Test the transcoder module."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("Checking dependencies...")
    deps = check_dependencies()
    
    all_present = True
    for dep, available in deps.items():
        status = "✓" if available else "✗"
        print(f"  {status} {dep}")
        if not available and dep in ("ffmpeg", "ffprobe"):
            all_present = False
    
    if not all_present:
        print(get_dependency_instructions())
        sys.exit(1)
    
    print("\nAll required dependencies are available!")
    
    # Create transcoder instance
    try:
        transcoder = Transcoder(Path("staging"))
        print(f"\nTranscoder initialized:")
        print(f"  Video: {transcoder.video_settings.standard.value.upper()}")
        print(f"  Resolution: {transcoder.video_settings.resolution}")
        print(f"  Audio: {transcoder.audio_settings.codec.upper()} "
              f"{transcoder.audio_settings.channels}ch @ {transcoder.audio_settings.bitrate}")
        
        # Test bitrate calculation
        print("\nBitrate calculations:")
        for minutes in [60, 90, 120, 180, 240]:
            bitrate = transcoder.calculate_optimal_bitrate(minutes)
            print(f"  {minutes} min: {bitrate / 1_000_000:.2f} Mbps")
        
    except FFmpegNotFoundError as e:
        print(f"\nError: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
