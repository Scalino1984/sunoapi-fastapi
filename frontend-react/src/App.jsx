import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ArrowLeft, ArrowUp, BookOpenText, Brush, ChevronDown, CircleHelp, ClipboardCheck, Command, FileText, Home, ListMusic, Menu, Mic2, Moon, MoreHorizontal, Music, RefreshCw, Scissors, Search, Settings, Shield, Sun, Trash, Trash2, UploadCloud, X } from 'lucide-react';
import { api } from './api/client.js';
import { assetSearchText, friendlyNotification } from './utils.js';
import { Login } from './components/Login.jsx';
import { MiniPlayer } from './components/MiniPlayer.jsx';
import { Toast } from './components/Toast.jsx';
import { StatusDetailModal } from './components/StatusDetailModal.jsx';
import { Modal } from './components/Modal.jsx';
import { ProfileMenu } from './components/ProfileMenu.jsx';
import { HomePage } from './pages/HomePage.jsx';
import { LibraryPage } from './pages/LibraryPage.jsx';
import { MusicPage } from './pages/MusicPage.jsx';
import { LyricsStudioPage } from './pages/LyricsStudioPage.jsx';
import { HelpPage } from './pages/HelpPage.jsx';
import { LibraryTextPage } from './pages/LibraryTextPage.jsx';
import { PlaylistsPage } from './pages/PlaylistsPage.jsx';
import { StylesPage } from './pages/StylesPage.jsx';
import { AdminPage } from './pages/AdminPage.jsx';
import { AuditPage } from './pages/AuditPage.jsx';
import { SystemPage } from './pages/SystemPage.jsx';
import { StatusPage } from './pages/StatusPage.jsx';
import { DawPage } from './pages/DawPage.jsx';
import { TrashPage } from './pages/TrashPage.jsx';
import { ImportPage } from './pages/ImportPage.jsx';
import { GlobalAIAssistant } from './components/GlobalAIAssistant.jsx';
import { AppAssistantProvider } from './context/AppAssistantContext.jsx';
import { buildAvailableAssistantActions, createAssistantActions } from './assistant/assistantActions.js';
import { useI18n } from './i18n/I18nContext.jsx';

const tabs = [
  ['home', 'Home', Home],
  ['library', 'Library', ListMusic],
  ['imports', 'Import', UploadCloud],
  ['music', 'Musik', Music],
  ['lyrics', 'Studio', Mic2],
  ['texts', 'Songtexte', FileText],
  ['playlists', 'Playlists', BookOpenText],
  ['trash', 'Papierkorb', Trash2],
  ['styles', 'Styles', Brush],
  ['daw', 'Mini-DAW', Scissors],
  ['admin', 'Admin', Shield],
  ['audit', 'Audit & Wartung', ClipboardCheck],
  ['status', 'Status', RefreshCw],
  ['system', 'System', Settings],
  ['help', 'Hilfe', BookOpenText]
];


const tabByKey = Object.fromEntries(tabs.map((tab) => [tab[0], tab]));

const tabLabels = Object.fromEntries(tabs.map(([key, label]) => [key, label]));

const tabKeys = new Set(tabs.map(([key]) => key));

function readStoredActiveTab() {
  try {
    const stored = localStorage.getItem('react-active-tab');
    return tabKeys.has(stored) ? stored : 'home';
  } catch {
    return 'home';
  }
}

function reactRouteBase(pathname = '') {
  return pathname === '/react' || pathname.startsWith('/react/') ? '/react' : '';
}

function tabFromPathname(pathname = '') {
  const cleanPath = String(pathname || '/').replace(/\/+$/, '') || '/';
  const withoutReactBase = cleanPath === '/react' ? '/' : cleanPath.replace(/^\/react(?=\/)/, '');
  const firstPart = withoutReactBase.split('/').filter(Boolean)[0] || 'home';
  return tabKeys.has(firstPart) ? firstPart : null;
}

function routeTitleSegment(value) {
  const clean = String(value || '')
    .trim()
    .replace(/[\/\?#]+/g, ' ')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '');
  return clean ? encodeURIComponent(clean).slice(0, 96) : '';
}

function routeDetailSegment(pathname = '', tabKey = 'library') {
  const cleanPath = String(pathname || '/').replace(/\/+$/, '') || '/';
  const withoutReactBase = cleanPath === '/react' ? '/' : cleanPath.replace(/^\/react(?=\/)/, '');
  const parts = withoutReactBase.split('/').filter(Boolean);
  if (parts[0] !== tabKey || parts.length < 2) return '';
  return parts.slice(1).join('/');
}

function decodeRouteDetailSegment(value = '') {
  try {
    return decodeURIComponent(String(value || ''));
  } catch {
    return String(value || '');
  }
}

function tabPath(key, pathname = '', detailTitle = '') {
  const safeKey = tabKeys.has(key) ? key : 'home';
  const base = reactRouteBase(pathname || (typeof window !== 'undefined' ? window.location.pathname : ''));
  if (safeKey === 'home') return base || '/';
  const rootPath = `${base}/${safeKey}`;
  const detailPart = safeKey === 'library' ? routeTitleSegment(detailTitle) : '';
  return detailPart ? `${rootPath}/${detailPart}` : rootPath;
}

function dawAssetIdFromLocation() {
  if (typeof window === 'undefined') return '';
  try {
    const params = new URLSearchParams(window.location.search || '');
    return String(params.get('asset_id') || params.get('audio_asset_id') || '').trim();
  } catch {
    return '';
  }
}

function dawPath(assetId = '', pathname = '') {
  const base = reactRouteBase(pathname || (typeof window !== 'undefined' ? window.location.pathname : ''));
  const normalized = String(assetId || '').trim();
  return normalized ? `${base}/daw?asset_id=${encodeURIComponent(normalized)}` : `${base}/daw`;
}

function initialDawAssetId() {
  if (typeof window === 'undefined') return '';
  return tabFromPathname(window.location.pathname) === 'daw' ? dawAssetIdFromLocation() : '';
}

function initialActiveTab() {
  if (typeof window === 'undefined') return readStoredActiveTab();
  return tabFromPathname(window.location.pathname) || readStoredActiveTab();
}
const ACTIVE_TASK_STATUSES = new Set(['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS', 'submitted', 'processing']);
const TERMINAL_SUCCESS_STATUSES = new Set(['SUCCESS', 'COMPLETED', 'COMPLETE', 'DONE', 'IMPORTED', 'PARTIAL_SUCCESS']);

const POLLING_AFTER_CREATE_MS = 20 * 60 * 1000;
const ACTIVE_POLL_INTERVAL_MS = 10 * 1000;
const IDLE_POLL_INTERVAL_MS = 60 * 1000;
const MIN_STATUS_POLL_INTERVAL_MS = 8 * 1000;
const STATUS_DETAIL_POLL_MS = 2500;
const AUTH_KEEPALIVE_INTERVAL_MS = 10 * 60 * 1000;
const DEFAULT_BADGE_AUTO_CLOSE_MS = 8000;
const DEFAULT_BADGE_AUTO_CLOSE_ENABLED = true;
const THEME_STORAGE_KEY = 'react-ui-theme';
const NOTIFICATION_SEEN_STORAGE_KEY = 'seen-react-notification-ids';
const NOTIFICATION_SEEN_MAX = 3000;
const NOTIFICATION_STARTUP_GRACE_MS = 5000;

const SIDEBAR_STORAGE_KEY = 'react-sidebar-mode';
const WORKSPACE_FOCUS_STORAGE_KEY = 'react-workspace-focus';

const directSidebarKeys = ['home', 'library', 'music', 'lyrics', 'imports', 'status'];

function getInitialSidebarMode() {
  try {
    const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
    if (['open', 'compact', 'closed'].includes(stored)) return stored;
  } catch {
    return 'open';
  }
  return 'open';
}

function getInitialWorkspaceFocus() {
  try {
    return localStorage.getItem(WORKSPACE_FOCUS_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

function getInitialTheme() {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    return 'dark';
  }
  return 'dark';
}



function readSeenNotificationIds() {
  try {
    const parsed = JSON.parse(localStorage.getItem(NOTIFICATION_SEEN_STORAGE_KEY) || '[]');
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.map((item) => String(item)).filter(Boolean));
  } catch {
    return new Set();
  }
}

function persistSeenNotificationIds(ids) {
  try {
    const values = [...ids].filter(Boolean).slice(-NOTIFICATION_SEEN_MAX);
    localStorage.setItem(NOTIFICATION_SEEN_STORAGE_KEY, JSON.stringify(values));
  } catch {
    // localStorage kann blockiert sein; die Session-Sperre bleibt trotzdem aktiv.
  }
}

function notificationCreatedAtMs(notification) {
  const raw = notification?.created_at || notification?.updated_at || notification?.completed_at || '';
  const parsed = Date.parse(raw);
  return Number.isFinite(parsed) ? parsed : 0;
}

function notificationSortValue(notification) {
  const created = notificationCreatedAtMs(notification);
  const id = Number(notification?.id || 0);
  return created * 100000 + (Number.isFinite(id) ? id : 0);
}

function normalizeApiList(value, preferredKeys = []) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== 'object') return [];

  for (const key of preferredKeys) {
    if (Array.isArray(value[key])) return value[key];
  }

  const commonKeys = ['items', 'results', 'data', 'records', 'rows', 'assets', 'lyrics', 'styles', 'playlists', 'tasks', 'notifications', 'songs'];
  for (const key of commonKeys) {
    if (Array.isArray(value[key])) return value[key];
  }

  return [];
}

function listCount(value) {
  return normalizeApiList(value).length;
}

function isActiveTask(task) {
  const status = String(task?.status || '').trim();
  return ACTIVE_TASK_STATUSES.has(status) || ACTIVE_TASK_STATUSES.has(status.toUpperCase());
}

function isTerminalSuccessStatus(status) {
  return TERMINAL_SUCCESS_STATUSES.has(String(status || '').trim().toUpperCase());
}

function activeTaskCount(value) {
  return normalizeApiList(value, ['tasks', 'items']).filter(isActiveTask).length;
}

function describeRefreshPayload(payload) {
  if (!payload || typeof payload !== 'object') return '';
  const candidates = [payload.message, payload.msg, payload.detail, payload.status];
  const direct = candidates.find((item) => typeof item === 'string' && item.trim());
  if (direct) return direct;
  const refreshed = payload.refreshed ?? payload.updated ?? payload.changed;
  if (Number.isFinite(Number(refreshed))) return `${refreshed} aktualisiert`;
  return '';
}

export default function App() {
  const { language, setLanguage, t } = useI18n();
  const [user, setUser] = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const routePopStateRef = useRef(false);
  const [activeTab, setActiveTab] = useState(initialActiveTab);
  const [assets, setAssets] = useState([]);
  const [libraryLoadError, setLibraryLoadError] = useState('');
  const [lyrics, setLyrics] = useState([]);
  const [styles, setStyles] = useState([]);
  const [voices, setVoices] = useState([]);
  const [uploadedFiles, setUploadedFiles] = useState([]);
  const [playlists, setPlaylists] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [credits, setCredits] = useState(null);
  const [toast, setToast] = useState(null);
  const [queue, setQueue] = useState([]);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [loop, setLoop] = useState(false);
  const [playerState, setPlayerState] = useState({ currentAssetId: null, isPlaying: false, currentTime: 0, duration: 0 });
  const [playerCommand, setPlayerCommand] = useState({ seq: 0, action: '' });
  const [lastPlayedAsset, setLastPlayedAsset] = useState(null);
  const [musicDraft, setMusicDraft] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [notifications, setNotifications] = useState([]);
  const [libraryOpenAssetId, setLibraryOpenAssetId] = useState(null);
  const [libraryOpenRequestKey, setLibraryOpenRequestKey] = useState(0);
  const [routePathname, setRoutePathname] = useState(() => (typeof window !== 'undefined' ? window.location.pathname : '/'));
  const [libraryRouteTitle, setLibraryRouteTitle] = useState(() => decodeRouteDetailSegment(routeDetailSegment(typeof window !== 'undefined' ? window.location.pathname : '', 'library')));
  const [dawOpenAssetId, setDawOpenAssetId] = useState(initialDawAssetId);
  const [libraryResetSignal, setLibraryResetSignal] = useState(0);
  const [musicWizardSignal, setMusicWizardSignal] = useState(false);
  const [pollingUntil, setPollingUntil] = useState(0);
  const [taskRefreshState, setTaskRefreshState] = useState({ running: false, lastCheck: null, lastMessage: '', lastError: '', activeCount: 0 });
  const [runtimeConfig, setRuntimeConfig] = useState(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [openNavGroup, setOpenNavGroup] = useState(null);
  const [statusDetail, setStatusDetail] = useState({ open: false, notification: null, task: null, loadingTask: false });
  const [modalTaskRefreshRunning, setModalTaskRefreshRunning] = useState(false);
  const [modalTaskCancelRunning, setModalTaskCancelRunning] = useState(false);
  const [theme, setTheme] = useState(getInitialTheme);
  const [sidebarMode, setSidebarMode] = useState(getInitialSidebarMode);
  const [workspaceFocus, setWorkspaceFocus] = useState(getInitialWorkspaceFocus);
  const [commandQuery, setCommandQuery] = useState('');
  const [mobileSearchOpen, setMobileSearchOpen] = useState(false);
  const [topbarMenuOpen, setTopbarMenuOpen] = useState(false);
  const [helpModalOpen, setHelpModalOpen] = useState(false);
  const [trashHasItems, setTrashHasItems] = useState(false);
  const [showMobileScrollTop, setShowMobileScrollTop] = useState(false);
  const showMobileScrollTopRef = useRef(false);
  const playbackRefreshLockRef = useRef(false);
  // Content-Refreshes waehrend aktiver Audiowiedergabe werden gesammelt und
  // erst nach Pause/Stop ausgefuehrt. So bleiben Markierungen, Dropdowns und
  // Scrollpositionen stabil, waehrend Tasks/Notifications weiter gepollt werden.
  const pendingContentRefreshRef = useRef(false);
  const cachedRefreshStateRef = useRef({ assets: [], tasks: [], notifications: [] });
  const lastPlaybackCommitRef = useRef({ currentAssetId: null, isPlaying: false, currentTime: 0, duration: 0, committedAt: 0 });
  const notificationSessionStartedAtRef = useRef(Date.now());
  const notificationBootstrapDoneRef = useRef(false);
  const seenNotificationIdsRef = useRef(readSeenNotificationIds());
  const successContentRefreshNotificationIdsRef = useRef(new Set());
  const successContentRefreshTaskIdsRef = useRef(new Set());
  const tasksRef = useRef([]);
  const pollingUntilRef = useRef(0);
  const lastStatusPollAtRef = useRef(0);

  useEffect(() => {
    tasksRef.current = tasks;
  }, [tasks]);

  useEffect(() => {
    pollingUntilRef.current = pollingUntil;
  }, [pollingUntil]);

  useEffect(() => {
    const safeTheme = theme === 'light' ? 'light' : 'dark';
    document.documentElement.dataset.theme = safeTheme;
    document.body.dataset.theme = safeTheme;
    document.documentElement.style.colorScheme = safeTheme;
    try {
      localStorage.setItem(THEME_STORAGE_KEY, safeTheme);
    } catch {
      // localStorage kann in privaten Browsermodi blockiert sein.
    }
  }, [theme]);

  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, sidebarMode);
    } catch {
      // localStorage kann in privaten Browsermodi blockiert sein.
    }
  }, [sidebarMode]);

  useEffect(() => {
    try {
      localStorage.setItem(WORKSPACE_FOCUS_STORAGE_KEY, String(workspaceFocus));
    } catch {
      // localStorage kann in privaten Browsermodi blockiert sein.
    }
  }, [workspaceFocus]);

  useEffect(() => {
    const shouldLock = Boolean(mobileNavOpen || topbarMenuOpen);
    document.body.classList.toggle('mobile-ui-lock', shouldLock);
    return () => document.body.classList.remove('mobile-ui-lock');
  }, [mobileNavOpen, topbarMenuOpen]);

  useEffect(() => {
    setTopbarMenuOpen(false);
    setMobileSearchOpen(false);
  }, [activeTab]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    let ticking = false;
    const updateScrollTopButton = () => {
      ticking = false;
      const nextVisible = window.scrollY > 240;
      if (showMobileScrollTopRef.current === nextVisible) return;
      showMobileScrollTopRef.current = nextVisible;
      setShowMobileScrollTop(nextVisible);
    };
    const requestUpdate = () => {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(updateScrollTopButton);
    };
    updateScrollTopButton();
    window.addEventListener('scroll', requestUpdate, { passive: true });
    window.addEventListener('resize', requestUpdate);
    return () => {
      window.removeEventListener('scroll', requestUpdate);
      window.removeEventListener('resize', requestUpdate);
    };
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((current) => current === 'light' ? 'dark' : 'light');
  }, []);

  const scrollToPageTop = useCallback(() => {
    setTopbarMenuOpen(false);
    setMobileSearchOpen(false);
    if (typeof window === 'undefined') return;
    document.querySelector('.studio-main-content')?.scrollTo?.({ top: 0, behavior: 'smooth' });
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, []);

  const notify = useCallback((message, type = 'info') => setToast({ message, type }), []);

  useEffect(() => {
    playbackRefreshLockRef.current = Boolean(playerState?.isPlaying);
    cachedRefreshStateRef.current = {
      ...cachedRefreshStateRef.current,
      assets,
      tasks,
      notifications,
    };
    document.body.classList.toggle('audio-playback-active', Boolean(playerState?.isPlaying));
    return () => document.body.classList.remove('audio-playback-active');
  }, [assets, tasks, notifications, playerState?.isPlaying]);

  const handlePlaybackStateChange = useCallback((nextState = {}) => {
    const normalized = {
      currentAssetId: nextState.currentAssetId || null,
      isPlaying: Boolean(nextState.isPlaying),
      currentTime: Number(nextState.currentTime || 0),
      duration: Number(nextState.duration || 0),
    };
    const previous = lastPlaybackCommitRef.current || {};
    const identityChanged = String(previous.currentAssetId || '') !== String(normalized.currentAssetId || '')
      || Boolean(previous.isPlaying) !== normalized.isPlaying
      || Math.abs(Number(previous.duration || 0) - normalized.duration) >= 0.5;

    // Der MiniPlayer meldet currentTime sehr häufig. Reine Zeit-Ticks dürfen nicht die
    // komplette App neu rendern, weil dadurch Library-Menüs, Scrollbereiche und Buttons
    // während der Wiedergabe remounten oder springen können.
    lastPlaybackCommitRef.current = { ...normalized, committedAt: Date.now() };
    playbackRefreshLockRef.current = Boolean(normalized.isPlaying);

    if (!identityChanged && normalized.isPlaying) return;

    setPlayerState((current) => {
      const stateIdentityChanged = String(current.currentAssetId || '') !== String(normalized.currentAssetId || '')
        || Boolean(current.isPlaying) !== normalized.isPlaying
        || Math.abs(Number(current.duration || 0) - normalized.duration) >= 0.5;
      const shouldCommitPausedTime = !normalized.isPlaying
        && Math.abs(Number(current.currentTime || 0) - normalized.currentTime) >= 0.5;
      if (!stateIdentityChanged && !shouldCommitPausedTime) return current;
      return normalized;
    });
  }, []);

  useEffect(() => {
    const activeId = String(playerState.currentAssetId || '').trim();
    if (!activeId) return;
    const queueAsset = (queue || []).find((asset) => String(asset?.id || '') === activeId);
    const freshAsset = (assets || []).find((asset) => String(asset?.id || '') === activeId);
    const nextAsset = freshAsset || queueAsset;
    if (!nextAsset?.id) return;
    setLastPlayedAsset((current) => {
      if (
        String(current?.id || '') === String(nextAsset.id)
        && String(current?.updated_at || '') === String(nextAsset.updated_at || '')
        && String(current?.status || '') === String(nextAsset.status || '')
      ) {
        return current;
      }
      return nextAsset;
    });
  }, [assets, queue, playerState.currentAssetId]);

  const notificationDisplayConfig = runtimeConfig?.notifications || {};
  const toastAutoCloseMs = useMemo(() => {
    const enabled = notificationDisplayConfig.badge_auto_close_enabled ?? DEFAULT_BADGE_AUTO_CLOSE_ENABLED;
    if (!enabled) return 0;
    const configuredMs = Number(notificationDisplayConfig.badge_auto_close_ms || 0);
    if (Number.isFinite(configuredMs) && configuredMs > 0) return configuredMs;
    const configuredSeconds = Number(notificationDisplayConfig.badge_auto_close_seconds || 0);
    if (Number.isFinite(configuredSeconds) && configuredSeconds > 0) return configuredSeconds * 1000;
    return DEFAULT_BADGE_AUTO_CLOSE_MS;
  }, [notificationDisplayConfig.badge_auto_close_enabled, notificationDisplayConfig.badge_auto_close_ms, notificationDisplayConfig.badge_auto_close_seconds]);
  const toastAutoMarkDone = Boolean(notificationDisplayConfig.badge_auto_mark_done);

  useEffect(() => {
    api.auth.me()
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthChecked(true));
  }, []);


  useEffect(() => {
    if (!user) {
      setRuntimeConfig(null);
      return;
    }

    api.runtimeConfig()
      .then(setRuntimeConfig)
      .catch(() => setRuntimeConfig(null));
  }, [user]);

  useEffect(() => {
    localStorage.setItem('react-active-tab', activeTab);
    setMobileNavOpen(false);
    setOpenNavGroup(null);
    if (typeof window !== 'undefined') {
      const targetPath = activeTab === 'daw'
        ? dawPath(dawOpenAssetId || dawAssetIdFromLocation(), window.location.pathname)
        : tabPath(activeTab, window.location.pathname, activeTab === 'library' ? libraryRouteTitle : '');
      const currentPath = `${window.location.pathname.replace(/\/+$/, '') || '/'}${window.location.search || ''}`;
      const normalizedTarget = targetPath;
      if (currentPath !== normalizedTarget) {
        if (routePopStateRef.current) {
          routePopStateRef.current = false;
        } else {
          window.history.pushState({ activeTab }, '', targetPath);
          setRoutePathname(window.location.pathname);
        }
      } else {
        routePopStateRef.current = false;
      }
    }
  }, [activeTab, libraryRouteTitle, dawOpenAssetId]);

  useEffect(() => {
    if (activeTab !== 'library' && libraryRouteTitle) {
      setLibraryRouteTitle('');
    }
  }, [activeTab, libraryRouteTitle]);

  useEffect(() => {
    if (typeof window === 'undefined') return undefined;
    const handlePopState = () => {
      const nextTab = tabFromPathname(window.location.pathname) || readStoredActiveTab();
      routePopStateRef.current = true;
      setRoutePathname(window.location.pathname);
      if (nextTab === 'library') {
        setLibraryRouteTitle(decodeRouteDetailSegment(routeDetailSegment(window.location.pathname, 'library')));
      } else if (nextTab === 'daw') {
        setDawOpenAssetId(dawAssetIdFromLocation());
      }
      setActiveTab(nextTab);
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);
  useEffect(() => {
    if (!user) return undefined;

    let stopped = false;

    const keepAlive = async () => {
      try {
        await api.auth.refresh();
      } catch (err) {
        if (!stopped && err?.status === 401) {
          setUser(null);
          notify('Deine Anmeldung ist abgelaufen. Bitte neu anmelden.', 'error');
        }
      }
    };

    const intervalId = window.setInterval(keepAlive, AUTH_KEEPALIVE_INTERVAL_MS);

    const onVisible = () => {
      if (document.visibilityState === 'visible') keepAlive();
    };

    document.addEventListener('visibilitychange', onVisible);

    return () => {
      stopped = true;
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [user, notify]);


  const refreshAll = useCallback(async (options = {}) => {
    const {
      silent = false,
      forceContentRefresh = false,
      deferContentWhilePlaying = true,
      ignorePlaybackLock = false,
      content = true,
      tasks: fetchTasks = true,
      credits: fetchCredits = true,
      notifications: fetchNotifications = true
    } = options;
    const contentLocked = Boolean(content) && deferContentWhilePlaying && playbackRefreshLockRef.current && !ignorePlaybackLock;
    if (contentLocked && forceContentRefresh) pendingContentRefreshRef.current = true;
    const shouldFetchContent = Boolean(content) && !contentLocked;
    const shouldFetchTasks = Boolean(fetchTasks);
    const shouldFetchCredits = Boolean(fetchCredits);
    const shouldFetchNotifications = Boolean(fetchNotifications);
    if (!silent) setRefreshing(true);

    try {
      const skippedContent = Promise.resolve({ __skipped: true });
      const results = await Promise.allSettled([
        shouldFetchContent ? api.archive.audio() : skippedContent,
        shouldFetchContent ? api.library.lyrics() : skippedContent,
        shouldFetchContent ? api.library.styles() : skippedContent,
        shouldFetchContent ? api.music.voices() : skippedContent,
        shouldFetchContent ? api.files.list() : skippedContent,
        shouldFetchContent ? api.library.playlists() : skippedContent,
        shouldFetchTasks ? api.music.tasks() : skippedContent,
        shouldFetchCredits ? api.credits() : skippedContent,
        shouldFetchNotifications ? api.notifications.list(true) : skippedContent,
        shouldFetchContent && api.music.songs ? api.music.songs() : skippedContent
      ]);

      let nextAssets = cachedRefreshStateRef.current.assets || [];
      let nextTasks = cachedRefreshStateRef.current.tasks || [];
      let nextNotifications = cachedRefreshStateRef.current.notifications || [];

      if (shouldFetchContent && results[0].status === 'fulfilled') {
        nextAssets = normalizeApiList(results[0].value, ['assets', 'audio_assets', 'items']);
        cachedRefreshStateRef.current = { ...cachedRefreshStateRef.current, assets: nextAssets };
        setAssets(nextAssets);
        setLibraryLoadError('');
      } else if (shouldFetchContent && results[0].status === 'rejected') {
        const message = results[0].reason?.message || 'Library konnte nicht geladen werden.';
        setLibraryLoadError(message);
      }
      if (shouldFetchContent && results[1].status === 'fulfilled') setLyrics(normalizeApiList(results[1].value, ['lyrics', 'items']));
      if (shouldFetchContent && results[2].status === 'fulfilled') setStyles(normalizeApiList(results[2].value, ['styles', 'items']));
      if (shouldFetchContent && results[3].status === 'fulfilled') setVoices(normalizeApiList(results[3].value, ['voices', 'items']));
      if (shouldFetchContent && results[4].status === 'fulfilled') setUploadedFiles(normalizeApiList(results[4].value, ['files', 'items', 'data']));
      if (shouldFetchContent && results[5].status === 'fulfilled') setPlaylists(normalizeApiList(results[5].value, ['playlists', 'items']));
      if (shouldFetchTasks && results[6].status === 'fulfilled') {
        nextTasks = normalizeApiList(results[6].value, ['tasks', 'items']);
        cachedRefreshStateRef.current = { ...cachedRefreshStateRef.current, tasks: nextTasks };
        setTasks(nextTasks);
      }
      if (shouldFetchCredits && results[7].status === 'fulfilled') setCredits(results[7].value?.data ?? results[7].value?.credits ?? null);
      if (shouldFetchNotifications && results[8].status === 'fulfilled') {
        nextNotifications = normalizeApiList(results[8].value, ['notifications', 'items']);
        cachedRefreshStateRef.current = { ...cachedRefreshStateRef.current, notifications: nextNotifications };
        setNotifications(nextNotifications);
      }

      return { assets: nextAssets, tasks: nextTasks, notifications: nextNotifications, results, contentSkipped: contentLocked };
    } finally {
      if (!silent) setRefreshing(false);
    }
  }, []);


  useEffect(() => {
    if (!user || playerState.isPlaying || !pendingContentRefreshRef.current) return;
    pendingContentRefreshRef.current = false;
    refreshAll({ silent: true, forceContentRefresh: true, deferContentWhilePlaying: false, ignorePlaybackLock: true }).catch(() => null);
  }, [user, playerState.isPlaying, refreshAll]);

  const refreshTrashIndicator = useCallback(async () => {
    try {
      const rows = await api.library.trash({ q: '', contentType: 'all', limit: 1 });
      setTrashHasItems(Array.isArray(rows) && rows.length > 0);
    } catch {
      setTrashHasItems(false);
    }
  }, []);

  const markTrashHasItems = useCallback(() => {
    setTrashHasItems(true);
  }, []);

  useEffect(() => {
    if (!user) {
      setTrashHasItems(false);
      return;
    }
    refreshTrashIndicator();
  }, [refreshTrashIndicator, user]);

  const handleFavoriteChange = useCallback((assetId, isFavorite) => {
    const id = String(assetId || '');
    if (!id) return;
    const updateRows = (rows = []) => (Array.isArray(rows) ? rows.map((asset) => String(asset?.id || '') === id ? { ...asset, is_favorite: Boolean(isFavorite) } : asset) : rows);
    setAssets((current) => {
      const next = updateRows(current);
      cachedRefreshStateRef.current = { ...cachedRefreshStateRef.current, assets: next };
      return next;
    });
    setQueue((current) => updateRows(current));
  }, []);

  useEffect(() => {
    function handleSrtUpdated(event) {
      const detail = event?.detail || {};
      const id = String(detail.audio_asset_id || detail.asset_id || detail.id || '');
      if (!id) return;
      const transcript = detail.srt || detail.transcript || detail.result || {};
      const hasSrt = transcript.exists !== false && Boolean(transcript.srt_text || transcript.srt_url || transcript.srt_path || transcript.download_url || transcript.segments?.length);
      const hasHalfSrt = Boolean(transcript.half_srt_exists || transcript.half_srt_text || transcript.half_srt_url || transcript.half_download_url);
      const updateRows = (rows = []) => (Array.isArray(rows) ? rows.map((asset) => {
        if (String(asset?.id || '') !== id) return asset;
        return {
          ...asset,
          srt_cached: hasSrt || Boolean(asset.srt_cached),
          half_srt_cached: hasHalfSrt || Boolean(asset.half_srt_cached),
          latest_srt_status: transcript.status || asset.latest_srt_status || (hasSrt ? 'completed' : asset.latest_srt_status),
          latest_srt_generated_at: transcript.generated_at || asset.latest_srt_generated_at,
          updated_at: transcript.updated_at || asset.updated_at,
        };
      }) : rows);

      setAssets((current) => {
        const next = updateRows(current);
        cachedRefreshStateRef.current = { ...cachedRefreshStateRef.current, assets: next };
        return next;
      });
      setQueue((current) => updateRows(current));

      const status = String(transcript.status || detail.status || '').toLowerCase();
      const hasTaskHandle = Boolean(transcript.task_local_id || transcript.task_id || detail.task_local_id || detail.task_id);
      const shouldRefreshTasks = hasTaskHandle || ['running', 'queued', 'pending', 'processing'].includes(status);

      if (shouldRefreshTasks) {
        // SRT-Erzeugungen koennen auch ausserhalb der Library-Detailseite
        // gestartet werden, z. B. im MiniPlayer. Dort gibt es kein onReload(),
        // deshalb muss die globale Task-/Notification-Leiste explizit nachziehen.
        setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS);
        const refreshTaskSnapshot = () => {
          refreshAll({
            silent: true,
            content: false,
            tasks: true,
            credits: false,
            notifications: true,
          })
            .then((snapshot) => {
              const count = activeTaskCount(snapshot?.tasks || []);
              setTaskRefreshState((current) => ({ ...current, activeCount: count }));
              if (count > 0) setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS);
            })
            .catch(() => null);
        };

        refreshTaskSnapshot();
        window.setTimeout(refreshTaskSnapshot, 800);
      }
    }

    window.addEventListener('srt:updated', handleSrtUpdated);
    return () => window.removeEventListener('srt:updated', handleSrtUpdated);
  }, [refreshAll]);

  // Wichtig: Keine assets/tasks/notifications in diese Dependencies aufnehmen.
  // Die Funktion pollt Live-Statuswerte. Wenn sie bei jeder Task-/Notification-
  // Aktualisierung neu erzeugt wird, startet der Polling-Effect sofort erneut
  // und triggert faktisch Dauer-Refreshes, die Textauswahl und Klicks stören.
  const refreshPendingAndReload = useCallback(async (options = {}) => {
    const { manual = false, silent = false, content = false, credits = manual } = options;
    if (!user) return null;

    const startedAt = new Date().toISOString();
    setTaskRefreshState((current) => ({ ...current, running: true, lastError: '' }));

    try {
      const refreshPayload = await api.music.refreshPending();
      const snapshot = await refreshAll({ silent: true, deferContentWhilePlaying: true, content, credits });
      const count = activeTaskCount(snapshot?.tasks || []);
      const message = describeRefreshPayload(refreshPayload) || (count ? `${count} Task(s) noch in Bearbeitung` : 'Keine offenen Tasks');

      setTaskRefreshState({
        running: false,
        lastCheck: startedAt,
        lastMessage: message,
        lastError: '',
        activeCount: count
      });

      if (count > 0) setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS);
      if (manual && !silent) notify(message, count ? 'info' : 'success');
      return { refreshPayload, snapshot, activeCount: count };
    } catch (err) {
      const message = err?.message || 'Statusprüfung fehlgeschlagen.';
      setTaskRefreshState((current) => ({
        ...current,
        running: false,
        lastCheck: startedAt,
        lastError: message
      }));
      if (manual && !silent) notify(message, 'error');
      return null;
    }
  }, [user, refreshAll, notify]);

  useEffect(() => {
    if (!user) return;
    let stopped = false;

    const boot = async () => {
      api.notifications.cleanupStale({ max_age_hours: 24, severities: ['info', 'success'] }).catch(() => null);
      if (stopped) return;
      const snapshot = await refreshAll();
      if (stopped) return;
      const count = activeTaskCount(snapshot?.tasks || []);
      setTaskRefreshState((current) => ({ ...current, activeCount: count }));
      if (count > 0) setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS);
    };

    boot().catch(() => null);

    return () => {
      stopped = true;
    };
  }, [user, refreshAll]);

  useEffect(() => {
    if (!user) return undefined;

    let stopped = false;
    let busy = false;
    let timerId = null;

    const tick = async () => {
      if (stopped || busy) return;
      // Während der Wiedergabe NICHT komplett pausieren: Task-Status und
      // Notifications müssen weiterlaufen, damit ein fertiger Song erkannt und
      // (via success-content-refresh) ohne F5 nachgeladen wird. Die schwere
      // Library-Abfrage bleibt über deferContentWhilePlaying in refreshAll
      // ausgespart, der Player (läuft über queue, nicht assets) bleibt unberührt.
      const now = Date.now();
      const openCount = activeTaskCount(tasksRef.current);
      const forceWindowActive = now < pollingUntilRef.current;
      const shouldPoll = openCount > 0 || forceWindowActive;

      if (!shouldPoll) return;
      if (now - lastStatusPollAtRef.current < MIN_STATUS_POLL_INTERVAL_MS) return;

      busy = true;
      lastStatusPollAtRef.current = now;
      try {
        await refreshPendingAndReload({ silent: true, credits: false });
      } finally {
        busy = false;
      }
    };

    const schedule = () => {
      const openCount = activeTaskCount(tasksRef.current);
      const forceWindowActive = Date.now() < pollingUntilRef.current;
      const delay = openCount > 0 || forceWindowActive ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
      timerId = window.setTimeout(async () => {
        await tick();
        if (!stopped) schedule();
      }, delay);
    };

    tick();
    schedule();

    return () => {
      stopped = true;
      if (timerId) window.clearTimeout(timerId);
    };
  }, [user, refreshPendingAndReload]);

  useEffect(() => {
    if (playbackRefreshLockRef.current) return;

    const rows = normalizeApiList(notifications, ['notifications', 'items']);
    if (!rows.length) return;

    const seen = seenNotificationIdsRef.current || readSeenNotificationIds();

    const minCreatedAt = notificationSessionStartedAtRef.current - NOTIFICATION_STARTUP_GRACE_MS;

    // Beim App-Start werden nur wirklich alte DB-Meldungen als gesehen markiert.
    // Meldungen, die nach Session-Start durch einen gerade gestarteten Job entstehen,
    // müssen weiterhin als Badge/Toast erscheinen.
    if (!notificationBootstrapDoneRef.current) {
      rows.forEach((item) => {
        if (item?.id == null) return;
        const createdAt = notificationCreatedAtMs(item);
        if (createdAt && createdAt < minCreatedAt) seen.add(String(item.id));
      });
      notificationBootstrapDoneRef.current = true;
      seenNotificationIdsRef.current = seen;
      persistSeenNotificationIds(seen);
    }

    const candidates = rows
      .filter((item) => item?.id != null)
      .filter((item) => String(item.status || 'unread') === 'unread')
      .filter((item) => !seen.has(String(item.id)))
      .filter((item) => {
        const createdAt = notificationCreatedAtMs(item);
        return createdAt === 0 || createdAt >= minCreatedAt;
      })
      .sort((a, b) => notificationSortValue(b) - notificationSortValue(a));

    if (!candidates.length) {
      seenNotificationIdsRef.current = seen;
      return;
    }

    // Pro Refresh-Zyklus nur die neueste echte Meldung toasten. Weitere neue Meldungen
    // bleiben in der Statusseite sichtbar, lösen aber keine alte Meldungsflut aus.
    const unread = candidates[0];
    seen.add(String(unread.id));
    seenNotificationIdsRef.current = seen;
    persistSeenNotificationIds(seen);

    const friendly = friendlyNotification(unread, t);
    setToast({ message: `${friendly.title}${friendly.message ? ' · ' + friendly.message : ''}`, type: unread.severity || 'info', notification: unread });
  }, [notifications, playerState.isPlaying]);

  useEffect(() => {
    if (!user) return;
    const notificationRows = normalizeApiList(notifications, ['notifications', 'items']);
    const taskRows = normalizeApiList(tasks, ['tasks', 'items']);
    let shouldRefreshContent = false;

    for (const item of notificationRows) {
      const notificationId = item?.id != null ? String(item.id) : '';
      if (!notificationId || successContentRefreshNotificationIdsRef.current.has(notificationId)) continue;
      const payload = item?.target_payload || {};
      const status = payload.status || item?.status_value || item?.result_status;
      const isSuccessNotification = String(item?.severity || '').toLowerCase() === 'success' || isTerminalSuccessStatus(status);
      if (!isSuccessNotification) continue;
      successContentRefreshNotificationIdsRef.current.add(notificationId);
      if (String(payload.task_type || '').toLowerCase() === 'generate_srt' && payload.audio_asset_id && typeof window !== 'undefined') {
        window.dispatchEvent(new CustomEvent('srt:updated', { detail: { audio_asset_id: payload.audio_asset_id } }));
      }
      shouldRefreshContent = true;
    }

    for (const task of taskRows) {
      const taskKey = task?.id != null ? String(task.id) : String(task?.task_id || '');
      if (!taskKey || successContentRefreshTaskIdsRef.current.has(taskKey)) continue;
      if (!isTerminalSuccessStatus(task?.status)) continue;
      successContentRefreshTaskIdsRef.current.add(taskKey);
      shouldRefreshContent = true;
    }

    if (!shouldRefreshContent) return;
    if (playbackRefreshLockRef.current) {
      pendingContentRefreshRef.current = true;
      return;
    }
    refreshAll({ silent: true, forceContentRefresh: true, deferContentWhilePlaying: true }).catch(() => null);
  }, [notifications, tasks, user, refreshAll]);

  async function logout() {
    await api.auth.logout();
    setUser(null);
    setPollingUntil(0);
    setTasks([]);
    setAssets([]);
    setLibraryLoadError('');
    setVoices([]);
    setUploadedFiles([]);
    setNotifications([]);
    setRuntimeConfig(null);
    notificationBootstrapDoneRef.current = false;
    seenNotificationIdsRef.current = readSeenNotificationIds();
  }

  function play(list, index = 0) {
    const playable = (list || []).filter((item) => item && item.id && String(item.status || '').toLowerCase() !== 'failed');
    if (!playable.length) return notify('Keine abspielbare Audiodatei gefunden.', 'error');
    const safeIndex = Math.max(0, Math.min(index, playable.length - 1));
    setQueue(playable);
    setCurrentIndex(safeIndex);
    setLastPlayedAsset(playable[safeIndex] || null);
  }

  useEffect(() => {
    if (!assets?.length || !queue?.length) return;
    const byId = new Map(assets.map((asset) => [String(asset.id), asset]));
    setQueue((current) => {
      let changed = false;
      const next = (current || []).map((item) => {
        const fresh = byId.get(String(item?.id || ''));
        if (!fresh) return item;
        const merged = { ...item, ...fresh };
        if (
          merged.public_url !== item.public_url
          || merged.local_path !== item.local_path
          || merged.status !== item.status
          || merged.filename !== item.filename
          || merged.duration_seconds !== item.duration_seconds
          || merged.updated_at !== item.updated_at
          || merged.srt_cached !== item.srt_cached
          || merged.half_srt_cached !== item.half_srt_cached
          || merged.latest_srt_status !== item.latest_srt_status
          || merged.latest_srt_generated_at !== item.latest_srt_generated_at
        ) {
          changed = true;
          return merged;
        }
        return item;
      });
      return changed ? next : current;
    });
  }, [assets, queue?.length]);

  const sendPlayerCommand = useCallback((action) => {
    setPlayerCommand((current) => ({ seq: Number(current?.seq || 0) + 1, action }));
  }, []);

  const toggleCurrentPlayer = useCallback(() => {
    sendPlayerCommand('toggle');
  }, [sendPlayerCommand]);

  const closeAudioPlayer = useCallback(() => {
    sendPlayerCommand('stop');
    setQueue([]);
    setCurrentIndex(0);
    setPlayerState({ currentAssetId: null, isPlaying: false, currentTime: 0, duration: 0 });
  }, [sendPlayerCommand]);

  useEffect(() => {
    if (activeTab !== 'daw') return;
    const activeDawAssetId = String(dawOpenAssetId || (typeof window !== 'undefined' ? dawAssetIdFromLocation() : '') || '').trim();
    if (!activeDawAssetId || !queue?.length) return;
    closeAudioPlayer();
  }, [activeTab, dawOpenAssetId, queue?.length, closeAudioPlayer]);

  const replayLastPlayedAsset = useCallback(() => {
    const lastId = String(lastPlayedAsset?.id || playerState.currentAssetId || '').trim();
    if (!lastId) {
      notify('Kein zuletzt gespielter Song vorhanden.', 'info');
      return;
    }
    const freshAsset = assets.find((asset) => String(asset?.id || '') === lastId);
    const asset = freshAsset || lastPlayedAsset;
    if (!asset?.id || String(asset.status || '').toLowerCase() === 'failed') {
      notify('Der zuletzt gespielte Song ist nicht mehr abspielbar.', 'warning');
      return;
    }
    setQueue([asset]);
    setCurrentIndex(0);
    setLastPlayedAsset(asset);
    setActiveTab('library');
    notify('Zuletzt gespielter Song wird wiedergegeben.', 'info');
  }, [assets, lastPlayedAsset, notify, playerState.currentAssetId]);

  useEffect(() => {
    function handlePlayerCommand(event) {
      const action = String(event?.detail?.action || '').trim();
      if (!action) return;
      sendPlayerCommand(action);
    }
    window.addEventListener('player:command', handlePlayerCommand);
    return () => window.removeEventListener('player:command', handlePlayerCommand);
  }, [sendPlayerCommand]);

  const handleLibraryDetailRouteChange = useCallback((nextValue = '') => {
    const normalized = String(nextValue || '').trim();
    setLibraryRouteTitle((current) => (String(current || '').trim() === normalized ? current : normalized));
  }, []);

  const closeLibraryDetails = useCallback(() => {
    setLibraryOpenAssetId(null);
    setLibraryRouteTitle('');
    setLibraryResetSignal((value) => value + 1);
    setActiveTab('library');
  }, []);

  const requestLibraryAssetOpen = useCallback((assetId) => {
    const normalized = String(assetId || '').trim();
    if (!normalized) return;
    setLibraryOpenAssetId(normalized);
    setLibraryOpenRequestKey((value) => value + 1);
    setActiveTab('library');
  }, []);

  function openCurrentPlayerDetails() {
    const currentAsset = queue?.[currentIndex];
    if (!currentAsset?.id) {
      notify('Kein aktiver Song für Details vorhanden.', 'info');
      return;
    }
    requestLibraryAssetOpen(currentAsset.id);
  }

  function isKeyboardInputTarget(event) {
    if (typeof document !== 'undefined' && document.body?.classList?.contains('app-modal-open')) return true;
    const target = event.target;
    if (!target || !(target instanceof Element)) return false;
    const editable = target.closest('[contenteditable="true"], [contenteditable=""], [role="textbox"], .cm-editor, .monaco-editor');
    if (editable) return true;
    const scrollableTextRegion = target.closest('.keyboard-scroll-region, .prompt-lyrics-card pre, .srt-preview, .large-pre, .tech-details pre, .metadata-split pre, .variant-meta-grid pre');
    if (scrollableTextRegion) return true;
    const field = target.closest('input, textarea, select');
    if (!field) return false;
    const tag = String(field.tagName || '').toLowerCase();
    if (tag === 'textarea' || tag === 'select') return true;
    const inputType = String(field.getAttribute('type') || 'text').toLowerCase();
    return !['button', 'submit', 'reset', 'checkbox', 'radio', 'range', 'color', 'file'].includes(inputType);
  }

  function hasTransientUiOverlay() {
    if (typeof document === 'undefined') return false;
    return Boolean(document.querySelector('.audio-action-menu-portal, .profile-dropdown, .status-detail-modal, .global-assistant-panel'));
  }

  useEffect(() => {
    function handleKeyboard(event) {
      if (isKeyboardInputTarget(event) || event.altKey || event.ctrlKey || event.metaKey) return;
      const key = event.key;
      const lower = String(key || '').toLowerCase();
      const dawManagedKeys = new Set([' ', 'k', 'p', 's', 'delete', 'backspace', 'escape', 'arrowleft', 'arrowright']);
      if (activeTab === 'daw' && dawManagedKeys.has(lower === ' ' ? ' ' : lower)) return;
      const hasQueue = Boolean(queue?.length);
      const hasLibraryDetails = activeTab === 'library' && Boolean(String(libraryRouteTitle || '').trim() || routeDetailSegment(routePathname, 'library'));

      if (lower === 'x' && hasLibraryDetails) {
        event.preventDefault();
        closeLibraryDetails();
        return;
      }

      if (key === 'Escape') {
        if (mobileSearchOpen || topbarMenuOpen) {
          event.preventDefault();
          setMobileSearchOpen(false);
          setTopbarMenuOpen(false);
          return;
        }
        if (hasTransientUiOverlay()) {
          // Das jeweilige Overlay behandelt ESC selbst. Der globale Handler
          // darf in diesem Schritt nicht zusätzlich Songdetails schließen.
          event.preventDefault();
          return;
        }
        if (hasLibraryDetails) {
          event.preventDefault();
          closeLibraryDetails();
          return;
        }
      }

      if (key === ' ' || lower === 'k' || lower === 'p') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('toggle');
        return;
      }
      if (key === 'ArrowRight') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand(event.shiftKey ? 'next' : 'seek-forward');
        return;
      }
      if (key === 'ArrowLeft') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand(event.shiftKey ? 'previous' : 'seek-backward');
        return;
      }
      if (lower === 'j') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('seek-backward');
        return;
      }
      if (lower === 'l') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('seek-forward');
        return;
      }
      if (lower === 'v') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('restart-current');
        return;
      }
      if (lower === 'n' || lower === 'w') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('next');
        return;
      }
      if (lower === 'z') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('previous');
        return;
      }
      if (lower === 'm') {
        event.preventDefault();
        setSidebarMode((current) => current === 'open' ? 'compact' : current === 'compact' ? 'closed' : 'open');
        return;
      }
      if (lower === 'r') {
        event.preventDefault();
        setLoop((value) => !value);
        notify(`Loop ${loop ? 'deaktiviert' : 'aktiviert'}.`, 'info');
        return;
      }
      if (lower === 's') {
        if (!hasQueue) return;
        event.preventDefault();
        sendPlayerCommand('stop-playback');
        notify('Wiedergabe gestoppt.', 'info');
        return;
      }
      if (lower === 'c') {
        if (!hasQueue) return;
        event.preventDefault();
        closeAudioPlayer();
        notify('Audio-Player geschlossen.', 'info');
        return;
      }
      if (lower === 'b') {
        event.preventDefault();
        replayLastPlayedAsset();
        return;
      }
      if (lower === 'd') {
        if (!hasQueue) return;
        event.preventDefault();
        openCurrentPlayerDetails();
        return;
      }
      if (key === '?' || lower === 'h') {
        event.preventDefault();
        setHelpModalOpen(true);
      }
    }

    window.addEventListener('keydown', handleKeyboard, { capture: true });
    return () => window.removeEventListener('keydown', handleKeyboard, { capture: true });
  }, [queue, currentIndex, sendPlayerCommand, loop, notify, closeAudioPlayer, activeTab, libraryRouteTitle, routePathname, closeLibraryDetails, replayLastPlayedAsset, mobileSearchOpen, topbarMenuOpen]);

  function openMainTab(key, options = {}) {
    const safeKey = tabKeys.has(key) ? key : 'home';
    if (safeKey === 'music') setMusicWizardSignal(Boolean(options.wizard));
    if (safeKey === 'library') {
      setLibraryOpenAssetId(null);
      setLibraryRouteTitle('');
      setLibraryResetSignal((value) => value + 1);
    } else {
      setLibraryRouteTitle('');
    }
    setOpenNavGroup(null);
    setMobileNavOpen(false);
    setActiveTab(safeKey);
  }

  function openAssetInDaw(assetOrId) {
    const rawId = typeof assetOrId === 'object' && assetOrId !== null
      ? assetOrId.id || assetOrId.audio_asset_id || assetOrId.asset_id
      : assetOrId;
    const normalized = String(rawId || '').trim();
    if (!normalized) {
      notify?.('Kein gueltiges AudioAsset fuer die Mini-DAW gefunden.', 'error');
      return;
    }
    setDawOpenAssetId(normalized);
    try {
      localStorage.setItem('react-daw-asset-id', normalized);
    } catch {
      // localStorage ist nur Komfortzustand; URL bleibt die Quelle.
    }
    if (queue?.length) closeAudioPlayer();
    setLibraryRouteTitle('');
    setOpenNavGroup(null);
    setMobileNavOpen(false);
    setActiveTab('daw');
    if (typeof window !== 'undefined') {
      const targetPath = dawPath(normalized, window.location.pathname);
      const currentPath = `${window.location.pathname.replace(/\/+$/, '') || '/'}${window.location.search || ''}`;
      if (currentPath !== targetPath) {
        window.history.pushState({ activeTab: 'daw', dawAssetId: normalized }, '', targetPath);
        setRoutePathname(window.location.pathname);
      }
    }
  }

  function tabHref(key, detailTitle = '') {
    return tabPath(key, typeof window !== 'undefined' ? window.location.pathname : '', detailTitle);
  }

  function tabFullHref(key) {
    if (typeof window === 'undefined') return tabHref(key);
    return new URL(tabHref(key, key === 'library' ? libraryRouteTitle : ''), window.location.origin).toString();
  }

  function openTabLink(event, key, options = {}) {
    event?.preventDefault?.();
    openMainTab(key, options);
  }


  function handleHeaderBack(event) {
    event?.preventDefault?.();
    if (activeTab === 'library' && (libraryRouteTitle || routeDetailSegment(routePathname, 'library'))) {
      closeLibraryDetails();
      return;
    }
    if (activeTab === 'daw' && (dawOpenAssetId || dawAssetIdFromLocation())) {
      setDawOpenAssetId('');
      try {
        localStorage.removeItem('react-daw-asset-id');
      } catch {
        // localStorage ist nur Komfortzustand; Navigation bleibt zustandsbasiert.
      }
      setActiveTab('daw');
      if (typeof window !== 'undefined') {
        const targetPath = tabPath('daw', window.location.pathname);
        window.history.pushState({ activeTab: 'daw' }, '', targetPath);
        setRoutePathname(window.location.pathname);
      }
      return;
    }
    if (typeof window !== 'undefined' && window.history.length > 1) {
      window.history.back();
      return;
    }
    openMainTab('home');
  }

  function cycleSidebarMode() {
    setSidebarMode((current) => current === 'open' ? 'compact' : current === 'compact' ? 'closed' : 'open');
  }

  function runCommand(rawQuery) {
    const query = String(rawQuery || '').trim();
    if (!query) return;
    setMobileSearchOpen(false);
    setTopbarMenuOpen(false);
    const lower = query.toLowerCase();

    const directTab = tabs.find(([key, label]) => {
      const localizedLabel = localizedTabLabels[key] || label;
      return lower === key
        || lower.includes(String(label).toLowerCase())
        || lower.includes(String(localizedLabel).toLowerCase());
    });
    if (directTab) {
      openMainTab(directTab[0], directTab[0] === 'music' && lower.includes('wizard') ? { wizard: true } : {});
      setCommandQuery('');
      notify(t('messages.opened', '{{label}} geöffnet.', { label: localizedTabLabels[directTab[0]] || directTab[1] }), 'info');
      return;
    }

    if (lower.includes('song') && (lower.includes('neu') || lower.includes('erstellen') || lower.includes('generieren'))) {
      openMainTab('music', { wizard: true });
      setCommandQuery('');
      notify(t('messages.songWizardOpened', 'Song-Wizard geöffnet.'), 'info');
      return;
    }

    if (lower.includes('status') || lower.includes('task') || lower.includes('fehler')) {
      openMainTab('status');
      setCommandQuery('');
      return;
    }

    const assetMatch = assets.find((asset) => assetSearchText(asset).includes(lower));
    if (assetMatch) {
      if (lower.includes('daw') || lower.includes('bearbeiten') || lower.includes('schneiden')) {
        openAssetInDaw(assetMatch.id);
        notify(`${assetMatch.title || 'Song'} in Mini-DAW geöffnet.`, 'info');
      } else {
        openMainTab('library');
      }
      return;
    }

    if (activeTab === 'library') return;

    notify('Kein direkter Treffer. Tipp: Songtitel, Mini-DAW, Musik, Library oder Status eingeben.', 'info');
  }

  function useLyricForMusic(item) {
    const tagText = String(item?.tags || item?.structure_template || '').toLowerCase();
    const isInstrumentalBlueprint = ['instrumental', 'instrumental_blueprint', 'blueprint', 'sound_blueprint'].includes(String(item?.work_mode || '').toLowerCase().replace('-', '_')) || Boolean(item?.instrumental) || tagText.includes('instrumental') || tagText.includes('bauplan');
    setMusicDraft({
      title: item.title,
      prompt: item.content || item.lyrics || item.prompt || '',
      style: item.style || item.tags || item.style_text || '',
      instrumental: isInstrumentalBlueprint,
      customMode: true,
      work_mode: isInstrumentalBlueprint ? 'instrumental_blueprint' : 'lyrics'
    });
    setActiveTab('music');
    notify(isInstrumentalBlueprint ? 'Instrumental-Bauplan wurde für Musik übernommen.' : 'Songtext wurde für Musik übernommen.', 'success');
  }

  async function useStyleForMusic(item) {
    if (!item) return;
    try {
      if (item.id) await api.library.useStyle(item.id);
      setMusicDraft({
        title: '',
        prompt: '',
        style: item.style_text || item.content || item.description || '',
        instrumental: false,
        customMode: true,
        work_mode: 'lyrics'
      });
      setActiveTab('music');
      notify('Style wurde für Musik übernommen.', 'success');
      refreshAll();
    } catch (error) {
      notify(error?.message || 'Style konnte nicht für Musik übernommen werden.', 'error');
    }
  }

  function reusePromptForMusic(payload) {
    setMusicDraft({
      title: payload?.title || '',
      prompt: payload?.prompt || payload?.lyrics || '',
      style: payload?.style || '',
      operationMode: payload?.operationMode || undefined,
      selectedAssetId: payload?.selectedAssetId || payload?.assetId || undefined,
      continueAt: payload?.continueAt || undefined,
      audioUrl: payload?.audioUrl || undefined,
      audioIdInput: payload?.audioIdInput || payload?.audioId || undefined,
      taskIdInput: payload?.taskIdInput || payload?.taskId || undefined,
      customMode: payload?.customMode,
      instrumental: payload?.instrumental,
      work_mode: payload?.work_mode || undefined,
      forceAdvanced: Boolean(payload?.forceAdvanced)
    });
    setMusicWizardSignal(false);
    setActiveTab('music');
    notify(payload?.message || (payload?.operationMode ? 'Musik-Operation wurde vorbereitet.' : 'Prompt und Style wurden in Musik übernommen.'), 'success');
  }

  const handleLibraryOpenAssetHandled = useCallback(() => {
    setLibraryOpenAssetId(null);
  }, []);

  const openLibraryAssetFromPlayer = useCallback((asset) => {
    if (!asset?.id) return;
    requestLibraryAssetOpen(asset.id);
  }, [requestLibraryAssetOpen]);

  const handleMusicStarted = useCallback(async (task) => {
    setPollingUntil(Date.now() + POLLING_AFTER_CREATE_MS);
    await refreshPendingAndReload({ silent: true });
    await refreshAll({ silent: true, forceContentRefresh: true });
    if (task?.task_id || task?.taskId || task?.id) {
      const taskId = task.task_id || task.taskId || task.id;
      notify(`Song gestartet. Statusprüfung läuft automatisch. Task: ${String(taskId).slice(0, 16)}…`, 'success');
    }
  }, [refreshPendingAndReload, refreshAll, notify]);

  function findTaskForNotification(notification) {
    const payload = notification?.target_payload || {};
    const localId = payload.task_local_id || notification?.task_local_id;
    const sunoTaskId = payload.suno_task_id || notification?.suno_task_id;
    return tasks.find((task) => {
      if (localId && String(task.id) === String(localId)) return true;
      if (sunoTaskId && task.task_id && String(task.task_id) === String(sunoTaskId)) return true;
      return false;
    }) || null;
  }

  async function openNotification(notification) {
    setToast(null);
    const payload = notification?.target_payload || {};
    const localId = payload.task_local_id || notification?.task_local_id;
    const knownTask = findTaskForNotification(notification);

    setStatusDetail({
      open: true,
      notification,
      task: knownTask,
      loadingTask: Boolean(!knownTask && localId)
    });

    if (!knownTask && localId) {
      try {
        const task = await api.music.getTask(localId);
        setStatusDetail((current) => {
          const currentLocalId = current.notification?.target_payload?.task_local_id || current.notification?.task_local_id;
          if (!current.open || String(currentLocalId) !== String(localId)) return current;
          return { ...current, task, loadingTask: false };
        });
      } catch {
        setStatusDetail((current) => ({ ...current, loadingTask: false }));
      }
    }
  }

  function openTaskDetails(task) {
    setStatusDetail({ open: true, notification: null, task, loadingTask: false });
  }

  function closeStatusDetail() {
    setStatusDetail({ open: false, notification: null, task: null, loadingTask: false });
  }



  function prepareRetryFromStatus(task, mode = 'same') {
    const request = task?.request_payload || {};
    const next = { ...request };
    if (mode === 'without_voice' || mode === 'safe_check') {
      delete next.voice_id;
      delete next.voiceId;
      delete next.persona_id;
      delete next.personaId;
      delete next.persona_model;
      delete next.personaModel;
    }
    setMusicDraft({
      title: next.title || request.title || `Retry ${task?.id || ''}`.trim(),
      prompt: next.prompt || next.lyrics || request.prompt || request.lyrics || '',
      style: next.style || next.tags || request.style || request.tags || '',
      customMode: next.customMode ?? next.custom_mode ?? true,
      instrumental: Boolean(next.instrumental),
      work_mode: next.instrumental ? 'instrumental_blueprint' : 'lyrics',
      safeCheckRequested: mode === 'safe_check',
      source_task_id: task?.id || null
    });
    setMusicWizardSignal(false);
    setActiveTab('music');
    closeStatusDetail();
    notify(mode === 'without_voice' ? 'Retry ohne Voice wurde im Musikbereich vorbereitet.' : mode === 'safe_check' ? 'Retry wurde im Musikbereich für den Safe-Check vorbereitet.' : 'Retry wurde im Musikbereich vorbereitet.', 'info');
  }

  async function openStatusDetailTarget(detail) {
    const notification = detail?.notification || null;
    const task = detail?.task || null;
    const payload = notification?.target_payload || {};
    const requestPayload = task?.request_payload || {};
    const resultPayload = task?.result_payload || {};
    const responsePayload = task?.response_payload || {};

    const pickPayloadValue = (...keys) => {
      for (const source of [payload, resultPayload, responsePayload, requestPayload]) {
        if (!source || typeof source !== 'object') continue;
        for (const key of keys) {
          const value = source[key];
          if (value !== undefined && value !== null && String(value).trim() !== '') return value;
        }
      }
      return null;
    };

    const firstIdFromList = (value) => {
      const list = Array.isArray(value) ? value : String(value || '').split(',');
      const first = list.map((item) => String(item || '').trim()).find(Boolean);
      return first || null;
    };

    const findNestedPayloadValue = (...keys) => {
      const wanted = new Set(keys);
      const visit = (value, depth = 0) => {
        if (value == null || depth > 5) return null;
        if (Array.isArray(value)) {
          for (const item of value) {
            const found = visit(item, depth + 1);
            if (found !== null && found !== undefined && String(found).trim() !== '') return found;
          }
          return null;
        }
        if (typeof value !== 'object') return null;
        for (const [key, item] of Object.entries(value)) {
          if (wanted.has(key) && item !== undefined && item !== null && String(item).trim() !== '') return item;
        }
        for (const item of Object.values(value)) {
          const found = visit(item, depth + 1);
          if (found !== null && found !== undefined && String(found).trim() !== '') return found;
        }
        return null;
      };
      for (const source of [payload, resultPayload, responsePayload, requestPayload]) {
        const found = visit(source);
        if (found !== null && found !== undefined && String(found).trim() !== '') return found;
      }
      return null;
    };

    const contentType = String(notification?.content_type || '').toLowerCase();
    const payloadAudioId = pickPayloadValue('audio_asset_id', 'asset_id', 'audioAssetId')
      || findNestedPayloadValue('audio_asset_id', 'asset_id', 'audioAssetId');
    const payloadAudioIds = pickPayloadValue('audio_asset_ids', 'asset_ids', 'audioAssetIds')
      || findNestedPayloadValue('audio_asset_ids', 'asset_ids', 'audioAssetIds');
    const audioAssetId = payloadAudioId
      || (['audio', 'audio_asset', 'audio-asset'].includes(contentType) ? notification?.content_id : null)
      || firstIdFromList(payloadAudioIds);
    const songId = pickPayloadValue('song_id', 'songId')
      || (contentType === 'song' ? notification?.content_id : null);
    const targetTab = String(notification?.target_tab || payload.target_tab || pickPayloadValue('target_tab', 'targetTab') || '').trim();

    const relatedAsset = assets.find((asset) => {
      if (audioAssetId && String(asset.id) === String(audioAssetId)) return true;
      if (task?.id && String(asset.task_local_id || '') === String(task.id)) return true;
      if (task?.task_id && String(asset.suno_task_id || '') === String(task.task_id)) return true;
      return false;
    });

    let resolvedAssetId = audioAssetId || relatedAsset?.id || null;
    if (resolvedAssetId && !relatedAsset) {
      const snapshot = await refreshAll({ silent: true, forceContentRefresh: true, deferContentWhilePlaying: true }).catch(() => null);
      const refreshedAsset = (snapshot?.assets || []).find((asset) => String(asset?.id || '') === String(resolvedAssetId));
      if (!refreshedAsset && !audioAssetId) resolvedAssetId = null;
    }

    if (resolvedAssetId) {
      requestLibraryAssetOpen(resolvedAssetId);
      closeStatusDetail();
      return;
    }

    if (songId || contentType === 'song') {
      setActiveTab('texts');
      closeStatusDetail();
      return;
    }

    if (targetTab && tabKeys.has(targetTab)) {
      setActiveTab(targetTab);
      closeStatusDetail();
      return;
    }

    setActiveTab('status');
    closeStatusDetail();
  }

  // Live-Ansicht: solange das Statusdetail-Modal offen ist und der Task noch aktiv
  // läuft, den Task gezielt nachladen. Bewusst ein kleiner, gezielter GET (nicht der
  // große refreshAll) – läuft daher unabhängig vom Player-Lock und stört die
  // Wiedergabe nicht. Stoppt automatisch, sobald der Task terminal ist.
  useEffect(() => {
    if (!statusDetail.open) return undefined;
    const taskId = statusDetail.task?.id
      || statusDetail.notification?.target_payload?.task_local_id
      || statusDetail.notification?.task_local_id;
    if (!taskId) return undefined;
    const ACTIVE = new Set(['PENDING', 'PROCESSING', 'RUNNING', 'QUEUED', 'SUBMITTED', 'CREATED', 'TEXT_SUCCESS', 'FIRST_SUCCESS', 'CANCEL_REQUESTED']);
    const isActive = (t) => ACTIVE.has(String(t?.status || '').trim().toUpperCase());
    if (statusDetail.task && !isActive(statusDetail.task)) return undefined;

    let stopped = false;
    let timerId = null;
    const tick = async () => {
      if (stopped) return;
      try {
        const fresh = await api.music.getTask(taskId);
        if (stopped) return;
        setStatusDetail((current) => {
          if (!current.open) return current;
          const currentId = current.task?.id
            || current.notification?.target_payload?.task_local_id
            || current.notification?.task_local_id;
          if (String(currentId) !== String(taskId)) return current;
          return { ...current, task: fresh, loadingTask: false };
        });
        if (!isActive(fresh)) {
          stopped = true;
          return;
        }
      } catch {
        // transienter Fehler – beim nächsten Tick erneut versuchen
      }
      if (!stopped) timerId = window.setTimeout(tick, STATUS_DETAIL_POLL_MS);
    };
    timerId = window.setTimeout(tick, STATUS_DETAIL_POLL_MS);
    return () => {
      stopped = true;
      if (timerId) window.clearTimeout(timerId);
    };
  }, [statusDetail.open, statusDetail.task?.id, statusDetail.task?.status, statusDetail.notification]);

  async function refreshTaskFromDetail(task) {
    if (!task?.id) return;
    setModalTaskRefreshRunning(true);
    try {
      const updatedTask = await api.music.refreshTask(task.id);
      setStatusDetail((current) => ({ ...current, task: updatedTask, loadingTask: false }));
      await refreshAll({ silent: true, deferContentWhilePlaying: true });
      notify('Task wurde geprüft.', 'success');
    } catch (err) {
      notify(err?.message || 'Task konnte nicht geprüft werden.', 'error');
    } finally {
      setModalTaskRefreshRunning(false);
    }
  }

  async function cancelTaskFromDetail(task) {
    if (!task?.id) return;
    setModalTaskCancelRunning(true);
    try {
      const updatedTask = await api.music.cancelTask(task.id);
      setStatusDetail((current) => ({ ...current, task: updatedTask || current.task, loadingTask: false }));
      await refreshAll({ silent: true, deferContentWhilePlaying: true });
      notify('Abbruch angefordert. Der Job stoppt beim nächsten sicheren Prüfpunkt.', 'info');
    } catch (err) {
      notify(err?.message || 'Job konnte nicht abgebrochen werden.', 'error');
    } finally {
      setModalTaskCancelRunning(false);
    }
  }

  async function markNotificationDoneFromDetail(notification) {
    if (!notification?.id) return;
    await api.notifications.markDone(notification.id);
    setStatusDetail((current) => ({
      ...current,
      notification: current.notification ? { ...current.notification, status: 'done' } : current.notification
    }));
    await refreshAll({ silent: true, deferContentWhilePlaying: true });
    notify('Meldung wurde als erledigt markiert.', 'success');
  }

  async function closeToast(markNotificationDone = true) {
    const notificationId = toast?.notification?.id;
    setToast(null);

    if (markNotificationDone && notificationId) {
      await api.notifications.markDone(notificationId).catch(() => null);
      await refreshAll({ silent: true, deferContentWhilePlaying: true }).catch(() => null);
    }
  }

  const autoCloseToast = useCallback(() => {
    const notificationId = toast?.notification?.id;
    setToast(null);

    if (toastAutoMarkDone && notificationId) {
      api.notifications.markDone(notificationId)
        .then(() => refreshAll({ silent: true, deferContentWhilePlaying: true }))
        .catch(() => null);
    }
  }, [toast?.notification?.id, toastAutoMarkDone, refreshAll]);

  const executeFrontendAction = useMemo(() => createAssistantActions({ openMainTab, openAssetInDaw, play, assets, refreshAll, notify, playerState }), [assets, refreshAll, notify, playerState.currentAssetId, playerState.isPlaying, playerState.duration]);
  const localizedTabLabels = useMemo(
    () => Object.fromEntries(tabs.map(([key, label]) => [key, t(`nav.${key}`, label)])),
    [t]
  );
  const localizedSidebarSections = useMemo(() => ([
    { label: t('nav.groups.collection', 'Sammlung'), keys: ['playlists', 'styles', 'texts', 'daw'] },
    { label: t('nav.groups.control', 'System'), keys: ['admin', 'audit', 'system'] }
  ]), [t]);
  const toggleLanguage = useCallback(() => {
    setLanguage(language === 'en' ? 'de' : 'en');
  }, [language, setLanguage]);

  function buildAssistantContext() {
    const lyricsState = JSON.parse(localStorage.getItem('assistant-lyrics-state') || '{}');
    return {
      active_tab: activeTab,
      page_label: localizedTabLabels[activeTab] || tabLabels[activeTab] || activeTab,
      route: tabPath(activeTab, typeof window !== 'undefined' ? window.location.pathname : ''),
      assets_count: listCount(assets),
      lyrics_count: listCount(lyrics),
      styles_count: listCount(styles),
      voices_count: listCount(voices),
      uploaded_files_count: listCount(uploadedFiles),
      playlists_count: listCount(playlists),
      tasks_count: listCount(tasks),
      active_tasks_count: activeTaskCount(tasks),
      current_audio_asset_id: playerState.currentAssetId || null,
      current_audio_time: playerState.currentTime || 0,
      current_audio_is_playing: Boolean(playerState.isPlaying),
      last_task_check: taskRefreshState.lastCheck,
      last_task_check_message: taskRefreshState.lastMessage,
      notifications_count: normalizeApiList(notifications, ['notifications', 'items']).filter((item) => item.status === 'unread').length,
      current_canvas: lyricsState.canvas || '',
      current_studio_mode: lyricsState.studioMode || 'lyrics',
      current_session_title: lyricsState.sessionTitle || '',
      current_session_id: lyricsState.sessionId || null,
      assistant_profile_id: lyricsState.profileId ? Number(lyricsState.profileId) : null,
      workflow_step: musicWizardSignal ? t('assistant.workflowWizardActive', 'Song-Wizard aktiv') : '',
      available_actions: buildAvailableAssistantActions(activeTab, lyricsState, { musicWizardSignal })
    };
  }

  const libraryRouteDetailSlug = useMemo(() => (activeTab === 'library' ? routeDetailSegment(routePathname, 'library') : ''), [activeTab, routePathname]);

  // Fuer Inhaltsseiten ist die Playerzeit waehrend laufender Wiedergabe bewusst
  // eingefroren. Der MiniPlayer rendert die Live-Zeit selbst; Library/Details
  // duerfen nicht mit jedem Audiotick neu rendern.
  const stablePlaybackTime = Number(playerState.currentTime || 0);
  const stablePlaybackState = useMemo(() => ({
    currentAssetId: playerState.currentAssetId || null,
    isPlaying: Boolean(playerState.isPlaying),
    currentTime: stablePlaybackTime,
    duration: Number(playerState.duration || 0),
  }), [
    playerState.currentAssetId,
    playerState.isPlaying,
    stablePlaybackTime,
    playerState.duration
  ]);

  // Aktive Task-/Notification-Livewerte duerfen nicht jede Arbeitsseite neu
  // rendern. Library, Editor und andere Inhaltsseiten brauchen diese Werte nicht
  // direkt; dort wuerden sie Textauswahl, Menues und Klickzeitpunkte stoeren.
  const currentPageTasks = activeTab === 'home' || activeTab === 'status' ? tasks : null;
  const currentPageNotifications = activeTab === 'home' || activeTab === 'status' ? notifications : null;
  const currentPageTaskRefreshState = activeTab === 'music' || activeTab === 'status' ? taskRefreshState : null;
  const navigateFromHelpModal = useCallback((key, options = {}) => {
    setHelpModalOpen(false);
    openMainTab(key, options);
  }, [openMainTab]);

  const currentPage = useMemo(() => {
    if (activeTab === 'home') return <HomePage assets={assets} lyrics={lyrics} playlists={playlists} tasks={tasks} notifications={notifications} onNavigate={openMainTab} onPlay={play} onOpenAsset={requestLibraryAssetOpen} />;
    if (activeTab === 'library') return <LibraryPage assets={assets} loadError={libraryLoadError} voices={voices} playlists={playlists} onReload={refreshAll} onPlay={play} notify={notify} onUseLyric={useLyricForMusic} onReusePrompt={reusePromptForMusic} openAssetId={libraryOpenAssetId} openAssetRequestKey={libraryOpenRequestKey} onOpenAssetHandled={handleLibraryOpenAssetHandled} resetSignal={libraryResetSignal} onOpenDaw={openAssetInDaw} playbackState={stablePlaybackState} onToggleCurrentPlayback={toggleCurrentPlayer} onDetailTitleChange={handleLibraryDetailRouteChange} routeDetailSlug={libraryRouteDetailSlug} searchQuery={commandQuery} onTrashChanged={markTrashHasItems} />;
    if (activeTab === 'imports') return <ImportPage notify={notify} onReload={refreshAll} onOpenAsset={requestLibraryAssetOpen} />;
    if (activeTab === 'music') return <MusicPage styles={styles} voices={voices} uploadedFiles={uploadedFiles} assets={assets} draft={musicDraft} notify={notify} onRefresh={refreshAll} onMusicStarted={handleMusicStarted} initialWizard={musicWizardSignal} taskRefreshState={taskRefreshState} onCheckStatus={() => refreshPendingAndReload({ manual: true })} />;
    if (activeTab === 'lyrics') return <LyricsStudioPage lyrics={lyrics} assets={assets} notify={notify} onRefresh={refreshAll} useForMusic={useLyricForMusic} />;
    if (activeTab === 'texts') return <LibraryTextPage lyrics={lyrics} notify={notify} onReload={refreshAll} useForMusic={useLyricForMusic} searchQuery={commandQuery} />;
    if (activeTab === 'playlists') return <PlaylistsPage playlists={playlists} assets={assets} notify={notify} onReload={refreshAll} onPlay={play} searchQuery={commandQuery} />;
    if (activeTab === 'trash') return <TrashPage notify={notify} onReload={refreshAll} onTrashChanged={setTrashHasItems} />;
    if (activeTab === 'styles') return <StylesPage styles={styles} notify={notify} onReload={refreshAll} useForMusic={useStyleForMusic} searchQuery={commandQuery} />;
    if (activeTab === 'daw') return <DawPage assets={assets} selectedAssetId={dawOpenAssetId || dawAssetIdFromLocation()} onSelectedHandled={() => {}} onAssetChange={(id) => setDawOpenAssetId(String(id || '').trim())} onBackToLibrary={() => openMainTab('library')} onPlay={play} notify={notify} onReload={refreshAll} />;
    if (activeTab === 'admin') return <AdminPage notify={notify} onReload={refreshAll} />;
    if (activeTab === 'audit') return <AuditPage notify={notify} onReload={refreshAll} />;
    if (activeTab === 'status') return <StatusPage notifications={notifications} tasks={tasks} onReload={refreshAll} onCheckStatus={() => refreshPendingAndReload({ manual: true })} taskRefreshState={taskRefreshState} onOpenNotification={openNotification} onOpenTaskDetails={openTaskDetails} notify={notify} />;
    if (activeTab === 'help') return <HelpPage onNavigate={openMainTab} notify={notify} />;
    return <SystemPage notify={notify} uploadedFiles={uploadedFiles} onRefresh={refreshAll} />;
  }, [activeTab, assets, libraryLoadError, lyrics, styles, voices, uploadedFiles, playlists, musicDraft, currentPageNotifications, currentPageTasks, libraryOpenAssetId, dawOpenAssetId, libraryResetSignal, libraryRouteDetailSlug, commandQuery, musicWizardSignal, currentPageTaskRefreshState, stablePlaybackState, toggleCurrentPlayer, handleLibraryOpenAssetHandled, refreshAll, refreshPendingAndReload, handleMusicStarted, notify, requestLibraryAssetOpen, handleLibraryDetailRouteChange, libraryOpenRequestKey, markTrashHasItems]);

  if (!authChecked) return <main className="loading">{t('app.loading', 'Lade Anwendung…')}</main>;
  if (!user) return <Login onLogin={setUser} />;

  const openTaskCount = activeTaskCount(tasks);
  const SidebarTrashIcon = trashHasItems ? Trash2 : Trash;
  const trashLabel = localizedTabLabels.trash || t('nav.trash', 'Papierkorb');
  const currentHeaderPath = tabHref(activeTab, activeTab === 'library' ? libraryRouteTitle : '');
  const routeBackTitle = t('topbar.back', 'Zurueck');

  return (
    <AppAssistantProvider value={{ activeTab, assets, lyrics, styles, voices, playlists, tasks, notifications, executeFrontendAction, buildAssistantContext }}>
      <div className={`studio-shell sidebar-${sidebarMode} ${mobileNavOpen ? 'sidebar-mobile-open' : ''} ${workspaceFocus ? 'workspace-focus' : ''}`}>
        {/* Header-Vertrag: Keine zusätzlichen Desktop-Grid-Siblings in die Topbar einfügen.
            Desktop bleibt: Brand/Back | Suche | Aktionen. Zusätzliche Header-Aktionen
            gehören in .studio-top-actions, sonst bricht die Topbar in mehrere Zeilen. */}
        <header className={`studio-topbar ${mobileSearchOpen ? 'search-open' : ''} ${topbarMenuOpen ? 'menu-open' : ''}`}>
          <div className="topbar-brand-zone">
            <button className="sidebar-mobile-button" type="button" onClick={() => setMobileNavOpen((value) => !value)} aria-expanded={mobileNavOpen} aria-controls="studioSidebar">
              {mobileNavOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
            <button className="sidebar-mode-button" type="button" onClick={cycleSidebarMode} title="Sidebar offen / kompakt / aus">
              <Menu size={18} />
            </button>
            <div className="studio-brand" role="banner">
              <Music size={26} />
              <div>
                <strong>Suno Song Studio</strong>
                <span>{t('app.suite', 'AI Music Production Suite')}</span>
              </div>
            </div>
            <button
              className="studio-route-back-button"
              type="button"
              onClick={handleHeaderBack}
              title={`${routeBackTitle}: ${currentHeaderPath}`}
              aria-label={`${routeBackTitle}: ${currentHeaderPath}`}
            >
              <ArrowLeft size={17} />
            </button>
          </div>

          <form className={`studio-commandbar ${mobileSearchOpen ? 'is-open' : ''}`} onSubmit={(event) => { event.preventDefault(); runCommand(commandQuery); }}>
            <Search size={17} />
            <input value={commandQuery} onChange={(event) => setCommandQuery(event.target.value)} placeholder={t('topbar.searchPlaceholder', 'Song, Task, Bereich oder Befehl suchen …')} />
            <button className="commandbar-close" type="button" onClick={() => setMobileSearchOpen(false)} aria-label={t('topbar.closeSearch', 'Suche schließen')}><X size={15} /></button>
            <kbd>Enter</kbd>
          </form>

          <div className="studio-mobile-actions">
            <button type="button" className={`mobile-scroll-top-button ${showMobileScrollTop ? 'is-visible' : ''}`} onClick={scrollToPageTop} title={t('topbar.scrollTop', 'Nach oben')} aria-label={t('topbar.scrollTop', 'Nach oben')} aria-hidden={!showMobileScrollTop} tabIndex={showMobileScrollTop ? 0 : -1}><ArrowUp size={17} /></button>
            <button type="button" onClick={() => setMobileSearchOpen((value) => { const next = !value; if (next) setTopbarMenuOpen(false); return next; })} className={mobileSearchOpen ? 'active' : ''} title={t('topbar.openSearch', 'Suche öffnen')} aria-expanded={mobileSearchOpen}><Search size={17} /></button>
            <button type="button" onClick={() => setTopbarMenuOpen((value) => { const next = !value; if (next) setMobileSearchOpen(false); return next; })} className={topbarMenuOpen ? 'active' : ''} title={t('topbar.quickMenu', 'Schnellmenü')} aria-expanded={topbarMenuOpen}><MoreHorizontal size={18} /></button>
          </div>


          <div className={`studio-top-actions ${topbarMenuOpen ? 'is-open' : ''}`}>
            <div className={`header-scroll-top-bridge ${showMobileScrollTop ? 'is-visible' : ''}`} aria-hidden={!showMobileScrollTop}>
              <button type="button" className={`header-scroll-top-button ${showMobileScrollTop ? 'is-visible' : ''}`} onClick={scrollToPageTop} title={t('topbar.scrollTop', 'Nach oben')} aria-label={t('topbar.scrollTop', 'Nach oben')} aria-hidden={!showMobileScrollTop} tabIndex={showMobileScrollTop ? 0 : -1}>
                <ArrowUp size={15} />
              </button>
            </div>
            {openTaskCount > 0 && <button className="task-poll-pill live-pill" onClick={() => refreshPendingAndReload({ manual: true })} title={t('topbar.openTasksNow', 'Offene Suno-Tasks jetzt prüfen')}><RefreshCw size={14} className={taskRefreshState.running ? 'spin-icon' : ''} /> {t('topbar.activeTasksShort', '{{count}} aktiv', { count: openTaskCount })}</button>}
            <span className="credits topbar-credits">{t('topbar.credits', 'Credits: {{value}}', { value: credits ?? '—' })}</span>
            <button className={workspaceFocus ? 'active focus-toggle-button' : 'focus-toggle-button'} type="button" onClick={() => setWorkspaceFocus((value) => !value)} title={t('topbar.focusTitle', 'Zusatzcontainer ein-/ausblenden')}><Command size={16} /><span>{t('topbar.focus', 'Fokus')}</span></button>
            <button className="header-help-button" type="button" onClick={() => setHelpModalOpen(true)} title={t('topbar.help', 'Hilfe öffnen (H)')} aria-label={t('topbar.help', 'Hilfe öffnen (H)')}><CircleHelp size={17} /></button>
            <button className="language-toggle-button" type="button" onClick={toggleLanguage} title={t('language.switchTo', 'Auf Englisch umschalten')} aria-label={t('language.switchTo', 'Auf Englisch umschalten')}>
              <span>{t('language.code', 'DE')}</span>
            </button>
            <button className="theme-toggle-button" type="button" onClick={toggleTheme} title={theme === 'light' ? t('topbar.enableDark', 'Dark Mode aktivieren') : t('topbar.enableLight', 'Light Mode aktivieren')} aria-label={theme === 'light' ? t('topbar.enableDark', 'Dark Mode aktivieren') : t('topbar.enableLight', 'Light Mode aktivieren')}>
              {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
              <span>{theme === 'light' ? t('topbar.dark', 'Dark') : t('topbar.light', 'Light')}</span>
            </button>
            <button onClick={() => refreshAll()} className={refreshing ? 'spin' : ''} title={t('topbar.refresh', 'Aktualisieren')}><RefreshCw size={16} /></button>
            <ProfileMenu user={user} voices={voices} uploadedFiles={uploadedFiles} onUserUpdate={setUser} onLogout={logout} onRefresh={refreshAll} notify={notify} />
          </div>
        </header>

        <aside id="studioSidebar" className="studio-sidebar" aria-label={t('nav.mainNavigation', 'Hauptnavigation')}>
          <nav className="studio-sidebar-nav">
            <div className="sidebar-direct-nav" aria-label={t('nav.directNavigation', 'Direktnavigation')}>
              {directSidebarKeys.map((key) => {
                const tab = tabByKey[key];
                if (!tab) return null;
                const [, label, Icon] = tab;
                const displayLabel = localizedTabLabels[key] || label;
                return (
                  <a key={key} className={`sidebar-link sidebar-direct-link ${activeTab === key ? 'active' : ''}`} href={tabHref(key, key === 'library' ? libraryRouteTitle : '')} onClick={(event) => openTabLink(event, key)} title={displayLabel}>
                    <Icon size={18} />
                    <span>{displayLabel}</span>
                  </a>
                );
              })}
            </div>
            {localizedSidebarSections.map((section) => {
              const sectionActive = section.keys.includes(activeTab);
              const isOpen = openNavGroup === section.label || sectionActive || sidebarMode === 'compact';
              return (
                <section className={`sidebar-section ${sectionActive ? 'has-active' : ''} ${isOpen ? 'is-open' : ''}`} key={section.label}>
                  <button type="button" className="sidebar-section-title" onClick={() => setOpenNavGroup((current) => current === section.label ? null : section.label)} aria-expanded={isOpen}>
                    <span>{section.label}</span>
                    <ChevronDown size={14} />
                  </button>
                  <div className="sidebar-section-items">
                    {section.keys.map((key) => {
                      const tab = tabByKey[key];
                      if (!tab) return null;
                      const [, label, Icon] = tab;
                      const displayLabel = localizedTabLabels[key] || label;
                      return (
                        <a key={key} className={`sidebar-link ${activeTab === key ? 'active' : ''}`} href={tabHref(key)} onClick={(event) => openTabLink(event, key)} title={displayLabel}>
                          <Icon size={18} />
                          <span>{displayLabel}</span>
                        </a>
                      );
                    })}
                  </div>
                </section>
              );
            })}
          </nav>
          <a
            className={`sidebar-footer-card sidebar-footer-link sidebar-trash-link ${trashHasItems ? 'has-items' : 'is-empty'} ${activeTab === 'trash' ? 'active' : ''}`}
            href={tabHref('trash')}
            onClick={(event) => openTabLink(event, 'trash')}
            title={trashHasItems ? t('trash.sidebar.hasItems', 'Papierkorb enthält Inhalte') : t('trash.sidebar.empty', 'Papierkorb ist leer')}
            aria-label={trashHasItems ? t('trash.sidebar.hasItems', 'Papierkorb enthält Inhalte') : t('trash.sidebar.empty', 'Papierkorb ist leer')}
          >
            <SidebarTrashIcon size={19} />
            <div>
              <strong>{trashLabel}</strong>
              <small>{trashHasItems ? t('trash.sidebar.hasItemsShort', 'Gelöschte Inhalte vorhanden') : t('trash.sidebar.emptyShort', 'Leer')}</small>
            </div>
          </a>
          <a
            className={`sidebar-footer-card sidebar-footer-link ${activeTab === 'status' ? 'active' : ''}`}
            href={tabHref('status')}
            onClick={(event) => openTabLink(event, 'status')}
            style={{ color: 'inherit', textDecoration: 'none', width: '100%', cursor: 'pointer' }}
            title={t('topbar.statusPageOpen', 'Statusseite öffnen')}
            aria-label={t('topbar.statusFooterAria', '{{count}} aktive Tasks. {{message}}. Statusseite öffnen', { count: openTaskCount, message: taskRefreshState.lastMessage || t('topbar.productionMonitorReady', 'Produktionsmonitor bereit') })}
          >
            <span className="live-dot" />
            <div>
              <strong>{t('topbar.activeTasksLong', '{{count}} aktive Tasks', { count: openTaskCount })}</strong>
              <small>{taskRefreshState.lastMessage || t('topbar.productionMonitorReady', 'Produktionsmonitor bereit')}</small>
            </div>
          </a>
        </aside>
        {mobileNavOpen && <button type="button" className="sidebar-scrim" aria-label={t('topbar.closeSidebar', 'Sidebar schließen')} onClick={() => setMobileNavOpen(false)} />}
        <main className="app-main studio-main-content">{currentPage}</main>
      </div>
      <MiniPlayer queue={queue} currentIndex={currentIndex} loop={loop} sidebarMode={sidebarMode} mobileNavOpen={mobileNavOpen} playerCommand={playerCommand} onPlaybackStateChange={handlePlaybackStateChange} onLoopChange={setLoop} onIndexChange={setCurrentIndex} onOpenDetails={openLibraryAssetFromPlayer} onPrepareMusic={reusePromptForMusic} onFavoriteChange={handleFavoriteChange} onClose={closeAudioPlayer} />
      <GlobalAIAssistant notify={notify} />
      <Toast message={toast?.message} type={toast?.type} onClose={() => closeToast(true)} onClick={toast?.notification ? () => openNotification(toast.notification) : undefined} autoCloseMs={toastAutoCloseMs} onAutoClose={autoCloseToast} toastKey={toast?.notification?.id || toast?.message || ''} />
      <StatusDetailModal
        open={statusDetail.open}
        notification={statusDetail.notification}
        task={statusDetail.task}
        loadingTask={statusDetail.loadingTask}
        onClose={closeStatusDetail}
        onOpenTarget={openStatusDetailTarget}
        onRefreshTask={refreshTaskFromDetail}
        onCancelTask={cancelTaskFromDetail}
        cancelRunning={modalTaskCancelRunning}
        onMarkNotificationDone={markNotificationDoneFromDetail}
        refreshRunning={modalTaskRefreshRunning || taskRefreshState.running}
        onPrepareRetry={prepareRetryFromStatus}
      />
      <Modal open={helpModalOpen} title={t('nav.help', 'Hilfe')} onClose={() => setHelpModalOpen(false)} wide cardClassName="help-modal-card" contentClassName="help-modal-content">
        <HelpPage onNavigate={navigateFromHelpModal} notify={notify} />
      </Modal>
    </AppAssistantProvider>
  );
}
