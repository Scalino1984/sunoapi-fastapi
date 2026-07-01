import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { de } from './de.js';
import { en } from './en.js';

export const SUPPORTED_LANGUAGES = {
  de: { code: 'de', label: 'Deutsch' },
  en: { code: 'en', label: 'English' }
};

const STORAGE_KEY = 'react-ui-language';
const dictionaries = { de, en };
const I18nContext = createContext(null);

function normalizeLanguage(value) {
  const key = String(value || '').trim().toLowerCase();
  return Object.prototype.hasOwnProperty.call(dictionaries, key) ? key : 'de';
}

function readInitialLanguage() {
  try {
    return normalizeLanguage(window.localStorage.getItem(STORAGE_KEY) || navigator.language?.slice(0, 2));
  } catch {
    return 'de';
  }
}

function lookup(dictionary, key) {
  return String(key || '')
    .split('.')
    .filter(Boolean)
    .reduce((current, part) => (current && typeof current === 'object' ? current[part] : undefined), dictionary);
}

function interpolate(value, params = {}) {
  return String(value).replace(/\{\{\s*([^}\s]+)\s*\}\}/g, (_, name) => {
    const replacement = params[name];
    return replacement === undefined || replacement === null ? '' : String(replacement);
  });
}

export function I18nProvider({ children }) {
  const [language, setLanguageState] = useState(readInitialLanguage);

  const setLanguage = useCallback((nextLanguage) => {
    const normalized = normalizeLanguage(nextLanguage);
    setLanguageState(normalized);
    try {
      window.localStorage.setItem(STORAGE_KEY, normalized);
    } catch {
      // Browsers can block localStorage; the in-memory language still updates.
    }
  }, []);

  useEffect(() => {
    document.documentElement.lang = language;
  }, [language]);

  const t = useCallback((key, fallback = '', params = {}) => {
    const value = lookup(dictionaries[language], key);
    if (typeof value === 'string') return interpolate(value, params);
    const fallbackValue = lookup(dictionaries.de, key);
    if (typeof fallbackValue === 'string') return interpolate(fallbackValue, params);
    return interpolate(fallback || key, params);
  }, [language]);

  const value = useMemo(() => ({
    language,
    setLanguage,
    supportedLanguages: SUPPORTED_LANGUAGES,
    t
  }), [language, setLanguage, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const context = useContext(I18nContext);
  if (context) return context;
  return {
    language: 'de',
    setLanguage: () => {},
    supportedLanguages: SUPPORTED_LANGUAGES,
    t: (key, fallback = '', params = {}) => interpolate(fallback || key, params)
  };
}
