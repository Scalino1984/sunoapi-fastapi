import React, { createContext, useContext, useMemo, useState } from 'react';

const AppAssistantContext = createContext(null);

export function AppAssistantProvider({ children, value }) {
  const [pageState, setPageState] = useState({});

  const apiValue = useMemo(() => ({
    ...(value || {}),
    pageState,
    updatePageState: (scope, patch) => {
      setPageState((current) => ({
        ...current,
        [scope]: {
          ...(current[scope] || {}),
          ...(patch || {})
        }
      }));
    },
    clearPageState: (scope) => {
      setPageState((current) => {
        const next = { ...current };
        delete next[scope];
        return next;
      });
    }
  }), [value, pageState]);

  return <AppAssistantContext.Provider value={apiValue}>{children}</AppAssistantContext.Provider>;
}

export function useAppAssistant() {
  const ctx = useContext(AppAssistantContext);
  if (!ctx) {
    return {
      activeTab: 'home',
      pageState: {},
      updatePageState: () => {},
      executeFrontendAction: () => false,
      buildAssistantContext: () => ({ active_tab: 'home', page_label: 'Home' })
    };
  }
  return ctx;
}
