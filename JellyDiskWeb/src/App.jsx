import React, { useState, useEffect, useRef } from 'react';
import { Jellyfin } from './jellyfin';
import './App.css';

// ----------------------------------------------------------------------
// Fallback DVD Questions (Exact match from menu_builder.py)
// ----------------------------------------------------------------------
const FALLBACK_TRIVIA = [
  {
    question: "What is the standard aspect ratio of a standard definition DVD?",
    options: ["4:3", "16:9 Anamorphic", "2.39:1 Cinema", "1.33:1 IMAX"],
    correct_index: 1
  },
  {
    question: "Which video standard is traditionally used in Europe and Asia?",
    options: ["NTSC", "PAL", "SECAM", "ATSC"],
    correct_index: 1
  },
  {
    question: "Which optical disc format succeeded the DVD in 2006?",
    options: ["HD-DVD", "Blu-ray Disc", "LaserDisc", "VCD"],
    correct_index: 1
  },
  {
    question: "What does 'CSS' stand for in DVD encryption?",
    options: ["Content Scramble System", "Copy Security System", "Cascading Style Sheets", "Core Sector Scrambler"],
    correct_index: 0
  },
  {
    question: "Which DVD region code covers the United States and Canada?",
    options: ["Region 1", "Region 2", "Region 4", "Region 0 (All)"],
    correct_index: 0
  },
  {
    question: "What is the physical storage capacity of a single-layer DVD-5?",
    options: ["4.7 GB", "8.5 GB", "700 MB", "25 GB"],
    correct_index: 0
  },
  {
    question: "What is the physical storage capacity of a dual-layer DVD-9?",
    options: ["4.7 GB", "8.5 GB", "9.4 GB", "15 GB"],
    correct_index: 1
  },
  {
    question: "Which file system is standard on DVD-Video discs?",
    options: ["FAT32", "NTFS", "UDF (Universal Disk Format)", "ISO 9660"],
    correct_index: 2
  },
  {
    question: "What format is standard DVD-Video compressed in?",
    options: ["MPEG-1", "MPEG-2", "H.264 / MPEG-4", "AV1"],
    correct_index: 1
  },
  {
    question: "Which analog copy protection system was built into most DVD players?",
    options: ["Macrovision", "FairPlay", "Widevine", "HDCP"],
    correct_index: 0
  },
  {
    question: "What is the term for fitting a 16:9 video onto a 4:3 DVD screen using black bars?",
    options: ["Anamorphic", "Letterboxing", "Pan and Scan", "Pillarboxing"],
    correct_index: 1
  },
  {
    question: "In what year were the first commercial DVD players and discs released in the US?",
    options: ["1995", "1997", "1999", "2001"],
    correct_index: 1
  }
];

// Helper to extract YouTube video ID and build the embed URL
function getYoutubeEmbedUrl(url) {
  if (!url) return null;
  let videoId = null;
  
  if (url.includes('youtube.com/watch')) {
    try {
      const searchParams = new URLSearchParams(url.split('?')[1]);
      videoId = searchParams.get('v');
    } catch (e) {
      console.warn("Error parsing youtube URL params", e);
    }
  } else if (url.includes('youtu.be/')) {
    videoId = url.split('youtu.be/')[1]?.split('?')[0];
  } else if (url.includes('youtube.com/embed/')) {
    videoId = url.split('youtube.com/embed/')[1]?.split('?')[0];
  }
  
  if (videoId) {
    return `https://www.youtube.com/embed/${videoId}?autoplay=1&enablejsapi=1&rel=0`;
  }
  return null;
}

function App() {
  // Connection states
  const [serverUrl, setServerUrl] = useState(import.meta.env.VITE_JELLYFIN_URL || '');
  const [username, setUsername] = useState(import.meta.env.VITE_JELLYFIN_USER || '');
  const [password, setPassword] = useState(import.meta.env.VITE_JELLYFIN_PASS || '');
  const [connection, setConnection] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  // Library browse states
  const [shows, setShows] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedShow, setSelectedShow] = useState(null);
  const [seasons, setSeasons] = useState([]);
  const [selectedSeason, setSelectedSeason] = useState(null);

  // DVD Player State
  const [isDvdActive, setIsDvdActive] = useState(false);
  const [dvdScreen, setDvdScreen] = useState('main'); // main, setup, episodes, cast, trivia, trivia_wrong, trivia_win
  const [episodes, setEpisodes] = useState([]);
  const [themeSongUrl, setThemeSongUrl] = useState(null);
  const [showDetails, setShowDetails] = useState(null);
  
  // Trailer States
  const [localTrailerUrl, setLocalTrailerUrl] = useState(null);
  const [youtubeTrailerEmbedUrl, setYoutubeTrailerEmbedUrl] = useState(null);
  const [playingTrailerUrl, setPlayingTrailerUrl] = useState(null);
  const [playingTrailerType, setPlayingTrailerType] = useState('local'); // local | youtube

  // Navigation indexes
  const [activeBtnIdx, setActiveBtnIdx] = useState(0);
  const [epPageIndex, setEpPageIndex] = useState(0);
  const [castPageIndex, setCastPageIndex] = useState(0);

  // Trivia progress
  const [triviaQuestions, setTriviaQuestions] = useState([]);
  const [triviaIndex, setTriviaIndex] = useState(0);

  // Settings
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [crtFilter, setCrtFilter] = useState(true);
  const [scanlines, setScanlines] = useState(true);
  const [isMuted, setIsMuted] = useState(false);

  // Video playback
  const [playingVideoUrl, setPlayingVideoUrl] = useState(null);
  const [activeSubtitleUrl, setActiveSubtitleUrl] = useState(null);
  const [isPlayingAll, setIsPlayingAll] = useState(false);
  const [playingEpisodeIndex, setPlayingEpisodeIndex] = useState(0);

  const audioRef = useRef(null);
  const videoRef = useRef(null);

  // Load credential parameters or handle auto-login if configured
  useEffect(() => {
    // Attempt local storage connection recovery if available
    const saved = localStorage.getItem('jellydisk_conn');
    if (saved) {
      try {
        const conn = JSON.parse(saved);
        setConnection(conn);
        loadShows(conn);
      } catch (e) {
        localStorage.removeItem('jellydisk_conn');
      }
    }
  }, []);

  // Handle theme song / trivia music looping
  useEffect(() => {
    if (audioRef.current) {
      const isTriviaScreen = dvdScreen === 'trivia' || dvdScreen === 'trivia_wrong' || dvdScreen === 'trivia_win';
      // If it's trivia screen, loop the Copied trivia_bg.mp3, else loop the show's theme song
      const activeAudio = isTriviaScreen ? '/trivia_bg.mp3' : themeSongUrl;

      if (isDvdActive && activeAudio && !playingVideoUrl && !playingTrailerUrl) {
        audioRef.current.volume = isMuted ? 0 : 0.35;
        
        // Match source URL exactly to avoid re-triggering loader
        const expectedSrc = activeAudio.startsWith('http') ? activeAudio : window.location.origin + activeAudio;
        if (audioRef.current.src !== expectedSrc) {
          audioRef.current.src = activeAudio;
          audioRef.current.load();
        }
        audioRef.current.play().catch(e => console.log("Audio play blocked: require interaction."));
      } else {
        audioRef.current.pause();
      }
    }
  }, [isDvdActive, themeSongUrl, dvdScreen, playingVideoUrl, playingTrailerUrl, isMuted]);

  // Keyboard navigation listener
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (!isDvdActive) return;
      if (playingVideoUrl || playingTrailerUrl) {
        // If playing video/trailer, escape/backspace returns to menu
        if (e.key === 'Escape' || e.key === 'Backspace') {
          stopVideo();
          setPlayingTrailerUrl(null);
        }
        return;
      }

      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault();
          moveSelection('UP');
          break;
        case 'ArrowDown':
          e.preventDefault();
          moveSelection('DOWN');
          break;
        case 'ArrowLeft':
          e.preventDefault();
          moveSelection('LEFT');
          break;
        case 'ArrowRight':
          e.preventDefault();
          moveSelection('RIGHT');
          break;
        case 'Enter':
          e.preventDefault();
          triggerButton();
          break;
        case 'Backspace':
        case 'Escape':
          e.preventDefault();
          goBackScreen();
          break;
        default:
          break;
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isDvdActive, dvdScreen, activeBtnIdx, epPageIndex, castPageIndex, episodes, triviaIndex, triviaQuestions, playingVideoUrl, playingTrailerUrl]);

  // Login handler
  const handleConnect = async (e) => {
    e.preventDefault();
    if (!serverUrl) return setError('Server URL is required');
    setIsLoading(true);
    setError('');

    try {
      const conn = await Jellyfin.authenticate(serverUrl, username, password);
      setConnection(conn);
      localStorage.setItem('jellydisk_conn', JSON.stringify(conn));
      await loadShows(conn);
    } catch (e) {
      setError(e.message || 'Connection failed');
    } finally {
      setIsLoading(false);
    }
  };

  const handleLogout = () => {
    setConnection(null);
    setShows([]);
    setSelectedShow(null);
    setSelectedSeason(null);
    setIsDvdActive(false);
    localStorage.removeItem('jellydisk_conn');
  };

  // Load TV shows/movies
  const loadShows = async (conn) => {
    setIsLoading(true);
    try {
      const list = await Jellyfin.searchLibrary(conn.serverUrl, conn.token, conn.userId);
      setShows(list);
    } catch (e) {
      setError('Failed to fetch shows from library');
    } finally {
      setIsLoading(false);
    }
  };

  // Search filter
  const handleSearch = async () => {
    if (!connection) return;
    setIsLoading(true);
    try {
      const list = await Jellyfin.searchLibrary(connection.serverUrl, connection.token, connection.userId, searchQuery);
      setShows(list);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  // Select show to load seasons
  const selectShow = async (show) => {
    setSelectedShow(show);
    setIsLoading(true);
    try {
      const list = await Jellyfin.getSeasons(connection.serverUrl, connection.token, connection.userId, show.id);
      setSeasons(list);
      // Auto-fetch show credits and overview details
      const details = await Jellyfin.getItemDetails(connection.serverUrl, connection.token, connection.userId, show.id);
      setShowDetails(details);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  // Boot DVD Player for Selected Season
  const startDvd = async (season) => {
    setSelectedSeason(season);
    setIsLoading(true);
    try {
      // Load episodes
      const epList = await Jellyfin.getEpisodes(connection.serverUrl, connection.token, connection.userId, selectedShow.id, season.id);
      setEpisodes(epList);

      // Fetch theme song
      const songUrl = await Jellyfin.getThemeSongUrl(connection.serverUrl, connection.token, selectedShow.id);
      setThemeSongUrl(songUrl);

      // Fetch local trailers
      let localTrailer = null;
      try {
        const localTrailers = await Jellyfin.getLocalTrailers(connection.serverUrl, connection.token, selectedShow.id);
        if (localTrailers && localTrailers.length > 0) {
          localTrailer = Jellyfin.getStreamUrl(connection.serverUrl, connection.token, localTrailers[0].Id);
        }
      } catch (e) {
        console.warn("Failed to fetch local trailers:", e);
      }
      setLocalTrailerUrl(localTrailer);

      // Parse remote YouTube trailer
      let remoteTrailer = null;
      if (showDetails?.RemoteTrailers && showDetails.RemoteTrailers.length > 0) {
        remoteTrailer = getYoutubeEmbedUrl(showDetails.RemoteTrailers[0].Url);
      }
      setYoutubeTrailerEmbedUrl(remoteTrailer);

      // Pre-generate Trivia questions
      const generatedTrivia = buildTrivia(selectedShow, season, epList, showDetails);
      setTriviaQuestions(generatedTrivia);
      setTriviaIndex(0);

      // Initialize UI state
      setDvdScreen('main');
      setActiveBtnIdx(0);
      setEpPageIndex(0);
      setCastPageIndex(0);
      setIsDvdActive(true);
    } catch (e) {
      console.error(e);
    } finally {
      setIsLoading(false);
    }
  };

  // Exit DVD Player
  const exitDvd = () => {
    setIsDvdActive(false);
    setThemeSongUrl(null);
    setEpisodes([]);
    setPlayingVideoUrl(null);
    setPlayingTrailerUrl(null);
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(() => {});
    }
  };

  const toggleFullscreen = () => {
    const playerEl = document.querySelector('.dvd-player-frame');
    if (!playerEl) return;
    
    if (!document.fullscreenElement) {
      playerEl.requestFullscreen().catch(err => {
        console.error(`Error attempting to enable fullscreen: ${err.message}`);
      });
    } else {
      document.exitFullscreen().catch(() => {});
    }
  };

  // ----------------------------------------------------------------------
  // DVD Interactive Navigation Mapping
  // ----------------------------------------------------------------------
  
  // Return list of buttons on the active screen
  const getScreenButtons = () => {
    if (dvdScreen === 'main') {
      const btns = ['PLAY ALL', 'EPISODE SELECT'];
      if (showDetails?.People?.some(p => p.Type === 'Actor')) btns.push('CAST & INFO');
      if (localTrailerUrl || youtubeTrailerEmbedUrl) btns.push('PLAY TRAILER');
      btns.push('SUBTITLES SETUP');
      if (triviaQuestions.length > 0) btns.push('PLAY TRIVIA');
      return btns;
    }
    
    if (dvdScreen === 'setup') {
      return ['SUBTITLES ON', 'SUBTITLES OFF', 'BACK TO MAIN'];
    }

    if (dvdScreen === 'episodes') {
      // Episodes grid has up to 6 thumbnails on current page
      const pageEps = episodes.slice(epPageIndex * 6, (epPageIndex + 1) * 6);
      const btns = pageEps.map((ep, i) => `EPISODE_${i}`);
      
      // Bottom navigation buttons
      if (epPageIndex > 0) btns.push('PREV PAGE');
      btns.push('MAIN MENU');
      if ((epPageIndex + 1) * 6 < episodes.length) btns.push('NEXT PAGE');
      
      return btns;
    }

    if (dvdScreen === 'cast') {
      const btns = [];
      const pageSize = 6;
      const actors = showDetails?.People?.filter(p => p.Type === 'Actor') || [];
      const totalPages = Math.ceil(actors.length / pageSize);

      btns.push('BACK TO MAIN');
      if (castPageIndex > 0) btns.push('PREV PAGE');
      if (castPageIndex < totalPages - 1) btns.push('NEXT PAGE');
      return btns;
    }

    if (dvdScreen === 'trivia') {
      // 4 choices + exit
      return ['OPT_0', 'OPT_1', 'OPT_2', 'OPT_3', 'EXIT GAME'];
    }

    if (dvdScreen === 'trivia_wrong') {
      return ['TRY AGAIN', 'MAIN MENU'];
    }

    if (dvdScreen === 'trivia_win') {
      return ['BACK TO MAIN'];
    }

    return [];
  };

  // Move highlight pointer
  const moveSelection = (direction) => {
    const btns = getScreenButtons();
    if (btns.length === 0) return;

    // Standard vertical list layouts: main, setup, trivia_wrong, trivia_win
    if (dvdScreen === 'main' || dvdScreen === 'setup' || dvdScreen === 'trivia_wrong' || dvdScreen === 'trivia_win') {
      if (direction === 'UP') {
        setActiveBtnIdx((activeBtnIdx - 1 + btns.length) % btns.length);
      } else if (direction === 'DOWN') {
        setActiveBtnIdx((activeBtnIdx + 1) % btns.length);
      }
      return;
    }

    // Grid Layouts: Episodes menu (6 grid items + bottom nav buttons)
    if (dvdScreen === 'episodes') {
      const pageEpsCount = Math.min(6, episodes.length - epPageIndex * 6);
      
      let isBottomNav = activeBtnIdx >= pageEpsCount;
      let bottomNavIndex = activeBtnIdx - pageEpsCount; 
      const bottomBtnsCount = btns.length - pageEpsCount;

      if (!isBottomNav) {
        const row = Math.floor(activeBtnIdx / 3);
        const col = activeBtnIdx % 3;

        if (direction === 'UP') {
          if (row > 0) {
            setActiveBtnIdx(activeBtnIdx - 3);
          }
        } else if (direction === 'DOWN') {
          if (row === 0 && pageEpsCount > 3) {
            const nextIdx = activeBtnIdx + 3;
            setActiveBtnIdx(nextIdx < pageEpsCount ? nextIdx : pageEpsCount - 1);
          } else {
            const hasPrev = epPageIndex > 0;
            const targetBottom = hasPrev ? 1 : 0;
            setActiveBtnIdx(pageEpsCount + Math.min(targetBottom, bottomBtnsCount - 1));
          }
        } else if (direction === 'LEFT') {
          if (col > 0) {
            setActiveBtnIdx(activeBtnIdx - 1);
          } else {
            setActiveBtnIdx(activeBtnIdx + Math.min(2, pageEpsCount - activeBtnIdx - 1));
          }
        } else if (direction === 'RIGHT') {
          if (col < 2 && activeBtnIdx + 1 < pageEpsCount) {
            setActiveBtnIdx(activeBtnIdx + 1);
          } else {
            setActiveBtnIdx(Math.floor(activeBtnIdx / 3) * 3); 
          }
        }
      } else {
        if (direction === 'UP') {
          if (pageEpsCount > 3) {
            setActiveBtnIdx(Math.min(4, pageEpsCount - 1));
          } else {
            setActiveBtnIdx(Math.min(1, pageEpsCount - 1));
          }
        } else if (direction === 'LEFT') {
          const nextBottom = (bottomNavIndex - 1 + bottomBtnsCount) % bottomBtnsCount;
          setActiveBtnIdx(pageEpsCount + nextBottom);
        } else if (direction === 'RIGHT') {
          const nextBottom = (bottomNavIndex + 1) % bottomBtnsCount;
          setActiveBtnIdx(pageEpsCount + nextBottom);
        }
      }
      return;
    }

    // Horizontal bottom list: Cast Screen
    if (dvdScreen === 'cast') {
      if (direction === 'LEFT') {
        setActiveBtnIdx((activeBtnIdx - 1 + btns.length) % btns.length);
      } else if (direction === 'RIGHT') {
        setActiveBtnIdx((activeBtnIdx + 1) % btns.length);
      }
      return;
    }

    // 2x2 Grid Layouts: Trivia Options (with bottom EXIT button)
    if (dvdScreen === 'trivia') {
      if (activeBtnIdx === 4) {
        // Focused on EXIT GAME at bottom
        if (direction === 'UP') {
          setActiveBtnIdx(2); // Focus C (bottom-left)
        }
      } else {
        const row = Math.floor(activeBtnIdx / 2);
        const col = activeBtnIdx % 2;

        if (direction === 'UP') {
          if (row > 0) setActiveBtnIdx(activeBtnIdx - 2);
        } else if (direction === 'DOWN') {
          if (row === 0) {
            setActiveBtnIdx(activeBtnIdx + 2);
          } else {
            setActiveBtnIdx(4); // Focus EXIT GAME
          }
        } else if (direction === 'LEFT' || direction === 'RIGHT') {
          setActiveBtnIdx((row * 2) + (col === 0 ? 1 : 0));
        }
      }
      return;
    }
  };

  // Button select execution
  const triggerButton = () => {
    const btns = getScreenButtons();
    if (btns.length === 0 || activeBtnIdx >= btns.length) return;
    
    const btnLabel = btns[activeBtnIdx];

    // Main Menu execution
    if (dvdScreen === 'main') {
      if (btnLabel === 'PLAY ALL') {
        playEpisodeSequence(0);
      } else if (btnLabel === 'EPISODE SELECT') {
        setDvdScreen('episodes');
        setActiveBtnIdx(0);
      } else if (btnLabel === 'CAST & INFO') {
        setDvdScreen('cast');
        setActiveBtnIdx(0);
        setCastPageIndex(0);
      } else if (btnLabel === 'PLAY TRAILER') {
        if (localTrailerUrl) {
          setPlayingTrailerUrl(localTrailerUrl);
          setPlayingTrailerType('local');
        } else if (youtubeTrailerEmbedUrl) {
          setPlayingTrailerUrl(youtubeTrailerEmbedUrl);
          setPlayingTrailerType('youtube');
        }
      } else if (btnLabel === 'SUBTITLES SETUP') {
        setDvdScreen('setup');
        setActiveBtnIdx(0);
      } else if (btnLabel === 'PLAY TRIVIA') {
        setDvdScreen('trivia');
        setTriviaIndex(0);
        setActiveBtnIdx(0);
      }
      return;
    }

    // Setup Menu execution
    if (dvdScreen === 'setup') {
      if (btnLabel === 'SUBTITLES ON') {
        setSubtitlesEnabled(true);
      } else if (btnLabel === 'SUBTITLES OFF') {
        setSubtitlesEnabled(false);
      } else if (btnLabel === 'BACK TO MAIN') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
      }
      return;
    }

    // Episodes Menu execution
    if (dvdScreen === 'episodes') {
      const pageEpsCount = Math.min(6, episodes.length - epPageIndex * 6);
      if (btnLabel.startsWith('EPISODE_')) {
        const epIndex = epPageIndex * 6 + parseInt(btnLabel.split('_')[1]);
        playSingleEpisode(epIndex);
      } else if (btnLabel === 'PREV PAGE') {
        setEpPageIndex(epPageIndex - 1);
        setActiveBtnIdx(0);
      } else if (btnLabel === 'NEXT PAGE') {
        setEpPageIndex(epPageIndex + 1);
        setActiveBtnIdx(0);
      } else if (btnLabel === 'MAIN MENU') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
      }
      return;
    }

    // Cast Screen execution
    if (dvdScreen === 'cast') {
      if (btnLabel === 'BACK TO MAIN') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
      } else if (btnLabel === 'PREV PAGE') {
        setCastPageIndex(castPageIndex - 1);
        setActiveBtnIdx(0);
      } else if (btnLabel === 'NEXT PAGE') {
        setCastPageIndex(castPageIndex + 1);
        setActiveBtnIdx(0);
      }
      return;
    }

    // Trivia Challenge execution
    if (dvdScreen === 'trivia') {
      if (btnLabel === 'EXIT GAME') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
        return;
      }
      
      const currentQ = triviaQuestions[triviaIndex];
      const selectedOptIdx = parseInt(btnLabel.split('_')[1]);

      if (selectedOptIdx === currentQ.correct_index) {
        if (triviaIndex + 1 < triviaQuestions.length) {
          setTriviaIndex(triviaIndex + 1);
          setActiveBtnIdx(0);
        } else {
          setDvdScreen('trivia_win');
          setActiveBtnIdx(0);
        }
      } else {
        setDvdScreen('trivia_wrong');
        setActiveBtnIdx(0);
      }
      return;
    }

    // Trivia wrong screen
    if (dvdScreen === 'trivia_wrong') {
      if (btnLabel === 'TRY AGAIN') {
        setDvdScreen('trivia');
        setTriviaIndex(0);
        setActiveBtnIdx(0);
      } else if (btnLabel === 'MAIN MENU') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
      }
      return;
    }

    // Trivia win screen
    if (dvdScreen === 'trivia_win') {
      if (btnLabel === 'BACK TO MAIN') {
        setDvdScreen('main');
        setActiveBtnIdx(0);
      }
      return;
    }
  };

  // Back action (Backspace/Escape)
  const goBackScreen = () => {
    if (dvdScreen === 'main') {
      exitDvd();
    } else if (dvdScreen === 'episodes' || dvdScreen === 'cast' || dvdScreen === 'setup' || dvdScreen === 'trivia') {
      setDvdScreen('main');
      setActiveBtnIdx(0);
    } else if (dvdScreen === 'trivia_wrong' || dvdScreen === 'trivia_win') {
      setDvdScreen('main');
      setActiveBtnIdx(0);
    }
  };

  // ----------------------------------------------------------------------
  // Video Streaming Handlers
  // ----------------------------------------------------------------------
  
  const getEpisodeSubtitleTrackUrl = (ep) => {
    if (!ep || !ep.mediaSources || ep.mediaSources.length === 0) return null;
    const mediaSource = ep.mediaSources[0];
    if (!mediaSource || !mediaSource.MediaStreams) return null;
    
    // Find the first Subtitle stream (e.g. English)
    const subStream = mediaSource.MediaStreams.find(s => s.Type === 'Subtitle');
    if (!subStream) return null;
    
    return `${connection.serverUrl}/Videos/${ep.id}/Subtitles/${subStream.Index}/0/Stream.vtt?api_key=${connection.token}`;
  };

  // Single episode playback
  const playSingleEpisode = (epIdx) => {
    const ep = episodes[epIdx];
    if (!ep) return;
    
    setIsPlayingAll(false);
    setPlayingEpisodeIndex(epIdx);
    
    const subUrl = getEpisodeSubtitleTrackUrl(ep);
    setActiveSubtitleUrl(subUrl);

    const videoUrl = Jellyfin.getStreamUrl(connection.serverUrl, connection.token, ep.id);
    setPlayingVideoUrl(videoUrl);
  };

  // Play All sequence
  const playEpisodeSequence = (epIdx) => {
    const ep = episodes[epIdx];
    if (!ep) {
      stopVideo();
      return;
    }
    
    setIsPlayingAll(true);
    setPlayingEpisodeIndex(epIdx);

    const subUrl = getEpisodeSubtitleTrackUrl(ep);
    setActiveSubtitleUrl(subUrl);

    const videoUrl = Jellyfin.getStreamUrl(connection.serverUrl, connection.token, ep.id);
    setPlayingVideoUrl(videoUrl);
  };

  const stopVideo = () => {
    setPlayingVideoUrl(null);
    setActiveSubtitleUrl(null);
    setIsPlayingAll(false);
  };

  const handleVideoEnded = () => {
    if (isPlayingAll) {
      const nextIdx = playingEpisodeIndex + 1;
      if (nextIdx < episodes.length) {
        playEpisodeSequence(nextIdx);
      } else {
        stopVideo();
      }
    } else {
      stopVideo();
    }
  };

  // ----------------------------------------------------------------------
  // Dynamic Trivia builder (Identical logic to Python burner)
  // ----------------------------------------------------------------------
  const buildTrivia = (show, season, epList, details) => {
    const qList = [];
    const actorPeople = details?.People?.filter(p => p.Type === 'Actor') || [];
    
    // 1. Cast Questions (up to 8)
    const validActors = actorPeople.filter(p => p.Name && p.Role);
    const shuffledActors = [...validActors].sort(() => Math.random() - 0.5);
    const chosenActors = shuffledActors.slice(0, Math.min(8, shuffledActors.length));
    
    chosenActors.forEach(actor => {
      const distractors = actorPeople
        .filter(p => p.Name !== actor.Name)
        .map(p => p.Name)
        .concat(["Zach Hadel", "Michael Cusack", "Drew Thomasson", "John Carpenter", "Kurt Russell", "Donald Pleasence"])
        .filter((name, idx, self) => self.indexOf(name) === idx && name !== actor.Name)
        .sort(() => Math.random() - 0.5)
        .slice(0, 3);
      
      while (distractors.length < 3) {
        distractors.push(`Generic Actor ${distractors.length + 1}`);
      }

      const options = [...distractors, actor.Name].sort(() => Math.random() - 0.5);
      
      qList.push({
        question: `Who plays the character '${actor.Role}' in ${show.name}?`,
        options: options,
        correct_index: options.indexOf(actor.Name)
      });
    });

    // 2. Release Year
    if (show.year) {
      const year = parseInt(show.year);
      const optionYears = [year, year - 2, year + 3, year - 5].filter((v, i, a) => a.indexOf(v) === i);
      while (optionYears.length < 4) {
        optionYears.push(optionYears[optionYears.length - 1] + 1);
      }
      const options = optionYears.map(String).sort(() => Math.random() - 0.5);
      qList.push({
        question: `In what year was ${show.name} released?`,
        options: options,
        correct_index: options.indexOf(String(year))
      });
    }

    // 3. Directors (up to 2)
    const directors = details?.People?.filter(p => p.Type === 'Director') || [];
    directors.slice(0, 2).forEach((dir, idx) => {
      const otherDirs = ["Steven Spielberg", "Christopher Nolan", "Quentin Tarantino", "Martin Scorsese", "James Cameron"];
      const distractors = otherDirs.filter(d => d !== dir.Name).sort(() => Math.random() - 0.5).slice(0, 3);
      const options = [...distractors, dir.Name].sort(() => Math.random() - 0.5);
      
      qList.push({
        question: idx === 0 ? `Who directed the movie ${show.name}?` : `Who is listed as a co-director for ${show.name}?`,
        options: options,
        correct_index: options.indexOf(dir.Name)
      });
    });

    // 4. Writers (up to 2)
    const writers = details?.People?.filter(p => p.Type === 'Writer') || [];
    writers.slice(0, 2).forEach((writer, idx) => {
      const otherWriters = ["George Lucas", "Stephen King", "Harold Ramis", "John Carpenter", "Nick Castle"];
      const distractors = otherWriters.filter(w => w !== writer.Name).sort(() => Math.random() - 0.5).slice(0, 3);
      const options = [...distractors, writer.Name].sort(() => Math.random() - 0.5);
      
      qList.push({
        question: idx === 0 ? `Who is listed as a writer for ${show.name}?` : `Who co-wrote the screenplay/teleplay for ${show.name}?`,
        options: options,
        correct_index: options.indexOf(writer.Name)
      });
    });

    // 5. Episode Name checks
    if (epList && epList.length > 1) {
      const chosenEps = [...epList].sort(() => Math.random() - 0.5).slice(0, Math.min(4, epList.length));
      chosenEps.forEach(ep => {
        const fakeNames = [
          "The Lost Episode", "A Very Special Occasion", "Pineapple Express Incident",
          "The Unexpected Journey", "Escape from Reality", "A Bad Day at the Office",
          "The Midnight Run", "Return of the Legend", "The Final Chapter", "A New Beginning"
        ];
        const distractors = fakeNames
          .filter(f => f.toLowerCase() !== ep.name.toLowerCase())
          .sort(() => Math.random() - 0.5)
          .slice(0, 3);
        
        const options = [...distractors, ep.name].sort(() => Math.random() - 0.5);
        qList.push({
          question: `Which of the following is a real episode from this season?`,
          options: options,
          correct_index: options.indexOf(ep.name)
        });
      });
    }

    // 6. Fallback General DVD Questions
    FALLBACK_TRIVIA.forEach(fQ => {
      if (qList.length < 20) {
        if (!qList.some(q => q.question === fQ.question)) {
          qList.push(fQ);
        }
      }
    });

    return qList.slice(0, 20);
  };

  // Click handler wrapper for text buttons (triggers select action)
  const handleBtnClick = (idx) => {
    setActiveBtnIdx(idx);
    setTimeout(() => {
      triggerButton();
    }, 50);
  };

  // Return background layout properties
  const getDvdBgStyle = () => {
    if (!selectedShow) return {};
    const url = selectedShow.backdropUrl;
    return {
      backgroundImage: `url('${url}')`
    };
  };

  return (
    <div className="jellydisk-app">
      {/* ----------------------------------------------------
         Left side: Setup or Library search panel
         ---------------------------------------------------- */}
      {!connection ? (
        <div className="setup-panel">
          <h2>JellyDisk Web</h2>
          <p>
            Welcome to the JellyDisk DVD Emulator web interface. Connect to your Jellyfin server to stream shows and movies with real interactive DVD menus.
          </p>

          {error && <div className="error-message">{error}</div>}

          <form onSubmit={handleConnect}>
            <div className="setup-form-group">
              <label>Jellyfin Server URL</label>
              <input 
                type="url" 
                placeholder="https://yourjellyfin.com" 
                value={serverUrl} 
                onChange={(e) => setServerUrl(e.target.value)} 
                required 
              />
            </div>
            <div className="setup-form-group">
              <label>Username</label>
              <input 
                type="text" 
                placeholder="admin" 
                value={username} 
                onChange={(e) => setUsername(e.target.value)} 
                required 
              />
            </div>
            <div className="setup-form-group">
              <label>Password</label>
              <input 
                type="password" 
                placeholder="••••••••" 
                value={password} 
                onChange={(e) => setPassword(e.target.value)} 
              />
            </div>
            <button type="submit" className="setup-btn" disabled={isLoading}>
              {isLoading ? 'Connecting...' : 'Connect'}
            </button>
          </form>
        </div>
      ) : (
        /* Authenticated Library Panel */
        !isDvdActive && (
          <div className="library-panel">
            <div className="library-header">
              <h2 className="library-title">JellyDisk Library</h2>
              <div className="library-search-container">
                <input 
                  type="text" 
                  placeholder="Search series or movies..." 
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                />
                <button className="setup-btn" style={{margin: 0, width: 'auto'}} onClick={handleSearch}>Search</button>
              </div>
              <button className="logout-btn" onClick={handleLogout}>Disconnect</button>
            </div>

            {isLoading ? (
              <div style={{padding: '50px', fontSize: '1.2rem', color: 'var(--color-text-secondary)'}}>Loading media assets...</div>
            ) : !selectedShow ? (
              <div className="library-grid">
                {shows.map(show => (
                  <div className="show-card" key={show.id} onClick={() => selectShow(show)}>
                    <img 
                      className="show-card-image" 
                      src={Jellyfin.getImageUrl(connection.serverUrl, show.id, 'Primary', 300)} 
                      alt={show.name} 
                      onError={(e) => { e.target.src = 'https://placehold.co/300x450/111/fff?text=No+Poster'; }}
                    />
                    <div className="show-card-info">
                      <h4 className="show-card-title">{show.name}</h4>
                      <span className="show-card-meta">{show.type} • {show.year || 'N/A'}</span>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              /* Season Selector Screen */
              <div className="season-selector">
                <button className="back-nav-btn" onClick={() => setSelectedShow(null)}>
                  ← Back to Library
                </button>
                <h3>{selectedShow.name} - Select Disc/Season</h3>
                <div className="season-grid">
                  {seasons.map(season => (
                    <div className="season-card" key={season.id} onClick={() => startDvd(season)}>
                      <img 
                        className="season-card-img" 
                        src={season.primaryImageUrl} 
                        alt={season.name} 
                        onError={(e) => { e.target.src = 'https://placehold.co/300x450/111/fff?text=No+Poster'; }}
                      />
                      <div className="season-card-name">{season.name}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )
      )}

      {/* ----------------------------------------------------
         DVD Player Core Screen (16:9 box ratio)
         ---------------------------------------------------- */}
      {isDvdActive && (
        <div className={`dvd-player-frame ${crtFilter ? 'crt-active' : ''}`}>
          {/* Optional Scanlines & Bezel overlays */}
          {crtFilter && <div className="crt-overlay"></div>}
          {crtFilter && <div className="crt-vignette"></div>}
          {crtFilter && <div className="crt-bezel"></div>}
          {crtFilter && <div className="crt-glare"></div>}
          {scanlines && <div className="dvd-retro-scanlines"></div>}

          {/* Audio looping player (Loops themeSongUrl or /trivia_bg.mp3 based on screen state) */}
          <audio 
            ref={audioRef} 
            loop 
          />

          {/* Fullscreen Episode Video Streaming Layer */}
          {playingVideoUrl && (
            <div className="dvd-video-container">
              <span className="video-back-indicator">Press ESC / Backspace to Return</span>
              <video 
                ref={videoRef}
                className="dvd-video-player"
                src={playingVideoUrl}
                autoPlay
                controls
                onEnded={handleVideoEnded}
              >
                {/* HTML5 Subtitles Toggle */}
                {subtitlesEnabled && activeSubtitleUrl && (
                  <track 
                    label="English" 
                    kind="subtitles" 
                    srcLang="en" 
                    src={activeSubtitleUrl} 
                    default 
                  />
                )}
              </video>
            </div>
          )}

          {/* Fullscreen Video/YouTube Trailer Streaming Layer */}
          {playingTrailerUrl && (
            <div className="dvd-video-container">
              <span className="video-back-indicator">Press ESC / Backspace to Return</span>
              {playingTrailerType === 'local' ? (
                <video 
                  className="dvd-video-player"
                  src={playingTrailerUrl}
                  autoPlay
                  controls
                  onEnded={() => setPlayingTrailerUrl(null)}
                />
              ) : (
                <iframe
                  className="dvd-video-player"
                  style={{ border: 'none', width: '100%', height: '100%', background: '#000' }}
                  src={playingTrailerUrl}
                  allow="autoplay; encrypted-media"
                  allowFullScreen
                  title="YouTube Trailer"
                />
              )}
            </div>
          )}

          {/* Interactive Screen Display */}
          <div 
            className={`dvd-screen ${scanlines ? 'dvd-retro-blur' : ''}`} 
            style={getDvdBgStyle()}
          >
            {/* Dark blend overlay matching Pillow's logic */}
            <div className="dvd-backdrop-dimmer"></div>

            {/* Audio Muted Banner if browser blocked autoplay */}
            {isMuted && (
              <div className="audio-muted-banner" onClick={() => setIsMuted(false)}>
                🔇 Theme Song Muted (Click to Unmute)
              </div>
            )}

            <div className="dvd-content">
              {/* DVD Title Logo or Header */}
              <div className="dvd-header">
                {selectedShow.logoUrl ? (
                  <img 
                    className="dvd-logo" 
                    src={selectedShow.logoUrl} 
                    alt={selectedShow.name}
                    onError={(e) => { e.target.style.display = 'none'; }} 
                  />
                ) : (
                  <h1 className="dvd-title-fallback">{selectedShow.name}</h1>
                )}
              </div>

              {/* Sub-menu Navigation Title indicators */}
              {dvdScreen === 'episodes' && (
                <div className="dvd-subtitle">Select Episode - Page {epPageIndex + 1} of {Math.ceil(episodes.length / 6)}</div>
              )}
              {dvdScreen === 'cast' && (
                <div className="dvd-subtitle">Cast & Crew - Page {castPageIndex + 1} of {Math.ceil((showDetails?.People?.filter(p => p.Type === 'Actor').length || 0) / 6)}</div>
              )}
              {dvdScreen === 'setup' && (
                <div className="dvd-subtitle">Subtitles Setup</div>
              )}
              {dvdScreen === 'trivia' && (
                <div className="dvd-subtitle">Trivia Game (Question {triviaIndex + 1}/20)</div>
              )}

              {/* -----------------------------------------------
                 SCREEN 1: Main Menu
                 ----------------------------------------------- */}
              {dvdScreen === 'main' && (
                <div className="dvd-body">
                  <div className="dvd-buttons-vertical">
                    {getScreenButtons().map((label, idx) => (
                      <button 
                        key={label}
                        className={`dvd-btn ${activeBtnIdx === idx ? 'highlighted' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(idx)}
                        onClick={() => handleBtnClick(idx)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* -----------------------------------------------
                 SCREEN 2: Episode Grid Selection
                 ----------------------------------------------- */}
              {dvdScreen === 'episodes' && (
                <div className="dvd-body">
                  <div className="dvd-episode-grid">
                    {episodes.slice(epPageIndex * 6, (epPageIndex + 1) * 6).map((ep, i) => {
                      const absoluteIndex = epPageIndex * 6 + i;
                      const isHighlighted = activeBtnIdx === i;
                      
                      return (
                        <div 
                          key={ep.id}
                          className={`dvd-episode-card ${isHighlighted ? 'highlighted' : ''}`}
                          onMouseEnter={() => setActiveBtnIdx(i)}
                          onClick={() => handleBtnClick(i)}
                        >
                          <div className="dvd-episode-thumb-container">
                            {ep.primaryImageUrl ? (
                              <img className="dvd-episode-thumb" src={ep.primaryImageUrl} alt={ep.name} />
                            ) : (
                              <div className="dvd-episode-placeholder-text">E{ep.indexNumber || absoluteIndex + 1}</div>
                            )}
                          </div>
                          <div className="dvd-episode-title">
                            E{ep.indexNumber || absoluteIndex + 1}. {ep.name}
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Navigation Row */}
                  <div className="dvd-nav-bottom">
                    {getScreenButtons().slice(Math.min(6, episodes.length - epPageIndex * 6)).map((label, i) => {
                      const gridCount = Math.min(6, episodes.length - epPageIndex * 6);
                      const targetIdx = gridCount + i;
                      const isHighlighted = activeBtnIdx === targetIdx;

                      return (
                        <button
                          key={label}
                          className={`dvd-btn ${isHighlighted ? 'highlighted' : ''}`}
                          onMouseEnter={() => setActiveBtnIdx(targetIdx)}
                          onClick={() => handleBtnClick(targetIdx)}
                        >
                          {label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* -----------------------------------------------
                 SCREEN 3: Subtitles Setup Menu
                 ----------------------------------------------- */}
              {dvdScreen === 'setup' && (
                <div className="dvd-body">
                  <div className="dvd-setup-options">
                    <div style={{textAlign: 'center'}}>
                      <button 
                        className={`dvd-btn ${activeBtnIdx === 0 ? 'highlighted' : ''} ${subtitlesEnabled ? 'selected' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(0)}
                        onClick={() => handleBtnClick(0)}
                      >
                        Subtitles On
                      </button>
                      {subtitlesEnabled && <div className="dvd-setup-indicator">Active</div>}
                    </div>

                    <div style={{textAlign: 'center'}}>
                      <button 
                        className={`dvd-btn ${activeBtnIdx === 1 ? 'highlighted' : ''} ${!subtitlesEnabled ? 'selected' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(1)}
                        onClick={() => handleBtnClick(1)}
                      >
                        Subtitles Off
                      </button>
                      {!subtitlesEnabled && <div className="dvd-setup-indicator">Active</div>}
                    </div>
                  </div>

                  <div className="dvd-nav-bottom">
                    <button 
                      className={`dvd-btn ${activeBtnIdx === 2 ? 'highlighted' : ''}`}
                      onMouseEnter={() => setActiveBtnIdx(2)}
                      onClick={() => handleBtnClick(2)}
                    >
                      Back to Main
                    </button>
                  </div>
                </div>
              )}

              {/* -----------------------------------------------
                 SCREEN 4: Cast & Crew Page
                 ----------------------------------------------- */}
              {dvdScreen === 'cast' && (
                <div className="dvd-body">
                  <div className="dvd-cast-layout">
                    {/* Left Column: Summary and Crew */}
                    <div className="dvd-show-summary-col">
                      <div className="dvd-section-label">Show Summary</div>
                      <div className="dvd-summary-text">
                        {selectedShow.overview || showDetails?.Overview || "No show summary available."}
                      </div>

                      <div className="dvd-crew-details">
                        {/* Directors list */}
                        {showDetails?.People?.some(p => p.Type === 'Director') && (
                          <div className="dvd-crew-item">
                            <span className="dvd-crew-label">Directed By: </span>
                            {showDetails.People.filter(p => p.Type === 'Director').slice(0, 3).map(p => p.Name).join(', ')}
                          </div>
                        )}
                        {/* Writers list */}
                        {showDetails?.People?.some(p => p.Type === 'Writer') && (
                          <div className="dvd-crew-item">
                            <span className="dvd-crew-label">Written By: </span>
                            {showDetails.People.filter(p => p.Type === 'Writer').slice(0, 3).map(p => p.Name).join(', ')}
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Right Column: Starring Actors Grid (Page 6 max) */}
                    <div className="dvd-cast-grid-col">
                      {showDetails?.People?.filter(p => p.Type === 'Actor')
                        .slice(castPageIndex * 6, (castPageIndex + 1) * 6)
                        .map((actor, idx) => {
                          const initials = actor.Name ? actor.Name.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() : '?';
                          const headshotUrl = Jellyfin.getImageUrl(connection.serverUrl, actor.Id, 'Primary', 100);

                          return (
                            <div className="dvd-actor-row" key={actor.Id || idx}>
                              {actor.Id ? (
                                <img 
                                  className="dvd-actor-headshot" 
                                  src={headshotUrl} 
                                  alt={actor.Name} 
                                  onError={(e) => {
                                    e.target.style.display = 'none';
                                    e.target.nextSibling.style.display = 'flex'; 
                                  }}
                                />
                              ) : null}
                              <div className="dvd-actor-headshot" style={{display: 'none'}}>{initials}</div>
                              <div className="dvd-actor-meta">
                                <div className="dvd-actor-name">{actor.Name}</div>
                                <div className="dvd-actor-role">{actor.Role ? `as ${actor.Role}` : ''}</div>
                              </div>
                            </div>
                          );
                        })}
                    </div>
                  </div>

                  {/* Nav Bar */}
                  <div className="dvd-nav-bottom">
                    {getScreenButtons().map((label, idx) => (
                      <button 
                        key={label}
                        className={`dvd-btn ${activeBtnIdx === idx ? 'highlighted' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(idx)}
                        onClick={() => handleBtnClick(idx)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* -----------------------------------------------
                 SCREEN 5: Trivia Challenge
                 ----------------------------------------------- */}
              {dvdScreen === 'trivia' && (
                <div className="dvd-body" style={{ justifyContent: 'flex-start', paddingTop: '15px' }}>
                  {triviaQuestions.length > 0 && (
                    <>
                      <div className="dvd-trivia-q-box">
                        <p className="dvd-trivia-q-text">
                          {triviaQuestions[triviaIndex].question}
                        </p>
                      </div>
                      
                      <div className="dvd-trivia-grid">
                        {triviaQuestions[triviaIndex].options.map((opt, i) => {
                          const letters = ["A", "B", "C", "D"];
                          return (
                            <button
                              key={i}
                              className={`dvd-trivia-option ${activeBtnIdx === i ? 'highlighted' : ''}`}
                              onMouseEnter={() => setActiveBtnIdx(i)}
                              onClick={() => handleBtnClick(i)}
                            >
                              {letters[i]}. {opt}
                            </button>
                          );
                        })}
                      </div>

                      <div className="dvd-trivia-exit-container">
                        <button
                          className={`dvd-btn ${activeBtnIdx === 4 ? 'highlighted' : ''}`}
                          onMouseEnter={() => setActiveBtnIdx(4)}
                          onClick={() => handleBtnClick(4)}
                        >
                          Exit Game
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}

              {/* SCREEN 6: Trivia Wrong Screen */}
              {dvdScreen === 'trivia_wrong' && (
                <div className="dvd-body">
                  <div className="dvd-trivia-status-title wrong">WRONG ANSWER!</div>
                  <div className="dvd-trivia-status-sub">Select an option below to continue.</div>
                  <div className="dvd-buttons-vertical">
                    {getScreenButtons().map((label, idx) => (
                      <button 
                        key={label}
                        className={`dvd-btn ${activeBtnIdx === idx ? 'highlighted' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(idx)}
                        onClick={() => handleBtnClick(idx)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* SCREEN 7: Trivia Win Screen */}
              {dvdScreen === 'trivia_win' && (
                <div className="dvd-body">
                  <div className="dvd-trivia-status-title win">CONGRATULATIONS!</div>
                  <div className="dvd-trivia-status-sub">You answered all trivia questions correctly!</div>
                  <div className="dvd-buttons-vertical">
                    {getScreenButtons().map((label, idx) => (
                      <button 
                        key={label}
                        className={`dvd-btn ${activeBtnIdx === idx ? 'highlighted' : ''}`}
                        onMouseEnter={() => setActiveBtnIdx(idx)}
                        onClick={() => handleBtnClick(idx)}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>
      )}

      {/* ----------------------------------------------------
         Right Side: Tactile Retro DVD Remote Controller
         ---------------------------------------------------- */}
      {isDvdActive && (
        <div className="dvd-remote-control">
          <div className="remote-label">JellyDisk Remote</div>

          <div className="remote-grid">
            <button className="remote-btn red" onClick={exitDvd}>Power</button>
            <button className="remote-btn" onClick={goBackScreen}>Return</button>
            <button className="remote-btn gold" onClick={() => setIsMuted(!isMuted)}>Mute</button>
          </div>

          {/* Direct Navigation shortcuts */}
          <div className="remote-grid">
            <button className="remote-btn" onClick={() => { setDvdScreen('main'); setActiveBtnIdx(0); }}>Menu</button>
            <button className="remote-btn" onClick={() => { setDvdScreen('episodes'); setActiveBtnIdx(0); }}>Title</button>
            <button className="remote-btn" onClick={() => { setDvdScreen('setup'); setActiveBtnIdx(0); }}>Setup</button>
          </div>

          {/* D-Pad Buttons */}
          <div className="remote-dpad">
            <button className="dpad-btn dpad-up" onClick={() => moveSelection('UP')}>▲</button>
            <button className="dpad-btn dpad-down" onClick={() => moveSelection('DOWN')}>▼</button>
            <button className="dpad-btn dpad-left" onClick={() => moveSelection('LEFT')}>◀</button>
            <button className="dpad-btn dpad-right" onClick={() => moveSelection('RIGHT')}>▶</button>
            <button className="dpad-btn dpad-enter" onClick={triggerButton}>ENTER</button>
          </div>

          <div className="remote-grid">
            <button className="remote-btn" onClick={() => setSubtitlesEnabled(!subtitlesEnabled)}>Subtitle</button>
            <button className="remote-btn" onClick={() => {
              if (playingVideoUrl && videoRef.current) {
                videoRef.current.paused ? videoRef.current.play() : videoRef.current.pause();
              }
            }}>Play/Pause</button>
            <button className="remote-btn" onClick={() => { stopVideo(); setPlayingTrailerUrl(null); }}>Stop</button>
          </div>

          <div className="remote-grid" style={{ width: '100%' }}>
            <button className="remote-btn" style={{ gridColumn: 'span 3', padding: '8px' }} onClick={toggleFullscreen}>
              🖥️ Fullscreen
            </button>
          </div>

          {/* Display & Styling Control Panel */}
          <div className="remote-options">
            <div className="toggle-row">
              <span>CRT TV Bulge</span>
              <label className="switch">
                <input type="checkbox" checked={crtFilter} onChange={() => setCrtFilter(!crtFilter)} />
                <span className="slider"></span>
              </label>
            </div>
            <div className="toggle-row">
              <span>Scanlines</span>
              <label className="switch">
                <input type="checkbox" checked={scanlines} onChange={() => setScanlines(!scanlines)} />
                <span className="slider"></span>
              </label>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default App;
