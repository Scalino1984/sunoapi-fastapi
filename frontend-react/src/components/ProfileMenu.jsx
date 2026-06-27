import React, { useEffect, useRef, useState } from 'react';
import { CheckCircle2, KeyRound, LogOut, Mic2, PlusCircle, RefreshCw, Save, Trash2, UserRound, X } from 'lucide-react';
import { api } from '../api/client.js';

function displayName(user) {
  return user?.nickname || user?.email?.split('@')[0] || 'Benutzer';
}

function voiceLabel(voice) {
  const nickname = voice?.nickname || voice?.name || 'Voice';
  const voiceId = voice?.voice_id || voice?.persona_id || '';
  const shortId = String(voiceId).slice(0, 12);
  return `${nickname}${shortId ? ` · ${shortId}…` : ''}`;
}

function uploadLabel(file) {
  if (!file) return 'Upload wählen…';
  return file.original_name || file.source_url || file.uploaded_url || `Upload #${file.id}`;
}

function extractTaskId(value) {
  return value?.task_id || value?.taskId || value?.data?.taskId || value?.data?.task_id || '';
}

function extractVoiceId(value) {
  return value?.voice_id || value?.voiceId || value?.data?.voiceId || value?.data?.voice_id || '';
}

function extractValidateInfo(value) {
  return value?.validateInfo || value?.validate_info || value?.data?.validateInfo || value?.data?.validate_info || '';
}

export function ProfileMenu({ user, voices = [], uploadedFiles = [], onUserUpdate, onLogout, onRefresh, notify }) {
  const [open, setOpen] = useState(false);
  const [nickname, setNickname] = useState(user?.nickname || '');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [voiceNickname, setVoiceNickname] = useState('');
  const [voiceId, setVoiceId] = useState('');
  const [voiceTaskId, setVoiceTaskId] = useState('');
  const [voiceDescription, setVoiceDescription] = useState('');
  const [voiceSourceUrl, setVoiceSourceUrl] = useState('');
  const [voiceSourceUploadId, setVoiceSourceUploadId] = useState('');
  const [voiceVerifyUrl, setVoiceVerifyUrl] = useState('');
  const [voiceVerifyUploadId, setVoiceVerifyUploadId] = useState('');
  const [voiceStartS, setVoiceStartS] = useState('0');
  const [voiceEndS, setVoiceEndS] = useState('15');
  const [voiceLanguage, setVoiceLanguage] = useState('de');
  const [voiceValidationTaskId, setVoiceValidationTaskId] = useState('');
  const [voiceCreationTaskId, setVoiceCreationTaskId] = useState('');
  const [voiceValidationInfo, setVoiceValidationInfo] = useState(null);
  const [voiceRecordInfo, setVoiceRecordInfo] = useState(null);
  const [singerSkillLevel, setSingerSkillLevel] = useState('beginner');
  const [saving, setSaving] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    setNickname(user?.nickname || '');
  }, [user?.nickname]);

  useEffect(() => {
    function onDocumentClick(event) {
      if (!open) return;
      if (menuRef.current && !menuRef.current.contains(event.target)) setOpen(false);
    }
    document.addEventListener('mousedown', onDocumentClick);
    return () => document.removeEventListener('mousedown', onDocumentClick);
  }, [open]);

  useEffect(() => {
    function onEscape(event) {
      if (!open || event.key !== 'Escape') return;
      event.preventDefault();
      setOpen(false);
    }
    document.addEventListener('keydown', onEscape);
    return () => document.removeEventListener('keydown', onEscape);
  }, [open]);

  async function saveProfile(event) {
    event.preventDefault();
    setSaving(true);
    try {
      const updated = await api.auth.updateProfile({ nickname: nickname.trim() || null });
      onUserUpdate(updated);
      notify?.('Profil wurde gespeichert.', 'success');
    } catch (err) {
      notify?.(err.message || 'Profil konnte nicht gespeichert werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function changePassword(event) {
    event.preventDefault();
    if (!currentPassword || !newPassword) return notify?.('Bitte aktuelles und neues Passwort eingeben.', 'error');
    setSaving(true);
    try {
      await api.auth.changePassword({ current_password: currentPassword, new_password: newPassword });
      setCurrentPassword('');
      setNewPassword('');
      notify?.('Passwort wurde geändert.', 'success');
    } catch (err) {
      notify?.(err.message || 'Passwort konnte nicht geändert werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function saveVoice(event) {
    event.preventDefault();
    const cleanNickname = voiceNickname.trim();
    const cleanVoiceId = voiceId.trim();
    const cleanTaskId = voiceTaskId.trim();
    if (!cleanNickname || !cleanVoiceId) {
      notify?.('Bitte Spitzname und Voice-ID eintragen.', 'error');
      return;
    }
    setSaving(true);
    try {
      await api.music.createVoice({
        nickname: cleanNickname,
        voice_id: cleanVoiceId,
        task_id: cleanTaskId || cleanVoiceId,
        description: voiceDescription.trim() || null
      });
      setVoiceNickname('');
      setVoiceId('');
      setVoiceTaskId('');
      setVoiceDescription('');
      await onRefresh?.({ silent: true });
      notify?.(`Voice „${cleanNickname}“ wurde gespeichert.`, 'success');
    } catch (err) {
      notify?.(err.message || 'Voice konnte nicht gespeichert werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function deleteVoice(localVoiceId) {
    const voice = voices.find((item) => String(item.id) === String(localVoiceId));
    const label = voice?.nickname || voice?.name || 'Voice';
    if (!window.confirm(`Voice „${label}“ wirklich entfernen?`)) return;
    setSaving(true);
    try {
      await api.music.deleteVoice(localVoiceId);
      await onRefresh?.({ silent: true });
      notify?.(`Voice „${label}“ wurde entfernt.`, 'success');
    } catch (err) {
      notify?.(err.message || 'Voice konnte nicht entfernt werden.', 'error');
    } finally {
      setSaving(false);
    }
  }


  function selectedUploadUrl(uploadId) {
    const file = uploadedFiles.find((item) => String(item.id) === String(uploadId));
    return file?.uploaded_url || '';
  }

  async function startVoiceValidation(event) {
    event.preventDefault();
    const sourceUrl = voiceSourceUrl.trim() || selectedUploadUrl(voiceSourceUploadId);
    if (!sourceUrl) return notify?.('Bitte eine Voice-URL oder Upload-Datei als Quelle auswählen.', 'error');
    setSaving(true);
    try {
      const task = await api.music.voiceValidate({
        voice_url: sourceUrl,
        vocal_start_s: Number(voiceStartS || 0),
        vocal_end_s: Number(voiceEndS || 15),
        language: voiceLanguage || 'de'
      });
      const taskId = extractTaskId(task);
      setVoiceValidationTaskId(taskId);
      notify?.('Validierungsphrase wurde angefordert. Danach Phrase abrufen.', 'success');
      await onRefresh?.({ silent: true });
    } catch (err) {
      notify?.(err.message || 'Validierungsphrase konnte nicht gestartet werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function loadVoiceValidationInfo() {
    const taskId = voiceValidationTaskId.trim();
    if (!taskId) return notify?.('Bitte zuerst eine Validation Task-ID eintragen.', 'error');
    setSaving(true);
    try {
      const info = await api.music.voiceValidateInfo(taskId);
      setVoiceValidationInfo(info);
      const phrase = extractValidateInfo(info);
      notify?.(phrase ? 'Validierungsphrase wurde geladen.' : 'Validierungsstatus wurde geladen.', 'success');
      await onRefresh?.({ silent: true });
    } catch (err) {
      notify?.(err.message || 'Validierungsphrase konnte nicht geladen werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function regenerateVoiceValidation() {
    const taskId = voiceValidationTaskId.trim();
    if (!taskId) return notify?.('Bitte zuerst eine Validation Task-ID eintragen.', 'error');
    setSaving(true);
    try {
      const task = await api.music.voiceRegenerate({ task_id: taskId });
      const newTaskId = extractTaskId(task);
      if (newTaskId) setVoiceValidationTaskId(newTaskId);
      notify?.('Neue Validierungsphrase wurde angefordert.', 'success');
      await onRefresh?.({ silent: true });
    } catch (err) {
      notify?.(err.message || 'Validierungsphrase konnte nicht neu erzeugt werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function startCustomVoiceGeneration() {
    const taskId = voiceValidationTaskId.trim();
    const verifyUrl = voiceVerifyUrl.trim() || selectedUploadUrl(voiceVerifyUploadId);
    const name = voiceNickname.trim() || 'Suno Voice';
    if (!taskId || !verifyUrl) return notify?.('Custom Voice benötigt Validation Task-ID und Verify-Audio-URL.', 'error');
    setSaving(true);
    try {
      const task = await api.music.voiceGenerate({
        task_id: taskId,
        verify_url: verifyUrl,
        voice_name: name,
        description: voiceDescription.trim() || null,
        style: null,
        singer_skill_level: singerSkillLevel || 'beginner'
      });
      const creationTaskId = extractTaskId(task);
      setVoiceCreationTaskId(creationTaskId);
      notify?.('Custom Voice wurde gestartet. Danach Voice Record abrufen.', 'success');
      await onRefresh?.({ silent: true });
    } catch (err) {
      notify?.(err.message || 'Custom Voice konnte nicht gestartet werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function loadCustomVoiceRecord() {
    const taskId = voiceCreationTaskId.trim();
    if (!taskId) return notify?.('Bitte zuerst eine Custom-Voice Task-ID eintragen.', 'error');
    setSaving(true);
    try {
      const info = await api.music.voiceRecordInfo(taskId);
      setVoiceRecordInfo(info);
      const foundVoiceId = extractVoiceId(info);
      if (foundVoiceId && !voiceId.trim()) setVoiceId(foundVoiceId);
      if (foundVoiceId && !voiceTaskId.trim()) setVoiceTaskId(taskId);
      notify?.(foundVoiceId ? 'Voice-ID wurde gefunden und übernommen.' : 'Voice Record wurde geladen.', 'success');
      await onRefresh?.({ silent: true });
    } catch (err) {
      notify?.(err.message || 'Custom Voice Record konnte nicht geladen werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  async function checkCustomVoiceAvailability() {
    const taskId = voiceCreationTaskId.trim() || voiceTaskId.trim();
    if (!taskId) return notify?.('Bitte Custom-Voice Task-ID eintragen.', 'error');
    setSaving(true);
    try {
      const info = await api.music.voiceCheckAvailability({ task_id: taskId });
      notify?.(info?.data?.isAvailable || info?.isAvailable ? 'Voice ist verfügbar.' : 'Voice ist noch nicht verfügbar.', info?.data?.isAvailable || info?.isAvailable ? 'success' : 'warning');
    } catch (err) {
      notify?.(err.message || 'Voice-Verfügbarkeit konnte nicht geprüft werden.', 'error');
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="profile-menu" ref={menuRef}>
      <button className="profile-trigger" type="button" onClick={() => setOpen((value) => !value)} title="Profil öffnen">
        <span className="profile-avatar"><UserRound size={16} /></span>
        <span className="profile-name">{displayName(user)}</span>
      </button>
      {open && (
        <div className="profile-dropdown profile-dropdown-wide">
          <div className="profile-dropdown-head">
            <div>
              <strong>{displayName(user)}</strong>
              <p className="muted">{user?.email}</p>
            </div>
            <button className="icon-button" type="button" onClick={() => setOpen(false)}><X size={16} /></button>
          </div>

          <form className="profile-form" onSubmit={saveProfile}>
            <label>Spitzname
              <input value={nickname} onChange={(event) => setNickname(event.target.value)} placeholder="z. B. Scalino" maxLength={120} />
            </label>
            <button className="primary" type="submit" disabled={saving}><Save size={15} /> Profil speichern</button>
          </form>

          <form className="profile-form" onSubmit={changePassword}>
            <h4><KeyRound size={15} /> Passwort ändern</h4>
            <label>Aktuelles Passwort
              <input type="password" value={currentPassword} onChange={(event) => setCurrentPassword(event.target.value)} autoComplete="current-password" />
            </label>
            <label>Neues Passwort
              <input type="password" value={newPassword} onChange={(event) => setNewPassword(event.target.value)} autoComplete="new-password" minLength={12} />
            </label>
            <button type="submit" disabled={saving}><KeyRound size={15} /> Passwort ändern</button>
          </form>

          <form className="profile-form voice-profile-form" onSubmit={saveVoice}>
            <h4><Mic2 size={15} /> Voice-Verwaltung</h4>
            <p className="muted">Fertige Suno Voice-IDs hier mit Spitznamen speichern. Im Musikbereich erscheint danach automatisch ein Dropdown.</p>
            <label>Voice-Spitzname
              <input value={voiceNickname} onChange={(event) => setVoiceNickname(event.target.value)} placeholder="z. B. Andy Main Voice" />
            </label>
            <label>Voice-ID
              <input value={voiceId} onChange={(event) => setVoiceId(event.target.value)} placeholder="b762e25da0e27d420535ae1068504ecd" />
            </label>
            <label>Task-ID optional
              <input value={voiceTaskId} onChange={(event) => setVoiceTaskId(event.target.value)} placeholder="falls abweichend von Voice-ID" />
            </label>
            <label>Notiz optional
              <textarea rows={2} value={voiceDescription} onChange={(event) => setVoiceDescription(event.target.value)} placeholder="z. B. raue Rapstimme, Hook geeignet…" />
            </label>

            <details className="voice-workflow-panel">
              <summary>Suno Voice Workflow erstellen</summary>
              <p className="muted">Geführter Ablauf: Quelle wählen → Validierungsphrase erzeugen/abrufen → Phrase einsingen/hochladen → Custom Voice erstellen → Voice-ID abrufen.</p>
              <div className="profile-form compact-form">
                {uploadedFiles.length > 0 && (
                  <label>Quelle aus Uploads
                    <select value={voiceSourceUploadId} onChange={(event) => setVoiceSourceUploadId(event.target.value)}>
                      <option value="">Keine Upload-Datei</option>
                      {uploadedFiles.filter((file) => file.uploaded_url).map((file) => <option key={file.id} value={file.id}>{uploadLabel(file)}</option>)}
                    </select>
                  </label>
                )}
                <label>Voice-Quell-URL
                  <input value={voiceSourceUrl} onChange={(event) => setVoiceSourceUrl(event.target.value)} placeholder="https://.../clean-vocal.mp3" />
                </label>
                <div className="inline-fields">
                  <label>Start s<input type="number" value={voiceStartS} onChange={(event) => setVoiceStartS(event.target.value)} /></label>
                  <label>Ende s<input type="number" value={voiceEndS} onChange={(event) => setVoiceEndS(event.target.value)} /></label>
                  <label>Sprache<input value={voiceLanguage} onChange={(event) => setVoiceLanguage(event.target.value)} placeholder="de" /></label>
                </div>
                <button type="button" onClick={startVoiceValidation} disabled={saving}><PlusCircle size={15} /> 1. Validierungsphrase starten</button>

                <label>Validation Task-ID
                  <input value={voiceValidationTaskId} onChange={(event) => setVoiceValidationTaskId(event.target.value)} placeholder="taskId aus Schritt 1" />
                </label>
                <div className="button-row wrap">
                  <button type="button" onClick={loadVoiceValidationInfo} disabled={saving}><RefreshCw size={15} /> 2. Phrase abrufen</button>
                  <button type="button" onClick={regenerateVoiceValidation} disabled={saving}>Phrase neu erzeugen</button>
                </div>
                {extractValidateInfo(voiceValidationInfo) && <div className="mini-result"><strong>Validierungsphrase:</strong><p>{extractValidateInfo(voiceValidationInfo)}</p></div>}

                {uploadedFiles.length > 0 && (
                  <label>Verify-Audio aus Uploads
                    <select value={voiceVerifyUploadId} onChange={(event) => setVoiceVerifyUploadId(event.target.value)}>
                      <option value="">Keine Upload-Datei</option>
                      {uploadedFiles.filter((file) => file.uploaded_url).map((file) => <option key={file.id} value={file.id}>{uploadLabel(file)}</option>)}
                    </select>
                  </label>
                )}
                <label>Verify-Audio-URL
                  <input value={voiceVerifyUrl} onChange={(event) => setVoiceVerifyUrl(event.target.value)} placeholder="https://.../verification-recording.mp3" />
                </label>
                <label>Singer Skill Level
                  <select value={singerSkillLevel} onChange={(event) => setSingerSkillLevel(event.target.value)}>
                    <option value="beginner">beginner</option>
                    <option value="intermediate">intermediate</option>
                    <option value="advanced">advanced</option>
                    <option value="professional">professional</option>
                  </select>
                </label>
                <button type="button" onClick={startCustomVoiceGeneration} disabled={saving}><Mic2 size={15} /> 3. Custom Voice erzeugen</button>

                <label>Custom-Voice Task-ID
                  <input value={voiceCreationTaskId} onChange={(event) => setVoiceCreationTaskId(event.target.value)} placeholder="taskId aus Schritt 3" />
                </label>
                <div className="button-row wrap">
                  <button type="button" onClick={loadCustomVoiceRecord} disabled={saving}><RefreshCw size={15} /> 4. Voice-ID abrufen</button>
                  <button type="button" onClick={checkCustomVoiceAvailability} disabled={saving}><CheckCircle2 size={15} /> Verfügbarkeit prüfen</button>
                </div>
                {extractVoiceId(voiceRecordInfo) && <div className="mini-result"><strong>Gefundene Voice-ID:</strong><p>{extractVoiceId(voiceRecordInfo)}</p></div>}
              </div>
            </details>

            <button className="primary" type="submit" disabled={saving}><PlusCircle size={15} /> Voice speichern</button>

            {voices.length > 0 && (
              <div className="voice-profile-list">
                {voices.map((voice) => (
                  <div key={voice.id} className="voice-profile-item">
                    <span><strong>{voice.nickname || voice.name}</strong><small>{voice.voice_id}</small></span>
                    <button type="button" className="danger ghost" onClick={() => deleteVoice(voice.id)} title="Voice entfernen"><Trash2 size={14} /></button>
                  </div>
                ))}
              </div>
            )}
          </form>

          <button className="danger full" type="button" onClick={onLogout}><LogOut size={15} /> Abmelden</button>
        </div>
      )}
    </div>
  );
}
