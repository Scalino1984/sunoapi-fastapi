import React, { useState } from 'react';
import { api } from '../api/client.js';
import { useI18n } from '../i18n/I18nContext.jsx';

export function Login({ onLogin }) {
  const { t } = useI18n();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  async function submit(event) {
    event.preventDefault();
    setLoading(true);
    setError('');
    try {
      await api.auth.login(email, password);
      const user = await api.auth.me();
      onLogin(user);
    } catch (err) {
      setError(err.message || t('login.failed', 'Login fehlgeschlagen.'));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div>
          <p className="eyebrow">{t('login.eyebrow', 'React Frontend')}</p>
          <h1>{t('login.title', 'Suno Studio')}</h1>
          <p className="muted">{t('login.intro', 'Bitte anmelden, um die geschützten Funktionen zu nutzen.')}</p>
        </div>
        {error && <div className="alert error">{error}</div>}
        <label>
          {t('login.email', 'E-Mail')}
          <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          {t('login.password', 'Passwort')}
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
        </label>
        <button className="primary" disabled={loading}>{loading ? t('login.loading', 'Anmeldung läuft…') : t('login.submit', 'Einloggen')}</button>
      </form>
    </main>
  );
}
