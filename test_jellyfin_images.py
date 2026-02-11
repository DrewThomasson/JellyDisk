#!/usr/bin/env python3
"""
Test script to verify Jellyfin image availability.

Usage:
    export JELLYFIN_URL='http://your-server:8096'
    export JELLYFIN_USER='your-username'
    export JELLYFIN_PASS='your-password'
    python test_jellyfin_images.py
"""

import os
import sys
import requests
from pathlib import Path

# Add the jellydisc module to path
sys.path.insert(0, str(Path(__file__).parent))

from jellydisc.jellyfin_client import JellyfinClient, AuthenticationError, JellyfinConnectionError


def test_image_url(session, url, description):
    """Test if an image URL is accessible."""
    try:
        response = session.head(url, timeout=10)
        if response.status_code == 200:
            print(f"  ✓ {description}: Available")
            return True
        else:
            print(f"  ✗ {description}: HTTP {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ {description}: Error - {e}")
        return False


def main():
    # Get credentials from environment
    server_url = os.environ.get("JELLYFIN_URL", "")
    username = os.environ.get("JELLYFIN_USER", "")
    password = os.environ.get("JELLYFIN_PASS", "")
    
    if not server_url or not username or not password:
        print("Please set environment variables:")
        print("  export JELLYFIN_URL='http://your-server:8096'")
        print("  export JELLYFIN_USER='your-username'")
        print("  export JELLYFIN_PASS='your-password'")
        sys.exit(1)
    
    print(f"Testing Jellyfin server: {server_url}")
    print(f"Username: {username}")
    print()
    
    try:
        # Connect and authenticate
        client = JellyfinClient(server_url)
        
        print("Getting server info...")
        info = client.get_server_info()
        print(f"  Server: {info.get('ServerName')} (v{info.get('Version')})")
        
        print("\nAuthenticating...")
        client.authenticate(username, password)
        print("  ✓ Authenticated successfully")
        
        # Get TV shows
        print("\nFetching TV shows...")
        shows = client.get_tv_shows()
        print(f"  Found {len(shows)} TV shows")
        
        if not shows:
            print("  No TV shows found in library.")
            return
        
        # Test first show's images
        show = shows[0]
        print(f"\n=== Testing images for: {show.name} ===")
        
        # Test show backdrop
        backdrop_url = client._get_image_url(show.id, "Backdrop", 1280)
        print(f"\nBackdrop URL: {backdrop_url}")
        test_image_url(client.session, backdrop_url, "Series Backdrop")
        
        # Test show logo
        logo_url = client._get_image_url(show.id, "Logo", 500)
        print(f"\nLogo URL: {logo_url}")
        test_image_url(client.session, logo_url, "Series Logo")
        
        # Test show primary
        primary_url = client._get_image_url(show.id, "Primary", 720)
        print(f"\nPrimary URL: {primary_url}")
        test_image_url(client.session, primary_url, "Series Primary")
        
        # Get seasons
        print(f"\nFetching seasons for {show.name}...")
        seasons = client.get_seasons(show.id)
        print(f"  Found {len(seasons)} seasons")
        
        if seasons:
            season = seasons[0]
            print(f"\n=== Testing images for: {season.name} ===")
            
            # Test season primary
            season_primary_url = client._get_image_url(season.id, "Primary", 720)
            print(f"\nSeason Primary URL: {season_primary_url}")
            test_image_url(client.session, season_primary_url, "Season Primary")
            
            # Get episodes
            print(f"\nFetching episodes for {season.name}...")
            episodes = client.get_episodes(show.id, season.id)
            print(f"  Found {len(episodes)} episodes")
            
            # Test episode images
            print(f"\n=== Testing episode images ===")
            for i, ep in enumerate(episodes[:5]):  # Test first 5 episodes
                print(f"\nE{ep.index_number}: {ep.name}")
                print(f"  primary_image_url from Episode object: {ep.primary_image_url}")
                
                # Construct URL manually to verify
                manual_url = client._get_image_url(ep.id, "Primary", 720)
                print(f"  Manually constructed URL: {manual_url}")
                
                test_image_url(client.session, ep.primary_image_url, f"Episode {ep.index_number} thumbnail")
        
        # Test theme song
        print(f"\n=== Testing theme song for: {show.name} ===")
        theme_url = client.get_theme_song_url(show.id)
        if theme_url:
            print(f"Theme URL: {theme_url}")
            test_image_url(client.session, theme_url, "Theme song")
        else:
            print("  No theme song available")
        
        print("\n=== Test Complete ===")
        
    except AuthenticationError as e:
        print(f"Authentication failed: {e}")
        sys.exit(1)
    except JellyfinConnectionError as e:
        print(f"Connection error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
