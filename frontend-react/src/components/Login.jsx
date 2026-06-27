import React, { useState } from 'react';
import { api } from '../api/client.js';

export function Login({ onLogin }) {
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
      setError(err.message || 'Login fehlgeschlagen.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-shell">
      <form className="login-card" onSubmit={submit}>
        <div>
          <p className="eyebrow">React Frontend</p>
          <h1>Suno Studio</h1>
          <p className="muted">Bitte anmelden, um die geschützten Funktionen zu nutzen.</p>
        </div>
        {error && <div className="alert error">{error}</div>}
        <label>
          E-Mail
          <input value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="username" required />
        </label>
        <label>
          Passwort
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required />
        </label>
        <button className="primary" disabled={loading}>{loading ? 'Anmeldung läuft…' : 'Einloggen'}</button>
      </form>
    </main>
  );
}
