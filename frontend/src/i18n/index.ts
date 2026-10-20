import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";
import { LOCALE_STORAGE_KEY, normalizeLocale, SUPPORTED_LOCALES } from "./locale";
import { resources } from "./resources";

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources,
    fallbackLng: "zh-CN",
    supportedLngs: [...SUPPORTED_LOCALES],
    load: "currentOnly",
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: LOCALE_STORAGE_KEY,
      caches: [],
      convertDetectedLanguage: normalizeLocale,
    },
    interpolation: { escapeValue: false },
    returnEmptyString: false,
  });

export async function changeLocale(locale: string): Promise<void> {
  const normalized = normalizeLocale(locale);
  try {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, normalized);
  } catch {
    // A blocked storage API must not prevent an in-memory language switch.
  }
  await i18n.changeLanguage(normalized);
}

export default i18n;
