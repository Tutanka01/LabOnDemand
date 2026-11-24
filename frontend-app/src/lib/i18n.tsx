import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import fr from "../locales/fr.json";
import en from "../locales/en.json";

export type Locale = "fr" | "en";

type Dictionary = Record<string, string>;
type Replacements = Record<string, string | number>;

const LOCALE_STORAGE_KEY = "labondemand.locale";

// Namespaced dictionaries (locales/<locale>/<namespace>.json) are merged on top
// of the base files so each feature area owns its own translation file.
function mergeNamespaces(base: Dictionary, modules: Record<string, Dictionary>): Dictionary {
  return Object.assign({}, base, ...Object.values(modules));
}

const dictionaries: Record<Locale, Dictionary> = {
  fr: mergeNamespaces(fr, import.meta.glob<Dictionary>("../locales/fr/*.json", { eager: true, import: "default" })),
  en: mergeNamespaces(en, import.meta.glob<Dictionary>("../locales/en/*.json", { eager: true, import: "default" })),
};

const PLACEHOLDER = /\{(\w+)\}/g;

/** Looks `key` up in `locale`, then French, then returns the key itself. */
export function translate(locale: Locale, key: string, replacements?: Replacements): string {
  const value = dictionaries[locale][key] ?? dictionaries.fr[key] ?? key;
  if (!replacements) return value;
  return value.replace(PLACEHOLDER, (match, name: string) =>
    Object.prototype.hasOwnProperty.call(replacements, name) ? String(replacements[name]) : match,
  );
}

interface I18nContextType {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, replacements?: Replacements) => string;
}

const I18nContext = createContext<I18nContextType | null>(null);

function readStoredLocale(): string | null {
  try {
    return window.localStorage.getItem(LOCALE_STORAGE_KEY);
  } catch {
    return null;
  }
}

/** Stored preference first, then the browser language, then French. */
export function getInitialLocale(): Locale {
  if (typeof window === "undefined") return "fr";
  const stored = readStoredLocale();
  if (stored === "fr" || stored === "en") return stored;
  const languages = navigator.languages?.length ? navigator.languages : [navigator.language];
  for (const language of languages) {
    const primary = language?.toLowerCase().split("-")[0];
    if (primary === "fr" || primary === "en") return primary;
  }
  return "fr";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    // Only persist an explicit choice so the browser language keeps applying otherwise.
    try {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next);
    } catch {
      // Storage unavailable (private mode): the choice lasts for this page only.
    }
  }, []);

  const t = useCallback(
    (key: string, replacements?: Replacements) => translate(locale, key, replacements),
    [locale],
  );

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t]);

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) {
    throw new Error("useI18n must be used within an I18nProvider");
  }
  return ctx;
}
