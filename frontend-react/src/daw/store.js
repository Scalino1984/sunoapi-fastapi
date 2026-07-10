// Zentraler DAW-Store (zustand). Trennt den Arrangement-/UI-Zustand sauber
// von den Komponenten: Undo/Redo, Auswahl, Werkzeuge, Transport und
// Kommandovorschau leben hier – Mutationen laufen ausschließlich über
// createDawCommandPlan bzw. explizite, normalisierte Updates.

import { create } from 'zustand';
import { cloneArrangementSnapshot, arrangementLength, safeNumber } from './timeUtils.js';
import { normalizeArrangement, createDawCommandPlan } from './arrangement.js';

const HISTORY_LIMIT = 60;

export const useDawStore = create((set, get) => ({
  // ---- Projekt / Arrangement ------------------------------------------
  asset: null,
  project: null,
  arrangement: null,
  beatgrid: null,
  sections: [],
  sourceDuration: 0,
  dirty: false,

  // ---- History ----------------------------------------------------------
  undoStack: [],
  redoStack: [],

  // ---- Auswahl / Werkzeuge ---------------------------------------------
  selectedClipId: '',
  selectedSectionId: '',
  selection: null, // { start, end }
  toolMode: 'select',
  closeGap: true,
  timelineZoom: 1,

  // ---- Transport ---------------------------------------------------------
  isPlaying: false,
  currentTime: 0,
  volume: 1,

  // ---- Kommandovorschau / KI ---------------------------------------------
  commandPreview: null,
  aiBusy: false,

  // ---- Setter -------------------------------------------------------------
  setProjectState: (patch) => set(patch),
  setArrangementDirect: (arrangement, { markDirty = true } = {}) =>
    set({ arrangement, dirty: markDirty ? true : get().dirty }),
  setSelectedClipId: (selectedClipId) => set({ selectedClipId }),
  setSelectedSectionId: (selectedSectionId) => set({ selectedSectionId }),
  setSelection: (selection) => set({ selection }),
  setToolMode: (toolMode) => set({ toolMode }),
  setCloseGap: (closeGap) => set({ closeGap }),
  setTimelineZoom: (timelineZoom) => set({ timelineZoom }),
  setIsPlaying: (isPlaying) => set({ isPlaying }),
  setCurrentTime: (currentTime) => set({ currentTime }),
  setVolume: (volume) => set({ volume }),
  setCommandPreview: (commandPreview) => set({ commandPreview }),
  setAiBusy: (aiBusy) => set({ aiBusy }),
  markSaved: () => set({ dirty: false }),

  loadProject: ({ asset, project, arrangement, sections = [], sourceDuration = 0 }) =>
    set({
      asset,
      project,
      arrangement,
      beatgrid: null,
      sections,
      sourceDuration,
      undoStack: [],
      redoStack: [],
      selectedClipId: arrangement?.clips?.[0]?.id || '',
      selection: null,
      commandPreview: null,
      currentTime: 0,
      dirty: false,
    }),

  // ---- History -------------------------------------------------------------
  commitHistory: (snapshot) => {
    const current = snapshot || get().arrangement;
    if (!current) return;
    set((state) => ({
      undoStack: [...state.undoStack.slice(-(HISTORY_LIMIT - 1)), cloneArrangementSnapshot(current)],
      redoStack: [],
    }));
  },
  undo: () => {
    const { undoStack, arrangement } = get();
    if (!undoStack.length || !arrangement) return null;
    const previous = undoStack[undoStack.length - 1];
    set((state) => ({
      undoStack: state.undoStack.slice(0, -1),
      redoStack: [...state.redoStack.slice(-(HISTORY_LIMIT - 1)), cloneArrangementSnapshot(arrangement)],
      arrangement: previous,
      dirty: true,
      commandPreview: null,
    }));
    return previous;
  },
  redo: () => {
    const { redoStack, arrangement } = get();
    if (!redoStack.length || !arrangement) return null;
    const next = redoStack[redoStack.length - 1];
    set((state) => ({
      redoStack: state.redoStack.slice(0, -1),
      undoStack: [...state.undoStack.slice(-(HISTORY_LIMIT - 1)), cloneArrangementSnapshot(arrangement)],
      arrangement: next,
      dirty: true,
      commandPreview: null,
    }));
    return next;
  },

  // ---- Direkte, normalisierte Arrangement-Änderung (Drag, Inspector) --------
  updateArrangement: (updater, { commit = true } = {}) => {
    const { arrangement, asset, sourceDuration } = get();
    if (!arrangement) return null;
    const before = cloneArrangementSnapshot(arrangement);
    const draft = updater(cloneArrangementSnapshot(arrangement));
    if (!draft) return null;
    const normalized = normalizeArrangement(
      draft,
      asset,
      Math.max(sourceDuration, arrangementLength(draft, safeNumber(arrangement.duration_seconds))),
    );
    if (commit) get().commitHistory(before);
    set({ arrangement: normalized, dirty: true });
    return normalized;
  },

  // ---- Kommandoplaner --------------------------------------------------------
  buildCommandContext: (extra = {}) => {
    const state = get();
    return {
      arrangement: state.arrangement,
      asset: state.asset,
      sections: state.sections,
      selectedSection: state.sections.find((section) => section.id === state.selectedSectionId) || null,
      beatgrid: state.beatgrid,
      selection: state.selection,
      selectedClipId: state.selectedClipId,
      currentTime: state.currentTime,
      closeGap: state.closeGap,
      sourceDuration: state.sourceDuration,
      mediaDuration: state.sourceDuration,
      timelineDuration: Math.max(
        arrangementLength(state.arrangement, state.sourceDuration || 1),
        state.sourceDuration,
        1,
      ),
      ...extra,
    };
  },
  previewCommand: (command, extraCtx = {}) => {
    const plan = createDawCommandPlan(command, get().buildCommandContext(extraCtx));
    set({ commandPreview: plan });
    return plan;
  },
  applyCommandPlan: (plan = null) => {
    const state = get();
    const active = plan || state.commandPreview;
    if (!active?.nextArrangement) return null;
    state.commitHistory(active.originalArrangement || state.arrangement);
    const normalized = normalizeArrangement(
      active.nextArrangement,
      state.asset,
      Math.max(active.afterDuration || 0, state.sourceDuration, 1),
    );
    set({
      arrangement: normalized,
      selectedClipId:
        active.nextSelectedClipId && normalized.clips.some((clip) => clip.id === active.nextSelectedClipId)
          ? active.nextSelectedClipId
          : normalized.clips[0]?.id || '',
      selection: active.nextSelection || null,
      commandPreview: null,
      dirty: true,
    });
    return normalized;
  },
}));
