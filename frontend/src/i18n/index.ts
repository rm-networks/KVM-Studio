import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { APP_NAME } from "../brand";
import en from "./en.json";
import fr from "./fr.json";

export const languages = ["en", "fr"] as const;
export type Language = (typeof languages)[number];

/** Each language under its own name, whatever the current one. */
export const LANGUAGE_NAMES: Record<Language, string> = { en: "English", fr: "Français" };

const GUEST_LANGUAGE_KEY = "kvmstudio.guestLanguage";

/**
 * Language a guest of LAN sharing picked in Edit > Language: kept by their
 * own browser, never sent to the host.
 */
export function storedGuestLanguage(): Language | null {
  try {
    const found = localStorage.getItem(GUEST_LANGUAGE_KEY);
    return languages.find((l) => l === found) ?? null;
  } catch {
    return null;
  }
}

export function storeGuestLanguage(language: Language): void {
  try {
    localStorage.setItem(GUEST_LANGUAGE_KEY, language);
  } catch {
    // Storage blocked (private window): the choice lasts for this page only.
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fr: { translation: fr } },
  // English until the configuration says otherwise; never the desktop's language.
  lng: storedGuestLanguage() ?? "en",
  fallbackLng: "en",
  interpolation: { escapeValue: false, defaultVariables: { app: APP_NAME } },
});

export default i18n;
