import { createContext, useContext, useEffect, useState, ReactNode } from "react";
import fr from "../locales/fr.json";
import en from "../locales/en.json";

export type Locale = "fr" | "en";

const dictionaries = { fr, en } as const;

interface I18nContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, replacements?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

export function getInitialLocale(): Locale {
  if (typeof window === "undefined") return "fr";
  const stored = window.localStorage.getItem("labondemand.locale");
  return stored === "en" ? "en" : "fr";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
    window.localStorage.setItem("labondemand.locale", locale);
  }, [locale]);

  const setLocale = (l: Locale) => setLocaleState(l);

  const t = (key: string, replacements?: Record<string, string | number>): string => {
    const dict = dictionaries[locale];
    const val = (dict as Record<string, string>)[key] || key;
    if (replacements) {
      return Object.entries(replacements).reduce((acc, [k, v]) => {
        return acc.replace(`{${k}}`, String(v));
      }, val);
    }
    return val;
  };

  return (
    <I18nContext.Provider value={{ locale, setLocale, t }}>
      {children}
    </I18nContext.Provider>
  );
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}
