import React, { useState } from 'react';
import { FileAudio2, ImageDown, Link2, RefreshCw, UploadCloud } from 'lucide-react';
import { api } from '../api/client.js';
import { SectionHeader } from '../components/SectionHeader.jsx';
import { useI18n } from '../i18n/I18nContext.jsx';

const SUNO_TASK_TYPE_OPTIONS = [
  ['auto', 'Auto erkennen'],
  ['generate_music', 'Musik / Audio'],
  ['extend_music', 'Musik erweitern'],
  ['upload_and_cover', 'Cover Song'],
  ['upload_and_extend', 'Upload erweitern'],
  ['add_instrumental', 'Instrumental hinzufügen'],
  ['add_vocals', 'Vocals hinzufügen'],
  ['generate_mashup', 'Mashup'],
  ['generate_sounds', 'Sounds'],
  ['create_cover', 'Cover-Bild'],
  ['create_video', 'Music Video / MP4'],
  ['separate', 'Stems / Separate'],
  ['convert_to_wav', 'WAV-Konvertierung'],
  ['generate_midi', 'MIDI'],
  ['generate_lyrics', 'Lyrics'],
  ['create_custom_voice', 'Custom Voice']
];

export function ImportPage({ notify, onReload, onOpenAsset }) {
  const { t } = useI18n();
  const [importingTask, setImportingTask] = useState(false);
  const [cachingCovers, setCachingCovers] = useState(false);
  const [manualImportBusy, setManualImportBusy] = useState(false);
  const [importPayload, setImportPayload] = useState({ task_id: '', task_type: 'auto', title: '', prompt: '', style: '', model: '', cache_audio: true, cache_video: true, generate_srt: false, generate_stems: false });
  const [batchImporting, setBatchImporting] = useState(false);
  const [batchImportPayload, setBatchImportPayload] = useState({ task_ids: '', task_type: 'auto', cache_audio: true, cache_video: true, title_prefix: '', generate_srt: false, generate_stems: false });
  const [songImporting, setSongImporting] = useState(false);
  const [songImportPayload, setSongImportPayload] = useState({ song_id: '', cache_audio: true, cache_cover: true, import_video_url: true, overwrite_existing: false, generate_srt: false, generate_stems: false });
  const [songBatchImporting, setSongBatchImporting] = useState(false);
  const [songBatchImportPayload, setSongBatchImportPayload] = useState({ song_ids: '', cache_audio: true, cache_cover: true, import_video_url: true, overwrite_existing: false, generate_srt: false, generate_stems: false });

  function updateImportPayload(key, value) {
    setImportPayload((current) => ({ ...current, [key]: value }));
  }

  function updateBatchImportPayload(key, value) {
    setBatchImportPayload((current) => ({ ...current, [key]: value }));
  }

  function updateSongImportPayload(key, value) {
    setSongImportPayload((current) => ({ ...current, [key]: value }));
  }

  function updateSongBatchImportPayload(key, value) {
    setSongBatchImportPayload((current) => ({ ...current, [key]: value }));
  }

  async function cacheMissingCovers() {
    setCachingCovers(true);
    try {
      const result = await api.archive.cacheMissingCovers();
      notify?.(result?.message || t('status.messages.coversCached', 'Cover wurden lokal gesichert.'), 'success');
      await onReload?.();
    } catch (err) {
      notify?.(err?.message || t('status.messages.coversCacheFailed', 'Cover konnten nicht lokal gesichert werden.'), 'error');
    } finally {
      setCachingCovers(false);
    }
  }

  async function importExternalTask(event) {
    event.preventDefault();
    const taskId = importPayload.task_id.trim();
    if (!taskId) return notify?.(t('status.messages.taskIdMissing', 'Bitte eine Suno Task-ID eintragen.'), 'error');

    setImportingTask(true);
    try {
      const payload = {
        task_id: taskId,
        task_type: importPayload.task_type || 'auto',
        title: importPayload.title.trim() || undefined,
        prompt: importPayload.prompt.trim() || undefined,
        style: importPayload.style.trim() || undefined,
        model: importPayload.model.trim() || undefined,
        cache_audio: Boolean(importPayload.cache_audio),
        cache_video: Boolean(importPayload.cache_video),
        generate_srt: Boolean(importPayload.generate_srt),
        generate_stems: Boolean(importPayload.generate_stems)
      };
      const result = await api.music.importFromSuno(payload);
      if (result?.already_imported || result?.import_status === 'already_imported') {
        notify?.(result?.import_message || t('status.messages.taskAlreadyImported', 'Dieser Suno-Task wurde bereits importiert. Es wurde nichts doppelt erstellt.'), 'info');
      } else {
        notify?.(result?.import_message || t('status.messages.taskImported', 'Suno-Task importiert: {{status}}', { status: result?.status || 'OK' }), 'success');
        setImportPayload((current) => ({ ...current, task_id: '', title: '', prompt: '', style: '', model: '' }));
      }
      await onReload?.();
    } catch (err) {
      notify?.(err?.message || t('status.messages.taskImportFailed', 'Suno-Task konnte nicht importiert werden.'), 'error');
    } finally {
      setImportingTask(false);
    }
  }

  async function importExternalTasksBatch(event) {
    event.preventDefault();
    if (!batchImportPayload.task_ids.trim()) return notify?.(t('status.messages.batchTaskIdsMissing', 'Bitte mindestens eine Task-ID eintragen.'), 'error');
    setBatchImporting(true);
    try {
      const result = await api.music.importBatchFromSuno({
        ...batchImportPayload,
        task_type: batchImportPayload.task_type || 'auto',
        cache_audio: Boolean(batchImportPayload.cache_audio),
        cache_video: Boolean(batchImportPayload.cache_video),
        generate_srt: Boolean(batchImportPayload.generate_srt),
        generate_stems: Boolean(batchImportPayload.generate_stems)
      });
      const summary = result?.summary || {};
      if (result?.queued) {
        notify?.(result?.message || t('status.messages.batchImportStarted', 'SunoAPI.org Task-Batchimport wurde gestartet ({{count}} Einträge).', { count: summary.total || 0 }), 'info');
        setBatchImportPayload((current) => ({ ...current, task_ids: '', title_prefix: '' }));
        await onReload?.();
        window.setTimeout(() => onReload?.(), 1500);
        return;
      }
      notify?.(result?.message || t('status.messages.importSummary', '{{imported}} importiert, {{existing}} bereits vorhanden, {{failed}} Fehler.', { imported: summary.imported || 0, existing: summary.already_imported || 0, failed: summary.failed || 0 }), summary.failed ? 'info' : 'success');
      if (!summary.failed) setBatchImportPayload((current) => ({ ...current, task_ids: '', title_prefix: '' }));
      await onReload?.();
    } catch (err) {
      notify?.(err?.message || t('status.messages.batchImportFailed', 'Batch-Import fehlgeschlagen.'), 'error');
    } finally {
      setBatchImporting(false);
    }
  }

  async function importPublicSunoSong(event) {
    event.preventDefault();
    const songId = songImportPayload.song_id.trim();
    if (!songId) return notify?.(t('status.messages.songIdMissing', 'Bitte eine Suno Song-ID oder Suno-URL eintragen.'), 'error');

    setSongImporting(true);
    try {
      const payload = {
        song_id: songId,
        cache_audio: Boolean(songImportPayload.cache_audio),
        cache_cover: Boolean(songImportPayload.cache_cover),
        import_video_url: Boolean(songImportPayload.import_video_url),
        overwrite_existing: Boolean(songImportPayload.overwrite_existing),
        generate_srt: Boolean(songImportPayload.generate_srt),
        generate_stems: Boolean(songImportPayload.generate_stems)
      };
      const result = await api.music.importSongFromSuno(payload);
      const message = result?.message || (result?.already_imported ? t('status.messages.songAlreadyImported', 'Suno-Song wurde bereits importiert.') : t('status.messages.songImported', 'Suno-Song wurde importiert.'));
      notify?.(message, result?.already_imported ? 'info' : 'success');
      if (!result?.already_imported || songImportPayload.overwrite_existing) {
        setSongImportPayload((current) => ({ ...current, song_id: '', overwrite_existing: false }));
      }
      await onReload?.();
    } catch (err) {
      notify?.(err?.message || t('status.messages.songImportFailed', 'Suno-Song konnte nicht importiert werden.'), 'error');
    } finally {
      setSongImporting(false);
    }
  }

  async function importPublicSunoSongsBatch(event) {
    event.preventDefault();
    if (!songBatchImportPayload.song_ids.trim()) return notify?.(t('status.messages.songBatchMissing', 'Bitte mindestens eine Suno Song-ID oder URL eintragen.'), 'error');
    setSongBatchImporting(true);
    try {
      const result = await api.music.importSongBatchFromSuno(songBatchImportPayload);
      const summary = result?.summary || {};
      if (result?.queued) {
        notify?.(result?.message || t('status.messages.songBatchStarted', 'Suno.com Song-Batchimport wurde gestartet ({{count}} Einträge).', { count: summary.total || 0 }), 'info');
        setSongBatchImportPayload((current) => ({ ...current, song_ids: '', overwrite_existing: false }));
        await onReload?.();
        window.setTimeout(() => onReload?.(), 1500);
        return;
      }
      notify?.(result?.message || t('status.messages.importSummary', '{{imported}} importiert, {{existing}} bereits vorhanden, {{failed}} Fehler.', { imported: summary.imported || 0, existing: summary.already_imported || 0, failed: summary.failed || 0 }), summary.failed ? 'info' : 'success');
      if (!summary.failed) setSongBatchImportPayload((current) => ({ ...current, song_ids: '', overwrite_existing: false }));
      await onReload?.();
    } catch (err) {
      notify?.(err?.message || t('status.messages.songBatchFailed', 'Suno-Song-Batch konnte nicht importiert werden.'), 'error');
    } finally {
      setSongBatchImporting(false);
    }
  }

  async function handleManualAudioImport(event) {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const audioFile = formData.get('audio');
    const title = String(formData.get('title') || '').trim();
    if (!audioFile || typeof audioFile === 'string' || !audioFile.size) {
      return notify?.(t('library.messages.selectAudioFile', 'Bitte eine Audiodatei auswählen.'), 'error');
    }
    if (!title) return notify?.(t('library.messages.importTitleRequired', 'Bitte einen Titel für den Import angeben.'), 'error');
    setManualImportBusy(true);
    try {
      const result = await api.archive.importManualAudio(formData);
      notify?.(result?.message || t('library.messages.audioImported', 'Audio wurde importiert.'), 'success');
      form.reset();
      await onReload?.();
      if (result?.audio_asset_id) onOpenAsset?.(result.audio_asset_id);
    } catch (err) {
      notify?.(err?.message || t('library.messages.audioImportFailed', 'Audio-Import fehlgeschlagen.'), 'error');
    } finally {
      setManualImportBusy(false);
    }
  }

  return (
    <section className="page stack import-page">
      <SectionHeader eyebrow={t('imports.eyebrow', 'Import Center')} title={t('imports.title', 'Audio importieren')}>
        <button type="button" onClick={cacheMissingCovers} disabled={cachingCovers}>
          <ImageDown size={16} className={cachingCovers ? 'spin-icon' : ''} />
          {cachingCovers ? t('status.import.cachingCovers', 'Sichere Cover…') : t('status.import.cacheMissingCovers', 'Fehlende Cover lokal sichern')}
        </button>
      </SectionHeader>

      <section className="panel stack slim-panel">
        <div>
          <p className="eyebrow"><RefreshCw size={14} /> {t('status.import.eyebrow', 'Backfill / Import')}</p>
          <h2>{t('status.import.title', 'Externen SunoAPI.org-Task importieren')}</h2>
          <p className="muted">{t('status.import.text', 'SunoAPI.org-Task-ID eintragen. Die App erkennt den Task-Typ automatisch oder nutzt die Auswahl. Audio wird als AudioAsset importiert, MP4-Videos werden separat als VideoAsset an vorhandene AudioAssets gebunden.')}</p>
        </div>
        <form className="form-grid" onSubmit={importExternalTask}>
          <label className="wide">Task-ID
            <input value={importPayload.task_id} onChange={(event) => updateImportPayload('task_id', event.target.value)} placeholder={t('status.import.taskIdPlaceholder', 'z. B. b762e25da0e27d420535ae1068504ecd')} />
          </label>
          <label>{t('status.import.taskType', 'Task-Typ')}
            <select value={importPayload.task_type} onChange={(event) => updateImportPayload('task_type', event.target.value)}>
              {SUNO_TASK_TYPE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>{t('status.import.titleOptional', 'Titel optional')}
            <input value={importPayload.title} onChange={(event) => updateImportPayload('title', event.target.value)} placeholder={t('status.import.localDisplayName', 'Lokaler Anzeigename')} />
          </label>
          <label>{t('status.import.modelOptional', 'Modell optional')}
            <input value={importPayload.model} onChange={(event) => updateImportPayload('model', event.target.value)} placeholder={t('status.import.modelPlaceholder', 'z. B. V5_5')} />
          </label>
          <label>{t('status.import.promptOptional', 'Prompt / Lyrics optional')}
            <textarea rows={3} value={importPayload.prompt} onChange={(event) => updateImportPayload('prompt', event.target.value)} placeholder={t('status.import.promptPlaceholder', 'Nur falls lokal ergänzt werden soll…')} />
          </label>
          <label>{t('status.import.styleOptional', 'Style optional')}
            <textarea rows={3} value={importPayload.style} onChange={(event) => updateImportPayload('style', event.target.value)} placeholder={t('status.import.stylePlaceholder', 'Style lokal ergänzen…')} />
          </label>
          <label className="check-row"><input type="checkbox" checked={importPayload.cache_audio} onChange={(event) => updateImportPayload('cache_audio', event.target.checked)} /> {t('status.import.cacheAudioIfAvailable', 'Audio lokal speichern, falls URL verfügbar')}</label>
          <label className="check-row"><input type="checkbox" checked={importPayload.cache_video} onChange={(event) => updateImportPayload('cache_video', event.target.checked)} /> {t('status.import.cacheVideoIfAvailable', 'MP4 lokal speichern, falls videoUrl verfügbar')}</label>
          <label className="check-row"><input type="checkbox" checked={importPayload.generate_srt} onChange={(event) => updateImportPayload('generate_srt', event.target.checked)} /> {t('status.import.generateSrtAfterImport', 'Nach Import SRT erzeugen')}</label>
          <label className="check-row"><input type="checkbox" checked={importPayload.generate_stems} onChange={(event) => updateImportPayload('generate_stems', event.target.checked)} /> {t('status.import.generateStemsAfterImport', 'Nach Import Stems erzeugen')}</label>
          <div className="form-actions">
            <button className="primary" type="submit" disabled={importingTask}><RefreshCw size={16} className={importingTask ? 'spin-icon' : ''} /> {importingTask ? t('status.import.importing', 'Importiere…') : t('status.import.importTask', 'Task importieren')}</button>
          </div>
        </form>

        <details className="batch-import-box">
          <summary>{t('status.import.batchSummary', 'Mehrere SunoAPI.org Task-IDs als Batch importieren')}</summary>
          <form className="form-grid" onSubmit={importExternalTasksBatch}>
            <label className="wide">{t('status.import.taskIdsOnePerLine', 'Task-IDs, eine pro Zeile')}
              <textarea rows={5} value={batchImportPayload.task_ids} onChange={(event) => updateBatchImportPayload('task_ids', event.target.value)} placeholder={t('status.import.taskIdsPlaceholder', 'Task-ID 1\nTask-ID 2\nTask-ID 3')} />
            </label>
            <label>{t('status.import.taskType', 'Task-Typ')}
              <select value={batchImportPayload.task_type} onChange={(event) => updateBatchImportPayload('task_type', event.target.value)}>
                {SUNO_TASK_TYPE_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
              </select>
            </label>
            <label>{t('status.import.titlePrefixOptional', 'Titel-Präfix optional')}
              <input value={batchImportPayload.title_prefix} onChange={(event) => updateBatchImportPayload('title_prefix', event.target.value)} placeholder={t('status.import.titlePrefixPlaceholder', 'z. B. Backfill')} />
            </label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.cache_audio} onChange={(event) => updateBatchImportPayload('cache_audio', event.target.checked)} /> {t('status.import.cacheAudio', 'Audio lokal speichern')}</label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.cache_video} onChange={(event) => updateBatchImportPayload('cache_video', event.target.checked)} /> {t('status.import.cacheVideo', 'MP4 lokal speichern')}</label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.generate_srt} onChange={(event) => updateBatchImportPayload('generate_srt', event.target.checked)} /> {t('status.import.generateSrtAfterImport', 'Nach Import SRT erzeugen')}</label>
            <label className="check-row"><input type="checkbox" checked={batchImportPayload.generate_stems} onChange={(event) => updateBatchImportPayload('generate_stems', event.target.checked)} /> {t('status.import.generateStemsAfterImport', 'Nach Import Stems erzeugen')}</label>
            <div className="form-actions"><button className="primary" type="submit" disabled={batchImporting}><RefreshCw size={16} className={batchImporting ? 'spin-icon' : ''} /> {batchImporting ? t('status.import.importing', 'Importiere…') : t('status.import.importBatch', 'Batch importieren')}</button></div>
          </form>
        </details>
      </section>

      <section className="panel stack slim-panel">
        <div>
          <p className="eyebrow"><Link2 size={14} /> {t('status.songImport.eyebrow', 'Öffentlicher Suno.com Song-Import')}</p>
          <h2>{t('status.songImport.title', 'Öffentliche Suno.com Song-ID / URL importieren')}</h2>
          <p className="muted">{t('status.songImport.text', 'Öffentliche Suno-Song-URL oder Clip-ID importieren. Lokale Funktionen wie Playback, Download, Lyrics und SRT bleiben aktiv; SunoAPI.org-Folgeaktionen werden für diese Imports deaktiviert.')}</p>
        </div>
        <form className="form-grid status-song-import-grid" onSubmit={importPublicSunoSong}>
          <label className="wide">{t('status.songImport.songIdOrUrl', 'Suno Song-ID oder URL')}
            <input value={songImportPayload.song_id} onChange={(event) => updateSongImportPayload('song_id', event.target.value)} placeholder={t('status.songImport.songIdPlaceholder', 'z. B. https://suno.com/song/96fdbd12-4ea1-41b4-a132-4b731ec6594e')} />
          </label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.cache_audio} onChange={(event) => updateSongImportPayload('cache_audio', event.target.checked)} /> {t('status.songImport.cacheAudio', 'Audio lokal speichern')}</label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.cache_cover} onChange={(event) => updateSongImportPayload('cache_cover', event.target.checked)} /> {t('status.songImport.cacheCover', 'Cover lokal speichern')}</label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.import_video_url} onChange={(event) => updateSongImportPayload('import_video_url', event.target.checked)} /> {t('status.songImport.importVideoUrl', 'Video-URL übernehmen')}</label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.overwrite_existing} onChange={(event) => updateSongImportPayload('overwrite_existing', event.target.checked)} /> {t('status.songImport.overwriteExisting', 'Vorhandenen Import aktualisieren')}</label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.generate_srt} onChange={(event) => updateSongImportPayload('generate_srt', event.target.checked)} /> {t('status.import.generateSrtAfterImport', 'Nach Import SRT erzeugen')}</label>
          <label className="check-row"><input type="checkbox" checked={songImportPayload.generate_stems} onChange={(event) => updateSongImportPayload('generate_stems', event.target.checked)} /> {t('status.import.generateStemsAfterImport', 'Nach Import Stems erzeugen')}</label>
          <div className="form-actions">
            <button className="primary" type="submit" disabled={songImporting}><RefreshCw size={16} className={songImporting ? 'spin-icon' : ''} /> {songImporting ? t('status.import.importing', 'Importiere…') : t('status.songImport.importSong', 'Song importieren')}</button>
          </div>
        </form>

        <details className="batch-import-box">
          <summary>{t('status.songImport.batchSummary', 'Mehrere öffentliche Suno.com Song-IDs / URLs als Batch importieren')}</summary>
          <form className="form-grid" onSubmit={importPublicSunoSongsBatch}>
            <label className="wide">{t('status.songImport.idsOrUrlsOnePerLine', 'Suno Song-IDs oder URLs, eine pro Zeile')}
              <textarea rows={5} value={songBatchImportPayload.song_ids} onChange={(event) => updateSongBatchImportPayload('song_ids', event.target.value)} placeholder={t('status.songImport.idsPlaceholder', 'https://suno.com/song/96fdbd12-4ea1-41b4-a132-4b731ec6594e\n96fdbd12-4ea1-41b4-a132-4b731ec6594e')} />
            </label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.cache_audio} onChange={(event) => updateSongBatchImportPayload('cache_audio', event.target.checked)} /> {t('status.songImport.cacheAudio', 'Audio lokal speichern')}</label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.cache_cover} onChange={(event) => updateSongBatchImportPayload('cache_cover', event.target.checked)} /> {t('status.songImport.cacheCover', 'Cover lokal speichern')}</label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.import_video_url} onChange={(event) => updateSongBatchImportPayload('import_video_url', event.target.checked)} /> {t('status.songImport.importVideoUrl', 'Video-URL übernehmen')}</label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.overwrite_existing} onChange={(event) => updateSongBatchImportPayload('overwrite_existing', event.target.checked)} /> {t('status.songImport.overwriteExistingBatch', 'Vorhandene Imports aktualisieren')}</label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.generate_srt} onChange={(event) => updateSongBatchImportPayload('generate_srt', event.target.checked)} /> {t('status.import.generateSrtAfterImport', 'Nach Import SRT erzeugen')}</label>
            <label className="check-row"><input type="checkbox" checked={songBatchImportPayload.generate_stems} onChange={(event) => updateSongBatchImportPayload('generate_stems', event.target.checked)} /> {t('status.import.generateStemsAfterImport', 'Nach Import Stems erzeugen')}</label>
            <div className="form-actions"><button className="primary" type="submit" disabled={songBatchImporting}><RefreshCw size={16} className={songBatchImporting ? 'spin-icon' : ''} /> {songBatchImporting ? t('status.import.importing', 'Importiere…') : t('status.songImport.importBatch', 'Song-Batch importieren')}</button></div>
          </form>
        </details>
      </section>

      <section className="panel stack slim-panel">
        <div>
          <p className="eyebrow"><FileAudio2 size={14} /> {t('library.manualImport.title', 'Audio manuell erfassen')}</p>
          <h2>{t('imports.local.title', 'Lokale Audiodatei importieren')}</h2>
          <p className="muted">{t('library.manualImport.fullSongText', 'Die Datei wird unter dem Audio-Storage gespeichert und als normales AudioAsset mit Song, Projekt, Lyrics, Style und Metadaten angelegt. Danach funktionieren Player, SRT-Erzeugung, Editor, ZIP-Export und Einzelinhalte wie bei Suno-generierten Songs.')}</p>
        </div>
        <form className="form-grid manual-audio-import-form" onSubmit={handleManualAudioImport}>
          <label className="wide">{t('library.manualImport.audioFile', 'Audiodatei')}
            <input name="audio" type="file" accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac" required />
          </label>
          <label>{t('common.title', 'Titel')}
            <input name="title" placeholder={t('library.manualImport.titlePlaceholder', 'z. B. Kalte Hände')} required />
          </label>
          <label>{t('library.manualImport.projectNameOptional', 'Projektname optional')}
            <input name="project_title" placeholder={t('library.manualImport.projectPlaceholder', 'leer = Titel')} />
          </label>
          <label>{t('library.manualImport.language', 'Sprache')}
            <select name="language" defaultValue="de">
              <option value="de">{t('language.label', 'Deutsch')}</option>
              <option value="en">English</option>
              <option value="auto">Auto</option>
            </select>
          </label>
          <label>{t('library.manualImport.coverOptional', 'Cover optional')}
            <input name="cover" type="file" accept="image/*,.jpg,.jpeg,.png,.webp,.gif,.avif" />
          </label>
          <label className="wide">Songtext / Lyrics
            <textarea name="lyrics" rows={10} placeholder={t('library.manualImport.lyricsPlaceholder', 'Songtext einfügen. Dieser Text wird später für SRT als Source of Truth verwendet.')} />
          </label>
          <label className="wide">Style
            <textarea name="style" rows={4} placeholder={t('library.manualImport.stylePlaceholder', 'z. B. German emotional boom bap, male rap vocals, dark piano...')} />
          </label>
          <label className="wide">{t('library.manualImport.promptOptional', 'Prompt / Beschreibung optional')}
            <textarea name="prompt" rows={4} placeholder={t('library.manualImport.promptPlaceholder', 'Optionaler Prompt. Falls leer, wird der Songtext auch als Prompt gespeichert.')} />
          </label>
          <label className="wide">{t('library.manualImport.notesOptional', 'Notizen optional')}
            <textarea name="notes" rows={3} placeholder={t('library.manualImport.notesPlaceholder', 'Interne Notizen zum Import.')} />
          </label>
          <div className="wide button-row wrap right">
            <button type="reset" disabled={manualImportBusy}>{t('common.clear', 'Leeren')}</button>
            <button className="primary" type="submit" disabled={manualImportBusy}><UploadCloud size={16} /> {manualImportBusy ? t('library.manualImport.importing', 'Importiere…') : t('library.actions.importAudio', 'Audio importieren')}</button>
          </div>
        </form>
      </section>
    </section>
  );
}
