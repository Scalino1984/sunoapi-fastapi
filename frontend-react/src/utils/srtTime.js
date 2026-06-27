export const MIN_SRT_SEGMENT_DURATION = 0.300;
export const DEFAULT_SRT_GAP_SECONDS = 0.080;

export function clampSeconds(value, fallback = 0) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(0, number);
}

export function roundSeconds(value) {
  return Number(clampSeconds(value).toFixed(3));
}

export function formatSrtTimestamp(value) {
  const totalMs = Math.max(0, Math.round(clampSeconds(value) * 1000));
  const hours = Math.floor(totalMs / 3600000);
  const minutes = Math.floor((totalMs % 3600000) / 60000);
  const seconds = Math.floor((totalMs % 60000) / 1000);
  const millis = totalMs % 1000;
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')},${String(millis).padStart(3, '0')}`;
}

export function parseSrtTimestamp(value) {
  const match = String(value || '').trim().replace('.', ',').match(/^(\d{1,3}):(\d{2}):(\d{2}),(\d{1,3})$/);
  if (!match) return 0;
  const [, h, m, s, ms] = match;
  return Number(h) * 3600 + Number(m) * 60 + Number(s) + Number(ms.padEnd(3, '0').slice(0, 3)) / 1000;
}

export function secondsLabel(value) {
  return `${roundSeconds(value).toFixed(3)}s`;
}
