"""
Burner Module

This module provides cross-platform disc burning and ISO creation functionality.
Supports Windows (ImgBurn), Linux (growisofs), and macOS (hdiutil).
"""

import logging
import os
import platform
import shutil
import subprocess
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class BurnerPlatform(Enum):
    """Supported burning platforms."""
    WINDOWS = "windows"
    LINUX = "linux"
    MACOS = "macos"
    UNKNOWN = "unknown"


@dataclass
class DiscInfo:
    """Information about a disc/drive."""
    device_path: str
    device_name: str
    is_blank: bool = False
    is_ready: bool = False
    media_type: str = "unknown"
    capacity_mb: int = 0


class BurnerError(Exception):
    """Base exception for burner errors."""
    pass


class NoBurnerFoundError(BurnerError):
    """Raised when no disc burner is found."""
    pass


class BurnFailedError(BurnerError):
    """Raised when burning fails."""
    pass


class ISOCreationError(BurnerError):
    """Raised when ISO creation fails."""
    pass


class Burner:
    """
    Cross-platform disc burner with ISO creation support.
    
    Automatically detects the operating system and uses the appropriate
    burning tool:
    - Windows: ImgBurn (CLI mode)
    - Linux: growisofs / wodim
    - macOS: hdiutil
    
    Also supports creating ISO images for testing without physical media.
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        Initialize the burner.
        
        Args:
            output_dir: Directory for ISO output (defaults to current directory)
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.platform = self._detect_platform()
        self._burner_path = self._find_burner()
    
    def _detect_platform(self) -> BurnerPlatform:
        """Detect the current operating system."""
        system = platform.system().lower()
        
        if system == "windows":
            return BurnerPlatform.WINDOWS
        elif system == "linux":
            return BurnerPlatform.LINUX
        elif system == "darwin":
            return BurnerPlatform.MACOS
        else:
            return BurnerPlatform.UNKNOWN
    
    def _find_burner(self) -> Optional[str]:
        """Find the appropriate burning tool for this platform."""
        if self.platform == BurnerPlatform.WINDOWS:
            # Look for ImgBurn
            imgburn_paths = [
                r"C:\Program Files\ImgBurn\ImgBurn.exe",
                r"C:\Program Files (x86)\ImgBurn\ImgBurn.exe",
                shutil.which("ImgBurn"),
            ]
            for path in imgburn_paths:
                if path and Path(path).exists():
                    return path
            
        elif self.platform == BurnerPlatform.LINUX:
            # Look for growisofs or wodim
            for tool in ["growisofs", "wodim", "cdrecord"]:
                path = shutil.which(tool)
                if path:
                    return path
                    
        elif self.platform == BurnerPlatform.MACOS:
            # hdiutil is built-in
            return shutil.which("hdiutil")
        
        return None
    
    def is_burner_available(self) -> bool:
        """Check if a disc burning tool is available."""
        return self._burner_path is not None
    
    def get_burner_info(self) -> dict:
        """Get information about the available burning tool."""
        if not self._burner_path:
            return {
                "available": False,
                "platform": self.platform.value,
                "tool": None,
                "instructions": self._get_install_instructions()
            }
        
        return {
            "available": True,
            "platform": self.platform.value,
            "tool": Path(self._burner_path).name,
            "path": self._burner_path
        }
    
    def _get_install_instructions(self) -> str:
        """Get installation instructions for the burning tool."""
        if self.platform == BurnerPlatform.WINDOWS:
            return (
                "ImgBurn is required for disc burning on Windows.\n"
                "Download from: https://www.imgburn.com/\n"
                "Install and ensure it's in your PATH or Program Files."
            )
        elif self.platform == BurnerPlatform.LINUX:
            return (
                "growisofs is required for disc burning on Linux.\n"
                "Install with:\n"
                "  Ubuntu/Debian: sudo apt install growisofs\n"
                "  Fedora: sudo dnf install dvd+rw-tools\n"
                "  Arch: sudo pacman -S dvd+rw-tools"
            )
        elif self.platform == BurnerPlatform.MACOS:
            return (
                "hdiutil should be available by default on macOS.\n"
                "If missing, try reinstalling Command Line Tools:\n"
                "  xcode-select --install"
            )
        else:
            return "Unknown platform. Please install appropriate burning software."
    
    def detect_drives(self) -> list[DiscInfo]:
        """
        Detect available optical drives.
        
        Returns:
            List of DiscInfo objects for each detected drive
        """
        drives = []
        
        if self.platform == BurnerPlatform.LINUX:
            # Check /dev/sr* and /dev/dvd*
            for pattern in ["/dev/sr*", "/dev/dvd*"]:
                import glob
                for device in glob.glob(pattern):
                    if os.path.exists(device):
                        drives.append(DiscInfo(
                            device_path=device,
                            device_name=Path(device).name,
                            is_ready=True
                        ))
        
        elif self.platform == BurnerPlatform.MACOS:
            # Use diskutil to find optical drives
            try:
                result = subprocess.run(
                    ["diskutil", "list"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                # Parse output for optical drives
                # This is a simplified detection
                for line in result.stdout.split('\n'):
                    if 'DVD' in line or 'CD' in line:
                        parts = line.split()
                        if parts:
                            drives.append(DiscInfo(
                                device_path=f"/dev/{parts[-1]}",
                                device_name=parts[-1],
                                is_ready=True
                            ))
            except subprocess.SubprocessError:
                pass
        
        elif self.platform == BurnerPlatform.WINDOWS:
            # Use WMI or check drive letters
            try:
                import ctypes
                drives_bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                for letter in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ':
                    if drives_bitmask & 1:
                        drive_path = f"{letter}:\\"
                        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                        if drive_type == 5:  # DRIVE_CDROM
                            drives.append(DiscInfo(
                                device_path=drive_path,
                                device_name=f"{letter}:",
                                is_ready=True
                            ))
                    drives_bitmask >>= 1
            except Exception:
                pass
        
        return drives
    
    def eject_tray(self, device: Optional[str] = None) -> bool:
        """
        Eject the disc tray.
        
        Args:
            device: Device path (auto-detected if not provided)
            
        Returns:
            True if successful
        """
        try:
            if self.platform == BurnerPlatform.LINUX:
                device = device or "/dev/sr0"
                subprocess.run(["eject", device], check=True, timeout=30)
                return True
                
            elif self.platform == BurnerPlatform.MACOS:
                device = device or "/dev/disk1"
                subprocess.run(["drutil", "eject"], check=True, timeout=30)
                return True
                
            elif self.platform == BurnerPlatform.WINDOWS:
                # Use PowerShell to eject
                device = device or "D:"
                ps_cmd = f'(New-Object -ComObject Shell.Application).Namespace(17).ParseName("{device}").InvokeVerb("Eject")'
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    check=True,
                    timeout=30
                )
                return True
                
        except subprocess.SubprocessError as e:
            logger.warning(f"Failed to eject tray: {e}")
        
        return False
    
    def close_tray(self, device: Optional[str] = None) -> bool:
        """
        Close the disc tray.
        
        Args:
            device: Device path (auto-detected if not provided)
            
        Returns:
            True if successful
        """
        try:
            if self.platform == BurnerPlatform.LINUX:
                device = device or "/dev/sr0"
                subprocess.run(["eject", "-t", device], check=True, timeout=30)
                return True
                
            elif self.platform == BurnerPlatform.MACOS:
                # macOS slot-loading drives don't have tray close
                logger.info("Tray close not supported on most Mac drives")
                return False
                
            elif self.platform == BurnerPlatform.WINDOWS:
                # This is more complex on Windows
                logger.info("Tray close requires manual insertion on Windows")
                return False
                
        except subprocess.SubprocessError as e:
            logger.warning(f"Failed to close tray: {e}")
        
        return False
    
    def prompt_for_next_disc(
        self,
        disc_number: int,
        total_discs: int,
        callback: Optional[Callable[[str], None]] = None
    ) -> bool:
        """
        Prompt user to insert the next disc for multi-disc projects.
        
        Ejects the tray and waits for user to insert a new blank disc.
        
        Args:
            disc_number: Current disc number (1-indexed)
            total_discs: Total number of discs required
            callback: Optional callback for status messages
            
        Returns:
            True if user inserted a disc, False if cancelled
        """
        message = f"\n{'='*50}\n"
        message += f"  Please insert DISC {disc_number} of {total_discs}\n"
        message += f"{'='*50}\n"
        
        if callback:
            callback(message)
        else:
            print(message)
        
        # Eject tray
        self.eject_tray()
        
        if callback:
            callback("Tray ejected. Insert a blank DVD and press Enter...")
        else:
            print("Tray ejected. Insert a blank DVD and press Enter...")
        
        try:
            input()  # Wait for user
            
            # Give drive time to recognize disc
            time.sleep(3)
            
            if callback:
                callback(f"Disc {disc_number} loaded. Continuing...")
            else:
                print(f"Disc {disc_number} loaded. Continuing...")
            
            return True
            
        except (KeyboardInterrupt, EOFError):
            if callback:
                callback("Cancelled by user")
            else:
                print("\nCancelled by user")
            return False
    
    def create_iso(
        self,
        dvd_structure_dir: Path,
        output_path: Optional[Path] = None,
        volume_label: str = "DVDVIDEO",
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """
        Create an ISO image from a DVD structure directory.
        
        Args:
            dvd_structure_dir: Path to DVD structure (VIDEO_TS folder)
            output_path: Output ISO path (auto-generated if not provided)
            volume_label: Volume label for the ISO
            progress_callback: Optional callback(progress: 0-1, status: str)
            
        Returns:
            Path to created ISO file
        """
        if output_path is None:
            output_path = self.output_dir / f"{volume_label}.iso"
        
        output_path = Path(output_path)
        
        if progress_callback:
            progress_callback(0.0, "Starting ISO creation...")
        
        # Find mkisofs or genisoimage
        mkisofs = shutil.which("mkisofs") or shutil.which("genisoimage")
        
        if mkisofs:
            return self._create_iso_mkisofs(
                dvd_structure_dir, output_path, volume_label, mkisofs, progress_callback
            )
        
        # Fallback to platform-specific tools
        if self.platform == BurnerPlatform.MACOS:
            return self._create_iso_hdiutil(
                dvd_structure_dir, output_path, volume_label, progress_callback
            )
        
        # Use Python pycdlib as last resort
        return self._create_iso_pycdlib(
            dvd_structure_dir, output_path, volume_label, progress_callback
        )
    
    def _create_iso_mkisofs(
        self,
        source_dir: Path,
        output_path: Path,
        volume_label: str,
        mkisofs_path: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """Create ISO using mkisofs/genisoimage."""
        cmd = [
            mkisofs_path,
            "-dvd-video",
            "-V", volume_label[:32],  # Volume label max 32 chars
            "-o", str(output_path),
            str(source_dir)
        ]
        
        if progress_callback:
            progress_callback(0.1, "Running mkisofs...")
        
        logger.debug(f"Running: {' '.join(cmd)}")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3600  # 1 hour timeout
        )
        
        if result.returncode != 0:
            raise ISOCreationError(f"mkisofs failed: {result.stderr}")
        
        if progress_callback:
            progress_callback(1.0, "ISO created successfully")
        
        logger.info(f"Created ISO: {output_path}")
        return output_path
    
    def _create_iso_hdiutil(
        self,
        source_dir: Path,
        output_path: Path,
        volume_label: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """Create ISO using macOS hdiutil."""
        # First create a temporary DMG
        temp_dmg = output_path.with_suffix('.dmg')
        
        cmd = [
            "hdiutil", "create",
            "-volname", volume_label,
            "-srcfolder", str(source_dir),
            "-ov",
            "-format", "UDTO",  # DVD/CD master
            str(temp_dmg)
        ]
        
        if progress_callback:
            progress_callback(0.1, "Creating disc image...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        
        if result.returncode != 0:
            raise ISOCreationError(f"hdiutil failed: {result.stderr}")
        
        # hdiutil creates .cdr file, rename to .iso
        cdr_path = temp_dmg.with_suffix('.dmg.cdr')
        if cdr_path.exists():
            cdr_path.rename(output_path)
        elif temp_dmg.exists():
            temp_dmg.rename(output_path)
        
        if progress_callback:
            progress_callback(1.0, "ISO created successfully")
        
        logger.info(f"Created ISO: {output_path}")
        return output_path
    
    def _create_iso_pycdlib(
        self,
        source_dir: Path,
        output_path: Path,
        volume_label: str,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> Path:
        """Create ISO using pycdlib (pure Python fallback)."""
        try:
            import pycdlib
        except ImportError:
            raise ISOCreationError(
                "No ISO creation tool found. Install mkisofs or pycdlib:\n"
                "  pip install pycdlib"
            )
        
        if progress_callback:
            progress_callback(0.1, "Creating ISO with pycdlib...")
        
        iso = pycdlib.PyCdlib()
        iso.new(
            interchange_level=4,
            sys_ident='',
            vol_ident=volume_label[:32],
            vol_set_ident='',
            pub_ident_str='',
            preparer_ident_str='JellyDisc',
            app_ident_str='JellyDisc DVD Authoring',
            udf=True
        )
        
        # Walk source directory and add files
        total_files = sum(1 for _ in source_dir.rglob('*') if _.is_file())
        processed = 0
        
        for file_path in source_dir.rglob('*'):
            if file_path.is_file():
                rel_path = file_path.relative_to(source_dir)
                iso_path = '/' + '/'.join(rel_path.parts).upper()
                
                # Ensure proper ISO 9660 path format
                iso_path = '/' + ';1'.join(iso_path.rsplit('.', 1)) if '.' in rel_path.name else iso_path + ';1'
                
                with open(file_path, 'rb') as f:
                    iso.add_fp(
                        f,
                        len(file_path.read_bytes()),
                        iso_path=iso_path
                    )
                
                processed += 1
                if progress_callback:
                    progress_callback(0.1 + 0.8 * (processed / total_files), f"Adding: {rel_path.name}")
        
        iso.write(str(output_path))
        iso.close()
        
        if progress_callback:
            progress_callback(1.0, "ISO created successfully")
        
        logger.info(f"Created ISO: {output_path}")
        return output_path
    
    def burn_iso(
        self,
        iso_path: Path,
        device: Optional[str] = None,
        speed: int = 4,
        progress_callback: Optional[Callable[[float, str], None]] = None
    ) -> bool:
        """
        Burn an ISO image to a physical disc.
        
        Args:
            iso_path: Path to ISO file
            device: Device path (auto-detected if not provided)
            speed: Burn speed (e.g., 4 for 4x)
            progress_callback: Optional callback(progress: 0-1, status: str)
            
        Returns:
            True if burning was successful
        """
        if not self._burner_path:
            raise NoBurnerFoundError(self._get_install_instructions())
        
        if not iso_path.exists():
            raise BurnFailedError(f"ISO file not found: {iso_path}")
        
        if progress_callback:
            progress_callback(0.0, "Starting burn...")
        
        try:
            if self.platform == BurnerPlatform.LINUX:
                return self._burn_linux(iso_path, device, speed, progress_callback)
            elif self.platform == BurnerPlatform.MACOS:
                return self._burn_macos(iso_path, device, progress_callback)
            elif self.platform == BurnerPlatform.WINDOWS:
                return self._burn_windows(iso_path, device, speed, progress_callback)
            else:
                raise BurnFailedError("Unsupported platform for burning")
                
        except subprocess.SubprocessError as e:
            raise BurnFailedError(f"Burn failed: {e}")
    
    def _burn_linux(
        self,
        iso_path: Path,
        device: Optional[str],
        speed: int,
        progress_callback: Optional[Callable[[float, str], None]]
    ) -> bool:
        """Burn ISO using growisofs on Linux."""
        device = device or "/dev/sr0"
        
        cmd = [
            self._burner_path,
            "-dvd-compat",
            f"-speed={speed}",
            "-Z", f"{device}={iso_path}"
        ]
        
        if progress_callback:
            progress_callback(0.1, f"Burning to {device}...")
        
        logger.info(f"Running: {' '.join(cmd)}")
        
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Parse progress from growisofs output
        for line in process.stdout:
            if '%' in line:
                try:
                    # Extract percentage from output like "12.3% done"
                    pct_str = line.split('%')[0].split()[-1]
                    pct = float(pct_str) / 100
                    if progress_callback:
                        progress_callback(pct, f"Burning: {pct*100:.1f}%")
                except (ValueError, IndexError):
                    pass
        
        process.wait()
        
        if process.returncode != 0:
            raise BurnFailedError("growisofs failed")
        
        if progress_callback:
            progress_callback(1.0, "Burn complete!")
        
        return True
    
    def _burn_macos(
        self,
        iso_path: Path,
        device: Optional[str],
        progress_callback: Optional[Callable[[float, str], None]]
    ) -> bool:
        """Burn ISO using hdiutil on macOS."""
        cmd = ["hdiutil", "burn", str(iso_path)]
        
        if device:
            cmd.extend(["-device", device])
        
        if progress_callback:
            progress_callback(0.1, "Burning disc...")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=7200)
        
        if result.returncode != 0:
            raise BurnFailedError(f"hdiutil burn failed: {result.stderr}")
        
        if progress_callback:
            progress_callback(1.0, "Burn complete!")
        
        return True
    
    def _burn_windows(
        self,
        iso_path: Path,
        device: Optional[str],
        speed: int,
        progress_callback: Optional[Callable[[float, str], None]]
    ) -> bool:
        """Burn ISO using ImgBurn on Windows."""
        device = device or "D:"
        
        cmd = [
            self._burner_path,
            "/MODE", "WRITE",
            "/SRC", str(iso_path),
            "/DEST", device,
            "/SPEED", str(speed),
            "/START",
            "/CLOSE",
            "/NOIMAGEDETAILS"
        ]
        
        if progress_callback:
            progress_callback(0.1, f"Burning to {device}...")
        
        # ImgBurn runs asynchronously, so we monitor the process
        process = subprocess.Popen(cmd)
        
        # Simple progress simulation for ImgBurn
        # (Real progress would require parsing ImgBurn log file)
        while process.poll() is None:
            time.sleep(5)
        
        if process.returncode != 0:
            raise BurnFailedError("ImgBurn failed")
        
        if progress_callback:
            progress_callback(1.0, "Burn complete!")
        
        return True
    
    def burn_multi_disc(
        self,
        iso_paths: list[Path],
        device: Optional[str] = None,
        speed: int = 4,
        progress_callback: Optional[Callable[[int, int, float, str], None]] = None
    ) -> bool:
        """
        Burn multiple ISOs to multiple discs with prompts between each.
        
        Args:
            iso_paths: List of ISO files to burn
            device: Device path
            speed: Burn speed
            progress_callback: Optional callback(disc_num, total_discs, progress, status)
            
        Returns:
            True if all discs were burned successfully
        """
        total_discs = len(iso_paths)
        
        for i, iso_path in enumerate(iso_paths):
            disc_num = i + 1
            
            if i > 0:
                # Prompt for next disc
                if not self.prompt_for_next_disc(disc_num, total_discs):
                    return False
            
            def disc_progress(progress: float, status: str):
                if progress_callback:
                    progress_callback(disc_num, total_discs, progress, status)
            
            try:
                self.burn_iso(iso_path, device, speed, disc_progress)
            except BurnFailedError as e:
                logger.error(f"Failed to burn disc {disc_num}: {e}")
                return False
        
        return True


def check_burner_dependencies() -> dict[str, bool]:
    """Check for available burning tools."""
    return {
        "mkisofs": shutil.which("mkisofs") is not None,
        "genisoimage": shutil.which("genisoimage") is not None,
        "growisofs": shutil.which("growisofs") is not None,
        "hdiutil": shutil.which("hdiutil") is not None,
        "pycdlib": _check_pycdlib(),
    }


def _check_pycdlib() -> bool:
    """Check if pycdlib is available."""
    try:
        import pycdlib
        return True
    except ImportError:
        return False


def main():
    """Test burner module."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    print("Burner Module Test")
    print("=" * 50)
    
    burner = Burner()
    
    print(f"\nPlatform: {burner.platform.value}")
    
    info = burner.get_burner_info()
    print(f"Burner available: {info['available']}")
    
    if info['available']:
        print(f"Tool: {info['tool']}")
        print(f"Path: {info['path']}")
    else:
        print(f"\n{info['instructions']}")
    
    print("\nChecking dependencies...")
    deps = check_burner_dependencies()
    for dep, available in deps.items():
        status = "✓" if available else "✗"
        print(f"  {status} {dep}")
    
    print("\nDetecting optical drives...")
    drives = burner.detect_drives()
    if drives:
        for drive in drives:
            print(f"  Found: {drive.device_name} ({drive.device_path})")
    else:
        print("  No optical drives detected")
    
    # Test ISO creation capability
    print("\nISO Creation: ", end="")
    if shutil.which("mkisofs") or shutil.which("genisoimage"):
        print("mkisofs/genisoimage available")
    elif shutil.which("hdiutil"):
        print("hdiutil available (macOS)")
    elif _check_pycdlib():
        print("pycdlib available (Python fallback)")
    else:
        print("No ISO creation tool found")


if __name__ == "__main__":
    main()
