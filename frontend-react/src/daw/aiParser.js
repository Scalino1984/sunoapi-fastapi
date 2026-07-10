// Lokaler DAW-KI-Parser: übersetzt natürliche Befehle (Deutsch) deterministisch
// in prüfbare Timeline-Kommandos für createDawCommandPlan. Der Parser läuft
// sofort und offline; komplexe/mehrdeutige Befehle gehen zusätzlich an das
// FastAPI-Endpoint /api/daw/assets/{id}/arrangement/ai-command.
import { safeNumber, secondsToClock } from './timeUtils.js';
import { SECTION_KIND_LABELS } from './sections.js';
import { inferBpmFromAsset, medianBarLengthFromGrid } from './musicalTime.js';

export function normalizeDawAiText(value = '') {
  return String(value || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/ä/g, 'ae')
    .replace(/ö/g, 'oe')
    .replace(/ü/g, 'ue')
    .replace(/ß/g, 'ss')
    .replace(/[„“”]/g, '"')
    .replace(/[’']/g, '')
    .replace(/[^a-z0-9#+:.,\s-]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

export function dawAiSectionKindFromText(text = '') {
  const raw = normalizeDawAiText(text);
  if (/pre\s*(chorus|hook|refrain)|vor\s*(chorus|hook|refrain)/.test(raw)) return 'pre_chorus';
  if (/post\s*(chorus|hook|refrain)|nach\s*(chorus|hook|refrain)/.test(raw)) return 'post_chorus';
  if (/hook|chorus|refrain|refreng|refrain/.test(raw)) return 'chorus';
  if (/verse|strophe|part\s*\d|rap\s*part/.test(raw)) return 'verse';
  if (/intro|anfang|opening/.test(raw)) return 'intro';
  if (/outro|ende|ending|schluss/.test(raw)) return 'outro';
  if (/bridge|mittelteil/.test(raw)) return 'bridge';
  if (/breakdown|break|pause|interlude/.test(raw)) return 'break';
  if (/drop|climax/.test(raw)) return 'drop';
  if (/instrumental|solo|beat/.test(raw)) return 'instrumental';
  return '';
}

export function dawAiOccurrenceFromText(text = '') {
  const raw = normalizeDawAiText(text);
  if (/letzte[nrms]?|finale[nrms]?|schluss/.test(raw)) return 'last';
  if (/erste[nrms]?|1\.|#?1\b/.test(raw)) return 1;
  if (/zweite[nrms]?|2\.|#?2\b/.test(raw)) return 2;
  if (/dritte[nrms]?|3\.|#?3\b/.test(raw)) return 3;
  if (/vierte[nrms]?|4\.|#?4\b/.test(raw)) return 4;
  if (/fuenfte[nrms]?|funfte[nrms]?|5\.|#?5\b/.test(raw)) return 5;
  return null;
}

export function truncateDawAiPrompt(value = '') {
  const text = String(value || '').trim().replace(/\s+/g, ' ');
  return text.length > 120 ? `${text.slice(0, 117)}…` : text;
}

export function dawAiFirstNumber(text = '', fallback = null) {
  const match = String(text || '').match(/[-+]?\d+(?:[,.]\d+)?/);
  if (!match) return fallback;
  const parsed = Number(match[0].replace(',', '.'));
  return Number.isFinite(parsed) ? parsed : fallback;
}

const DAW_AI_NUMBER_WORDS = {
  ein: 1,
  eine: 1,
  einen: 1,
  eins: 1,
  zwei: 2,
  drei: 3,
  vier: 4,
  fuenf: 5,
  funf: 5,
  sechs: 6,
  sieben: 7,
  acht: 8,
  neun: 9,
  zehn: 10,
  elf: 11,
  zwoelf: 12,
  zwolf: 12,
  dreizehn: 13,
  vierzehn: 14,
  fuenfzehn: 15,
  funfzehn: 15,
  sechzehn: 16,
  siebzehn: 17,
  achtzehn: 18,
  neunzehn: 19,
  zwanzig: 20,
};

function dawAiNumberTokenPattern() {
  return `(?:\\d+(?:[,.]\\d+)?|${Object.keys(DAW_AI_NUMBER_WORDS).join('|')})`;
}

function dawAiNumberFromToken(value, fallback = null) {
  const token = String(value || '').trim().toLowerCase().replace(',', '.');
  if (token in DAW_AI_NUMBER_WORDS) return DAW_AI_NUMBER_WORDS[token];
  const parsed = Number(token);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function dawAiMusicalBarLength(ctx = {}) {
  const fromGrid = medianBarLengthFromGrid(ctx.beatgrid);
  if (fromGrid && fromGrid > 0) return { seconds: fromGrid, source: 'Beatgrid' };
  const bpm = safeNumber(ctx.arrangement?.bpm || inferBpmFromAsset(ctx.asset), 0);
  if (bpm >= 20) return { seconds: 240 / bpm, source: `${Math.round(bpm * 10) / 10} BPM` };
  return null;
}

function dawAiDurationFromText(text = '', ctx = {}, fallback = 2) {
  const raw = normalizeDawAiText(text);
  const numberPattern = dawAiNumberTokenPattern();
  const barMatch = raw.match(new RegExp(`(${numberPattern})\\s*(?:vollstaendige[nrms]?\\s*)?(?:takt|takte|takten|bar|bars)\\b`));
  if (barMatch) {
    const bars = dawAiNumberFromToken(barMatch[1], null);
    const barLength = dawAiMusicalBarLength(ctx);
    if (bars && barLength?.seconds) {
      return {
        seconds: bars * barLength.seconds,
        unit: 'bars',
        amount: bars,
        source: barLength.source,
      };
    }
    throw new Error('Für Taktangaben brauche ich ein geladenes Beatgrid oder einen BPM-Wert.');
  }
  const minuteMatch = raw.match(new RegExp(`(${numberPattern})\\s*(?:min|minute|minuten)\\b`));
  if (minuteMatch) {
    const minutes = dawAiNumberFromToken(minuteMatch[1], null);
    if (minutes) return { seconds: minutes * 60, unit: 'minutes', amount: minutes, source: 'Zeitangabe' };
  }
  const secondMatch = raw.match(new RegExp(`(${numberPattern})\\s*(?:s|sek|sekunde|sekunden|sec|seconds)\\b`));
  if (secondMatch) {
    const seconds = dawAiNumberFromToken(secondMatch[1], null);
    if (seconds) return { seconds, unit: 'seconds', amount: seconds, source: 'Zeitangabe' };
  }
  return { seconds: fallback, unit: 'seconds', amount: fallback, source: 'Default' };
}

export function dawAiSecondsFromText(text = '', fallback = 2) {
  const raw = String(text || '');
  const minuteMatch = raw.match(/(\d+(?:[,.]\d+)?)\s*(min|minute|minuten)/);
  if (minuteMatch) {
    const minutes = Number(minuteMatch[1].replace(',', '.'));
    if (Number.isFinite(minutes)) return minutes * 60;
  }
  const secondMatch = raw.match(/(\d+(?:[,.]\d+)?)\s*(s|sek|sekunde|sekunden|sec|seconds)/);
  if (secondMatch) {
    const seconds = Number(secondMatch[1].replace(',', '.'));
    if (Number.isFinite(seconds)) return seconds;
  }
  return fallback;
}

function parseDawClipIntent(text, ctx = {}, common = {}, contextClipId = '', isClipContext = false) {
  if (!contextClipId) return null;
  const hasFadeWord = /(fade|einblend|ausblend|weich|sanft|reinblenden|rausblenden)/.test(text);
  const hasFadeIn = /(fade\s*in|fadein|einblend|reinblend|sanft\s*rein|weich\s*rein|anfang\s*weich|vorne\s*weich|einstieg)/.test(text);
  const hasFadeOut = /(fade\s*out|fadeout|ausblend|rausblend|sanft\s*raus|weich\s*raus|ende\s*weich|hinten\s*weich|ausstieg)/.test(text);
  const wantsBothFades = hasFadeWord && (
    (hasFadeIn && hasFadeOut)
    || /fade\s*(?:in\s*)?(?:\/|\+|,|&|\bund\b)\s*(?:fade\s*)?out/.test(text)
    || /ein(?:blenden|blendung)?\s*(?:und|\/|\+|,)\s*aus(?:blenden|blendung)?/.test(text)
    || /anfang\s*(?:und|\/|\+|,)\s*ende.*(?:fade|weich|sanft)/.test(text)
    || /vorne\s*(?:und|\/|\+|,)\s*hinten.*(?:fade|weich|sanft)/.test(text)
    || /(?:rein|vorne|anfang).*(?:und|\/|\+|,).*(?:raus|hinten|ende)/.test(text)
  );
  if (!hasFadeWord && !hasFadeIn && !hasFadeOut) return null;

  const duration = dawAiDurationFromText(text, ctx, 2);
  const edge = wantsBothFades ? 'both' : hasFadeOut && !hasFadeIn ? 'out' : 'in';
  const lengthLabel = duration.unit === 'bars'
    ? `${duration.amount} Takte (${secondsToClock(duration.seconds, true)}, ${duration.source})`
    : secondsToClock(duration.seconds, true);
  const actionLabel = edge === 'both'
    ? `Fade-in und Fade-out für den gewählten Clip auf jeweils ${lengthLabel} setzen.`
    : edge === 'out'
      ? `Fade-out für den gewählten Clip auf ${lengthLabel} setzen.`
      : `Fade-in für den gewählten Clip auf ${lengthLabel} setzen.`;
  return {
    ...common,
    type: 'clip_fade',
    clipId: contextClipId,
    edge,
    seconds: duration.seconds,
    warnings: duration.unit === 'bars' ? [`Taktangabe wurde über ${duration.source} in Sekunden umgerechnet.`] : [],
    aiSource: `${common.aiSource || 'local-daw-command-parser'}:intent`,
    aiInterpretation: actionLabel,
  };
}

function resolveDawAiSection(kind, occurrence, ctx) {
  const { sections: resolvedSections = [], selectedSection = null } = ctx;
  const matches = resolvedSections
    .filter((section) => section.kind === kind)
    .sort((a, b) => safeNumber(a.start) - safeNumber(b.start));
  if (!matches.length) {
    const label = SECTION_KIND_LABELS[kind] || 'Abschnitt';
    throw new Error(`${label} wurde in den vorhandenen Struktursegmenten nicht gefunden.`);
  }
  if (occurrence === 'last') return { section: matches[matches.length - 1], warning: '' };
  if (Number.isFinite(Number(occurrence)) && Number(occurrence) > 0) {
    const section = matches[Number(occurrence) - 1];
    if (!section) throw new Error(`${SECTION_KIND_LABELS[kind] || 'Abschnitt'} ${occurrence} wurde nicht gefunden.`);
    return { section, warning: '' };
  }
  if (selectedSection?.kind === kind) return { section: selectedSection, warning: '' };
  const warning = matches.length > 1
    ? `Mehrere passende Zeitmarken gefunden; ohne genaue Angabe wird ${matches[0].displayLabel} verwendet.`
    : '';
  return { section: matches[0], warning };
}

function selectedSectionInstructionFallback(text, ctx) {
  const resolvedSections = ctx.sections || [];
  const selectedSection = ctx.selectedSection || null;
  const selectedSectionId = ctx.selectedSectionId || '';
  const section = selectedSection || resolvedSections.find((item) => item.id === selectedSectionId);
  if (!section) return null;
  if (/ausgewaehl|ausgewahl|markiert|songteil|abschnitt|bereich/.test(text)) return section;
  return null;
}

export function parseDawAiCommand(prompt, ctx = {}, options = {}) {
  const { selectedClipId = '', selection = null, currentTime = 0, closeGap = true } = ctx;
  const rawPrompt = String(prompt || '').trim();
  const text = normalizeDawAiText(rawPrompt);
  if (!text) throw new Error('Bitte zuerst einen DAW-Befehl eingeben.');
  const contextClipId = options.clipId || selectedClipId;
  const isClipContext = Boolean(options.clipId);
  const common = { aiPrompt: truncateDawAiPrompt(rawPrompt), aiSource: options.source || 'local-daw-command-parser' };

  const preciseBarsMatch = text.match(/(?:erste[nrms]?\s+)?(\d+)\s*(?:vollstaendige[nrms]?\s*)?(?:takt|takte|bars?)/);
  const wantsPreciseSectionDuplicate = /(doppel|verdoppel|wiederhol|kopier|copy|fuege|fuge|erneut|nochmal|noch\s*mal)/.test(text)
    && /(direkt\s*danach|danach\s*(?:erneut|nochmal|noch\s*mal|ein)|bestehende[nrms]?\s+.*songverlauf|nicht\s+mitkopier|uebergangsauftakt|vollstaendige[nrms]?\s*takt|downbeat|beatnet|srt|lyrics)/.test(text);
  const preciseSectionKind = dawAiSectionKindFromText(text);
  if (preciseSectionKind && preciseBarsMatch && wantsPreciseSectionDuplicate) {
    const occurrence = dawAiOccurrenceFromText(text);
    const { section, warning } = resolveDawAiSection(preciseSectionKind, occurrence, ctx);
    return {
      ...common,
      type: 'duplicate_musical_range',
      sectionId: section.id,
      section,
      bars: Math.max(1, Math.min(64, Number(preciseBarsMatch[1]) || 4)),
      anchor: /vollstaendige[nrms]?\s*takt|downbeat|beatnet/.test(text) ? 'first_full_bar' : 'section_start',
      insert: 'after_range',
      ripple: true,
      excludeTransitionPickup: /nicht\s+mitkopier|uebergangsauftakt|auftakt/.test(text),
      warnings: warning ? [warning] : [],
      aiInterpretation: `${section.displayLabel}: erste ${Number(preciseBarsMatch[1]) || 4} vollständige Takte direkt danach duplizieren.`,
    };
  }

  if (/(intro|part|rap\s*part|verse|strophe|bridge|outro|hook|chorus|refrain).*(laenger|langer|verlaenger|erweitern|hinzufueg|hinzufug|fuege|fuge|neu|dritter|dritten|16\s*bars|16\s*takte|sechzehn)/.test(text)) {
    return {
      ...common,
      uiAction: 'needs_generation_workflow',
      aiInterpretation: 'Dieser Wunsch braucht neue Audio-Erzeugung statt nur Timeline-Schnitt. Der Befehl wurde als Planungswunsch erkannt, aber nicht blind angewendet.',
    };
  }

  if (/(luecke|lucke)[n]?\s*(schliessen|schliesse|schliess|entfernen)|alle\s*(luecken|lucken)|gap\s*close/.test(text)) {
    return { ...common, type: 'gap_close', aiInterpretation: 'Alle Timeline-Lücken pro Spur schließen.' };
  }

  const clipIntent = parseDawClipIntent(text, ctx, common, contextClipId, isClipContext);
  if (clipIntent) return clipIntent;

  if (contextClipId) {
    const requestedSeconds = dawAiSecondsFromText(text, 2);
    const explicitDb = dawAiFirstNumber(text, null);
    if (/(fade\s*in|fadein|einblend|sanft\s*rein)/.test(text)) {
      return { ...common, type: 'clip_fade', clipId: contextClipId, edge: 'in', seconds: requestedSeconds, aiInterpretation: `Fade-in für den gewählten Clip auf ${secondsToClock(requestedSeconds, true)} setzen.` };
    }
    if (/(fade\s*out|fadeout|ausblend|sanft\s*raus)/.test(text)) {
      return { ...common, type: 'clip_fade', clipId: contextClipId, edge: 'out', seconds: requestedSeconds, aiInterpretation: `Fade-out für den gewählten Clip auf ${secondsToClock(requestedSeconds, true)} setzen.` };
    }
    if (/(fade|einblenden|ausblenden)/.test(text)) {
      return { ...common, type: 'clip_fade', clipId: contextClipId, edge: 'both', seconds: requestedSeconds, aiInterpretation: `Fade-in und Fade-out für den gewählten Clip auf ${secondsToClock(requestedSeconds, true)} setzen.` };
    }
    if (/(leiser|senk|reduzier|weniger\s*laut|runter|absenken)/.test(text) && /(laut|volume|gain|pegel|db|dezibel|leiser)/.test(text)) {
      const amount = Math.abs(Number.isFinite(explicitDb) ? explicitDb : 3);
      return { ...common, type: 'clip_gain', clipId: contextClipId, gainDelta: -amount, aiInterpretation: `Gewählten Clip um ${amount} dB leiser machen.` };
    }
    if (/(lauter|erhoeh|erhohe|hoch|mehr\s*laut|boost)/.test(text) && /(laut|volume|gain|pegel|db|dezibel|lauter)/.test(text)) {
      const amount = Math.abs(Number.isFinite(explicitDb) ? explicitDb : 3);
      return { ...common, type: 'clip_gain', clipId: contextClipId, gainDelta: amount, aiInterpretation: `Gewählten Clip um ${amount} dB lauter machen.` };
    }
    if (/(gain|pegel|lautstaerke|lautstarke|volume|db|dezibel)/.test(text) && Number.isFinite(explicitDb)) {
      return { ...common, type: 'clip_gain', clipId: contextClipId, gainDb: explicitDb, aiInterpretation: `Gewählten Clip auf ${explicitDb} dB setzen.` };
    }
    if (/(anfang|start|intro|vorne)/.test(text) && /(kurz|kuerz|trim|abschneid|wegschneid|entfern|weg)/.test(text)) {
      return { ...common, type: 'clip_trim', clipId: contextClipId, edge: 'start', seconds: requestedSeconds, aiInterpretation: `Anfang des gewählten Clips um ${secondsToClock(requestedSeconds, true)} kürzen.` };
    }
    if (/(ende|end|hinten|schluss|outro)/.test(text) && /(kurz|kuerz|trim|abschneid|wegschneid|entfern|weg)/.test(text)) {
      return { ...common, type: 'clip_trim', clipId: contextClipId, edge: 'end', seconds: requestedSeconds, aiInterpretation: `Ende des gewählten Clips um ${secondsToClock(requestedSeconds, true)} kürzen.` };
    }
  }

  const sectionKind = dawAiSectionKindFromText(text);
  if (sectionKind) {
    const occurrence = dawAiOccurrenceFromText(text);
    const { section, warning } = resolveDawAiSection(sectionKind, occurrence, ctx);
    const aiWarnings = warning ? [warning] : [];
    if (/ans?\s*ende|anhaengen|anhaenge|hange|haenge|append|am\s*ende|nach\s*hinten/.test(text)) {
      return { ...common, type: 'section_append_to_end', sectionId: section.id, section, warnings: aiWarnings, aiInterpretation: `${section.displayLabel} ans Arrangement-Ende hängen.` };
    }
    if (/loesch|losch|entfern|wegschneid|schneid.*weg|raus|delete|remove/.test(text)) {
      return { ...common, type: 'section_delete', sectionId: section.id, section, closeGap, warnings: aiWarnings, aiInterpretation: `${section.displayLabel} entfernen${closeGap ? ' und Lücke schließen' : ''}.` };
    }
    if (/doppel|verdoppel|wiederhol|zweimal|2x|nochmal|noch\s*mal|repeat|kopier|copy|setze/.test(text)) {
      return { ...common, type: 'section_duplicate', sectionId: section.id, section, warnings: aiWarnings, aiInterpretation: `${section.displayLabel} direkt hinter dem Original duplizieren.` };
    }
    if (/bereich|markier|waehl|wahl|auswaehl|auswahl/.test(text)) {
      return { ...common, uiAction: 'focus_section', section, aiInterpretation: `${section.displayLabel} als Bereich markieren.` };
    }
    throw new Error('Abschnitt erkannt, aber keine Aktion. Nutze z. B. „doppelt“, „ans Ende“ oder „entfernen“.');
  }

  const fallbackSection = selectedSectionInstructionFallback(text, ctx);
  if (fallbackSection) {
    if (/ans?\s*ende|anhaeng|anhang|append|ende/.test(text)) {
      return { ...common, type: 'section_append_to_end', sectionId: fallbackSection.id, section: fallbackSection, aiInterpretation: `${fallbackSection.displayLabel} ans Arrangement-Ende hängen.` };
    }
    if (/loesch|losch|entfern|delete|remove/.test(text)) {
      return { ...common, type: 'section_delete', sectionId: fallbackSection.id, section: fallbackSection, closeGap, aiInterpretation: `${fallbackSection.displayLabel} entfernen${closeGap ? ' und Lücke schließen' : ''}.` };
    }
    if (/doppel|verdoppel|wiederhol|zweimal|2x|nochmal|duplizier|kopier|copy/.test(text)) {
      return { ...common, type: 'section_duplicate', sectionId: fallbackSection.id, section: fallbackSection, aiInterpretation: `${fallbackSection.displayLabel} direkt hinter dem Original duplizieren.` };
    }
    if (/bereich|markier|waehl|wahl|auswaehl|auswahl/.test(text)) {
      return { ...common, uiAction: 'focus_section', section: fallbackSection, aiInterpretation: `${fallbackSection.displayLabel} als Bereich markieren.` };
    }
  }

  if (/bereich/.test(text) && /entfern|loesch|losch|delete|remove/.test(text)) {
    return { ...common, type: 'range_delete', range: selection, closeGap, aiInterpretation: 'Aktuell markierten Bereich entfernen.' };
  }
  if (/30\s*s|30\s*sek|dreissig/.test(text) && /bereich|markier/.test(text)) {
    return { ...common, uiAction: 'range_30', aiInterpretation: 'Ab Playhead einen 30-Sekunden-Bereich markieren.' };
  }
  if (/schneid|schnitt|split|cut/.test(text)) {
    return { ...common, type: 'clip_split', time: currentTime, clipId: contextClipId, aiInterpretation: `Am Playhead ${secondsToClock(currentTime, true)} schneiden.` };
  }
  if (/duplizier|kopier|copy/.test(text) && /clip|audio|markiert/.test(text)) {
    return { ...common, type: 'clip_duplicate', clipId: contextClipId, aiInterpretation: isClipContext ? 'Gewählten Timeline-Clip duplizieren.' : 'Markierten Clip duplizieren.' };
  }
  if (/loesch|losch|entfern|delete|remove/.test(text) && /clip|audio|markiert/.test(text)) {
    return { ...common, type: 'clip_delete', clipId: contextClipId, aiInterpretation: isClipContext ? 'Gewählten Timeline-Clip löschen.' : 'Markierten Clip löschen.' };
  }
  if (/start/.test(text) && /playhead|slider|cursor|abspielkopf/.test(text)) {
    return { ...common, type: 'clip_align_to_playhead', edge: 'start', clipId: contextClipId, aiInterpretation: 'Clip-Start an Playhead ausrichten.' };
  }
  if (/(ende|end)/.test(text) && /playhead|slider|cursor|abspielkopf/.test(text)) {
    return { ...common, type: 'clip_align_to_playhead', edge: 'end', clipId: contextClipId, aiInterpretation: 'Clip-Ende an Playhead ausrichten.' };
  }
  if (/vorher|vorgaenger|previous/.test(text) && /clip|audio|anschliess|anlegen|snap/.test(text)) {
    return { ...common, type: 'clip_attach_adjacent', direction: 'previous', clipId: contextClipId, aiInterpretation: isClipContext ? 'Gewählten Clip an den vorherigen Clip anschließen.' : 'Markierten Clip an den vorherigen Clip anschließen.' };
  }
  if (/naechst|nachst|next/.test(text) && /clip|audio|anschliess|anlegen|snap/.test(text)) {
    return { ...common, type: 'clip_attach_adjacent', direction: 'next', clipId: contextClipId, aiInterpretation: isClipContext ? 'Gewählten Clip an den nächsten Clip anschließen.' : 'Markierten Clip an den nächsten Clip anschließen.' };
  }

  if (isClipContext && /duplizier|kopier|copy|wiederhol|nochmal|noch\s*mal/.test(text)) {
    return { ...common, type: 'clip_duplicate', clipId: contextClipId, aiInterpretation: 'Gewählten Timeline-Clip duplizieren.' };
  }
  if (isClipContext && /loesch|losch|entfern|delete|remove|weg/.test(text)) {
    return { ...common, type: 'clip_delete', clipId: contextClipId, aiInterpretation: 'Gewählten Timeline-Clip löschen.' };
  }
  if (isClipContext && /schneid|schnitt|split|cut/.test(text)) {
    return { ...common, type: 'clip_split', time: currentTime, clipId: contextClipId, aiInterpretation: `Gewählten Timeline-Clip am Playhead ${secondsToClock(currentTime, true)} schneiden.` };
  }

  throw new Error('Befehl nicht eindeutig. Beispiele: „Fade-in 3s“, „kürze Anfang um 8s“, „dupliziere diesen Clip“, „Schließe alle Lücken“.');
}
