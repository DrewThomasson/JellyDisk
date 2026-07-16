/**
 * Jellyfin API Client Wrapper for JellyDiskWeb
 */

const CLIENT_NAME = "JellyDiskWeb";
const DEVICE_NAME = "Web Browser";
const DEVICE_ID = "jellydisk-web-emulator";
const CLIENT_VERSION = "1.0.0";

/**
 * Helper to construct headers with auth token
 */
function getHeaders(token = null) {
  const authParts = [
    `MediaBrowser Client="${CLIENT_NAME}"`,
    `Device="${DEVICE_NAME}"`,
    `DeviceId="${DEVICE_ID}"`,
    `Version="${CLIENT_VERSION}"`
  ];
  if (token) {
    authParts.push(`Token="${token}"`);
  }

  return {
    "X-Emby-Authorization": authParts.join(", "),
    "Content-Type": "application/json"
  };
}

/**
 * Normalize server URL (remove trailing slash)
 */
function cleanUrl(url) {
  if (!url) return "";
  return url.trim().replace(/\/+$/, "");
}

export const Jellyfin = {
  /**
   * Test connection and retrieve public server info
   */
  async getServerInfo(serverUrl) {
    const url = `${cleanUrl(serverUrl)}/System/Info/Public`;
    const res = await fetch(url);
    if (!res.ok) throw new Error("Could not reach Jellyfin server");
    return res.json();
  },

  /**
   * Authenticate and get AccessToken & UserId
   */
  async authenticate(serverUrl, username, password) {
    const baseUrl = cleanUrl(serverUrl);
    const url = `${baseUrl}/Users/AuthenticateByName`;
    
    const response = await fetch(url, {
      method: "POST",
      headers: getHeaders(),
      body: JSON.stringify({
        Username: username,
        Pw: password
      })
    });

    if (response.status === 401) {
      throw new Error("Invalid username or password");
    }
    if (!response.ok) {
      throw new Error("Authentication failed");
    }

    const data = await response.json();
    return {
      token: data.AccessToken,
      userId: data.User.Id,
      username: data.User.Name,
      serverUrl: baseUrl
    };
  },

  /**
   * Search shows and movies in the library
   */
  async searchLibrary(serverUrl, token, userId, query = "") {
    const baseUrl = cleanUrl(serverUrl);
    const url = new URL(`${baseUrl}/Users/${userId}/Items`);
    
    url.searchParams.append("IncludeItemTypes", "Series,Movie");
    url.searchParams.append("Recursive", "true");
    url.searchParams.append("Fields", "Overview,ProviderIds,Path");
    url.searchParams.append("SortBy", "SortName");
    url.searchParams.append("SortOrder", "Ascending");
    
    if (query) {
      url.searchParams.append("SearchTerm", query);
    }

    const res = await fetch(url.toString(), {
      headers: getHeaders(token)
    });

    if (!res.ok) throw new Error("Failed to search library");
    const data = await res.json();
    
    return (data.Items || []).map(item => ({
      id: item.Id,
      name: item.Name,
      overview: item.Overview || "",
      year: item.ProductionYear,
      rating: item.OfficialRating,
      backdropUrl: this.getImageUrl(baseUrl, item.Id, "Backdrop"),
      logoUrl: this.getImageUrl(baseUrl, item.Id, "Logo"),
      type: item.Type || "Series"
    }));
  },

  /**
   * Fetch full details for a media item
   */
  async getItemDetails(serverUrl, token, userId, itemId) {
    const baseUrl = cleanUrl(serverUrl);
    const url = `${baseUrl}/Users/${userId}/Items/${itemId}?Fields=People,Overview,RemoteTrailers`;
    
    const res = await fetch(url, {
      headers: getHeaders(token)
    });

    if (!res.ok) throw new Error("Failed to fetch item details");
    return res.json();
  },

  /**
   * Fetch local trailers associated with a media item
   */
  async getLocalTrailers(serverUrl, token, itemId) {
    const baseUrl = cleanUrl(serverUrl);
    const url = `${baseUrl}/Items/${itemId}/LocalTrailers`;
    
    const res = await fetch(url, {
      headers: getHeaders(token)
    });

    if (!res.ok) throw new Error("Failed to fetch local trailers");
    return res.json();
  },

  /**
   * Fetch seasons for a TV series, or a mock season for a Movie
   */
  async getSeasons(serverUrl, token, userId, seriesId) {
    const baseUrl = cleanUrl(serverUrl);
    const details = await this.getItemDetails(baseUrl, token, userId, seriesId);
    
    if (details.Type === "Movie") {
      return [{
        id: details.Id,
        name: "Movie",
        indexNumber: 1,
        seriesId: seriesId,
        seriesName: details.Name,
        overview: details.Overview || "",
        primaryImageUrl: this.getImageUrl(baseUrl, details.Id, "Primary")
      }];
    }

    const url = `${baseUrl}/Shows/${seriesId}/Seasons?Fields=Overview,Path`;
    const res = await fetch(url, {
      headers: getHeaders(token)
    });

    if (!res.ok) throw new Error("Failed to fetch seasons");
    const data = await res.json();

    return (data.Items || []).map(item => ({
      id: item.Id,
      name: item.Name,
      indexNumber: item.IndexNumber || 0,
      seriesId: seriesId,
      seriesName: item.SeriesName || details.Name,
      overview: item.Overview || "",
      primaryImageUrl: this.getImageUrl(baseUrl, item.Id, "Primary")
    }));
  },

  /**
   * Fetch episodes for a season, or a mock episode list for a Movie
   */
  async getEpisodes(serverUrl, token, userId, seriesId, seasonId) {
    const baseUrl = cleanUrl(serverUrl);
    const details = await this.getItemDetails(baseUrl, token, userId, seriesId);
    
    if (details.Type === "Movie") {
      return [{
        id: details.Id,
        name: details.Name,
        indexNumber: 1,
        overview: details.Overview || "",
        runtimeTicks: details.RunTimeTicks || 0,
        primaryImageUrl: this.getImageUrl(baseUrl, details.Id, "Primary"),
        mediaSources: details.MediaSources || []
      }];
    }

    const url = `${baseUrl}/Shows/${seriesId}/Episodes?SeasonId=${seasonId}&Fields=Overview,Path,MediaSources`;
    const res = await fetch(url, {
      headers: getHeaders(token)
    });

    if (!res.ok) throw new Error("Failed to fetch episodes");
    const data = await res.json();

    return (data.Items || []).map(item => ({
      id: item.Id,
      name: item.Name,
      indexNumber: item.IndexNumber || 0,
      overview: item.Overview || "",
      runtimeTicks: item.RunTimeTicks || 0,
      primaryImageUrl: this.getImageUrl(baseUrl, item.Id, "Primary"),
      mediaSources: item.MediaSources || []
    }));
  },

  /**
   * Construct URL for an item's image
   */
  getImageUrl(serverUrl, itemId, imageType, maxWidth = 720) {
    const baseUrl = cleanUrl(serverUrl);
    return `${baseUrl}/Items/${itemId}/Images/${imageType}?maxWidth=${maxWidth}`;
  },

  /**
   * Get direct stream URL for a video file
   */
  getStreamUrl(serverUrl, token, itemId) {
    const baseUrl = cleanUrl(serverUrl);
    return `${baseUrl}/Items/${itemId}/Download?api_key=${token}`;
  },

  /**
   * Get the theme song URL for a series if available
   */
  async getThemeSongUrl(serverUrl, token, seriesId) {
    const baseUrl = cleanUrl(serverUrl);
    try {
      const url = `${baseUrl}/Items/${seriesId}/ThemeSongs`;
      const res = await fetch(url, {
        headers: getHeaders(token)
      });
      if (!res.ok) return null;
      const data = await res.json();
      if (data.Items && data.Items.length > 0) {
        return `${baseUrl}/Items/${data.Items[0].Id}/Download?api_key=${token}`;
      }
    } catch (e) {
      console.warn("Error fetching theme song:", e);
    }
    return null;
  }
};
