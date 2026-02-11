"""
Jellyfin Client Module

This module provides connectivity to a Jellyfin media server for fetching
TV shows, seasons, episodes, and associated media assets.
"""

import os
import logging
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """Represents a TV show episode."""
    id: str
    name: str
    index_number: int
    overview: str = ""
    runtime_ticks: int = 0
    primary_image_url: Optional[str] = None
    media_sources: list = field(default_factory=list)
    
    @property
    def runtime_minutes(self) -> float:
        """Return runtime in minutes."""
        if self.runtime_ticks:
            return self.runtime_ticks / 10_000_000 / 60
        return 0.0


@dataclass
class Season:
    """Represents a TV show season."""
    id: str
    name: str
    index_number: int
    series_id: str
    series_name: str = ""
    overview: str = ""
    primary_image_url: Optional[str] = None
    episodes: list[Episode] = field(default_factory=list)


@dataclass
class Series:
    """Represents a TV show series."""
    id: str
    name: str
    overview: str = ""
    year: Optional[int] = None
    rating: Optional[str] = None
    backdrop_image_url: Optional[str] = None
    logo_image_url: Optional[str] = None
    theme_song_url: Optional[str] = None
    seasons: list[Season] = field(default_factory=list)


class JellyfinClientError(Exception):
    """Base exception for Jellyfin client errors."""
    pass


class AuthenticationError(JellyfinClientError):
    """Raised when authentication fails."""
    pass


class JellyfinConnectionError(JellyfinClientError):
    """Raised when connection to server fails."""
    pass


class JellyfinClient:
    """
    Client for interacting with a Jellyfin media server.
    
    Provides methods to authenticate, browse TV shows, and download
    media assets for DVD authoring.
    """
    
    # Device info for Jellyfin client identification
    DEVICE_NAME = "JellyDisc"
    DEVICE_ID = "jellydisc-dvd-authoring"
    CLIENT_NAME = "JellyDisc"
    CLIENT_VERSION = "0.1.0"
    
    def __init__(self, server_url: str):
        """
        Initialize the Jellyfin client.
        
        Args:
            server_url: Base URL of the Jellyfin server (e.g., "http://localhost:8096")
        """
        # Ensure URL doesn't have trailing slash
        self.server_url = server_url.rstrip('/')
        self.access_token: Optional[str] = None
        self.user_id: Optional[str] = None
        self.session = requests.Session()
        
        # Set default headers
        self._update_auth_header()
    
    def _update_auth_header(self) -> None:
        """Update the authorization header with current credentials."""
        auth_parts = [
            f'MediaBrowser Client="{self.CLIENT_NAME}"',
            f'Device="{self.DEVICE_NAME}"',
            f'DeviceId="{self.DEVICE_ID}"',
            f'Version="{self.CLIENT_VERSION}"'
        ]
        
        if self.access_token:
            auth_parts.append(f'Token="{self.access_token}"')
        
        self.session.headers.update({
            'X-Emby-Authorization': ', '.join(auth_parts),
            'Content-Type': 'application/json'
        })
    
    def _make_request(self, method: str, endpoint: str, **kwargs) -> dict:
        """
        Make an HTTP request to the Jellyfin API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint (e.g., "/Users/AuthenticateByName")
            **kwargs: Additional arguments to pass to requests
            
        Returns:
            JSON response as dictionary
            
        Raises:
            ConnectionError: If unable to connect to server
            JellyfinClientError: If the API returns an error
        """
        url = f"{self.server_url}{endpoint}"
        
        try:
            response = self.session.request(method, url, **kwargs)
            
            if response.status_code == 401:
                raise AuthenticationError("Invalid credentials or session expired")
            
            response.raise_for_status()
            
            if response.content:
                return response.json()
            return {}
            
        except requests.exceptions.SSLError as e:
            raise JellyfinConnectionError(f"SSL error connecting to server: {e}")
        except requests.exceptions.ConnectionError as e:
            raise JellyfinConnectionError(f"Unable to connect to Jellyfin server at {self.server_url}: {e}")
        except requests.exceptions.RequestException as e:
            raise JellyfinClientError(f"Request failed: {e}")
    
    def authenticate(self, username: str, password: str) -> bool:
        """
        Authenticate with the Jellyfin server.
        
        Args:
            username: Jellyfin username
            password: Jellyfin password
            
        Returns:
            True if authentication was successful
            
        Raises:
            AuthenticationError: If credentials are invalid
            ConnectionError: If unable to connect to server
        """
        payload = {
            "Username": username,
            "Pw": password
        }
        
        try:
            result = self._make_request("POST", "/Users/AuthenticateByName", json=payload)
            
            self.access_token = result.get("AccessToken")
            self.user_id = result.get("User", {}).get("Id")
            
            if not self.access_token or not self.user_id:
                raise AuthenticationError("Invalid response from server")
            
            # Update headers with new token
            self._update_auth_header()
            
            logger.info(f"Successfully authenticated as {username}")
            return True
            
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                raise AuthenticationError("Invalid username or password")
            raise JellyfinClientError(f"Authentication failed: {e}")
    
    def is_authenticated(self) -> bool:
        """Check if client is currently authenticated."""
        return self.access_token is not None and self.user_id is not None
    
    def get_server_info(self) -> dict:
        """
        Get server information.
        
        Returns:
            Server info dictionary
        """
        return self._make_request("GET", "/System/Info/Public")
    
    def get_tv_shows(self) -> list[Series]:
        """
        Fetch all TV shows from the library.
        
        Returns:
            List of Series objects
            
        Raises:
            AuthenticationError: If not authenticated
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        params = {
            "IncludeItemTypes": "Series",
            "Recursive": True,
            "Fields": "Overview,ProviderIds,Path",
            "SortBy": "SortName",
            "SortOrder": "Ascending"
        }
        
        result = self._make_request("GET", f"/Users/{self.user_id}/Items", params=params)
        
        shows = []
        for item in result.get("Items", []):
            series = Series(
                id=item["Id"],
                name=item["Name"],
                overview=item.get("Overview", ""),
                year=item.get("ProductionYear"),
                rating=item.get("OfficialRating"),
                backdrop_image_url=self._get_image_url(item["Id"], "Backdrop"),
                logo_image_url=self._get_image_url(item["Id"], "Logo"),
            )
            shows.append(series)
        
        return shows
    
    def get_seasons(self, series_id: str) -> list[Season]:
        """
        Fetch all seasons for a TV show.
        
        Args:
            series_id: ID of the TV series
            
        Returns:
            List of Season objects
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        params = {
            "Fields": "Overview,Path"
        }
        
        result = self._make_request("GET", f"/Shows/{series_id}/Seasons", params=params)
        
        seasons = []
        for item in result.get("Items", []):
            season = Season(
                id=item["Id"],
                name=item["Name"],
                index_number=item.get("IndexNumber", 0),
                series_id=series_id,
                series_name=item.get("SeriesName", ""),
                overview=item.get("Overview", ""),
                primary_image_url=self._get_image_url(item["Id"], "Primary"),
            )
            seasons.append(season)
        
        return seasons
    
    def get_episodes(self, series_id: str, season_id: str) -> list[Episode]:
        """
        Fetch all episodes for a season.
        
        Args:
            series_id: ID of the TV series
            season_id: ID of the season
            
        Returns:
            List of Episode objects
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        params = {
            "SeasonId": season_id,
            "Fields": "Overview,Path,MediaSources"
        }
        
        result = self._make_request("GET", f"/Shows/{series_id}/Episodes", params=params)
        
        episodes = []
        for item in result.get("Items", []):
            episode = Episode(
                id=item["Id"],
                name=item["Name"],
                index_number=item.get("IndexNumber", 0),
                overview=item.get("Overview", ""),
                runtime_ticks=item.get("RunTimeTicks", 0),
                primary_image_url=self._get_image_url(item["Id"], "Primary"),
                media_sources=item.get("MediaSources", [])
            )
            episodes.append(episode)
        
        return episodes
    
    def get_season_details(self, series_id: str, season_id: str) -> Season:
        """
        Get full details for a season including episodes.
        
        Args:
            series_id: ID of the TV series
            season_id: ID of the season
            
        Returns:
            Season object with populated episodes list
        """
        # Get season info
        seasons = self.get_seasons(series_id)
        season = next((s for s in seasons if s.id == season_id), None)
        
        if not season:
            raise JellyfinClientError(f"Season {season_id} not found")
        
        # Get episodes
        season.episodes = self.get_episodes(series_id, season_id)
        
        return season
    
    def _get_image_url(self, item_id: str, image_type: str, max_width: int = 720) -> str:
        """
        Construct URL for an item's image.
        
        Args:
            item_id: ID of the item
            image_type: Type of image (Primary, Backdrop, Logo, etc.)
            max_width: Maximum width for the image
            
        Returns:
            Full URL to the image
        """
        return f"{self.server_url}/Items/{item_id}/Images/{image_type}?maxWidth={max_width}"
    
    def download_image(self, url: str, save_path: Path) -> Path:
        """
        Download an image from the server.
        
        Args:
            url: Full URL to the image
            save_path: Path where to save the image
            
        Returns:
            Path to the saved image
        """
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        logger.info(f"Downloaded image to {save_path}")
        return save_path
    
    def download_media_file(self, item_id: str, save_path: Path, 
                            progress_callback=None) -> Path:
        """
        Download a media file (episode) from the server.
        
        Args:
            item_id: ID of the media item to download
            save_path: Path where to save the file
            progress_callback: Optional callback(bytes_downloaded, total_bytes)
            
        Returns:
            Path to the saved file
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        url = f"{self.server_url}/Items/{item_id}/Download"
        
        response = self.session.get(url, stream=True)
        response.raise_for_status()
        
        total_size = int(response.headers.get('content-length', 0))
        save_path.parent.mkdir(parents=True, exist_ok=True)
        
        downloaded = 0
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size:
                    progress_callback(downloaded, total_size)
        
        logger.info(f"Downloaded media to {save_path}")
        return save_path
    
    def get_stream_url(self, item_id: str) -> str:
        """
        Get the direct streaming URL for a media item.
        
        This can be used to pass to ffmpeg for transcoding without
        downloading the entire file first.
        
        Args:
            item_id: ID of the media item
            
        Returns:
            Direct stream URL
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        return f"{self.server_url}/Items/{item_id}/Download?api_key={self.access_token}"
    
    def get_theme_song_url(self, series_id: str) -> Optional[str]:
        """
        Get the theme song URL for a series if available.
        
        Args:
            series_id: ID of the TV series
            
        Returns:
            URL to theme song or None if not available
        """
        if not self.is_authenticated():
            raise AuthenticationError("Not authenticated. Call authenticate() first.")
        
        result = self._make_request("GET", f"/Items/{series_id}/ThemeSongs")
        
        items = result.get("Items", [])
        if items:
            return f"{self.server_url}/Items/{items[0]['Id']}/Download?api_key={self.access_token}"
        
        return None
    
    def logout(self) -> None:
        """Log out and clear session."""
        if self.access_token:
            try:
                self._make_request("POST", "/Sessions/Logout")
            except JellyfinClientError:
                pass  # Ignore logout errors
        
        self.access_token = None
        self.user_id = None
        self._update_auth_header()
        logger.info("Logged out from Jellyfin server")


def main():
    """Example usage of the Jellyfin client."""
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # Example: Connect to a local Jellyfin server
    server_url = os.environ.get("JELLYFIN_URL", "http://localhost:8096")
    username = os.environ.get("JELLYFIN_USER", "")
    password = os.environ.get("JELLYFIN_PASS", "")
    
    if not username or not password:
        print("Please set JELLYFIN_URL, JELLYFIN_USER, and JELLYFIN_PASS environment variables")
        print("Example:")
        print("  export JELLYFIN_URL='http://localhost:8096'")
        print("  export JELLYFIN_USER='admin'")
        print("  export JELLYFIN_PASS='password'")
        sys.exit(1)
    
    client = JellyfinClient(server_url)
    
    try:
        # Get server info (no auth required)
        print(f"Connecting to: {server_url}")
        info = client.get_server_info()
        print(f"Server: {info.get('ServerName')} (v{info.get('Version')})")
        
        # Authenticate
        print(f"\nAuthenticating as {username}...")
        client.authenticate(username, password)
        print("Authentication successful!")
        
        # Get TV shows
        print("\nFetching TV shows...")
        shows = client.get_tv_shows()
        print(f"Found {len(shows)} TV shows:\n")
        
        for show in shows[:5]:  # Show first 5
            print(f"  - {show.name} ({show.year or 'N/A'})")
            
            # Get seasons for first show
            if shows.index(show) == 0:
                seasons = client.get_seasons(show.id)
                print(f"    Seasons: {len(seasons)}")
                
                if seasons:
                    episodes = client.get_episodes(show.id, seasons[0].id)
                    print(f"    Episodes in {seasons[0].name}: {len(episodes)}")
                    
                    for ep in episodes[:3]:
                        print(f"      - E{ep.index_number}: {ep.name} ({ep.runtime_minutes:.0f} min)")
        
        # Logout
        client.logout()
        print("\nLogged out successfully!")
        
    except AuthenticationError as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)
    except JellyfinConnectionError as e:
        print(f"Connection error: {e}")
        sys.exit(1)
    except JellyfinClientError as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
