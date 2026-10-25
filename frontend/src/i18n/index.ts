import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import { APP_NAME } from "../brand";
import en from "./en.json";
import fr from "./fr.json";

export const languages = ["en", "fr"] as const;
export type Language = (typeof languages)[number];

/** Until the backend tells the configured language, follow the browser. */
export function browserLanguage(): Language {
  return navigator.language.toLowerCase().startsWith("fr") ? "fr" : "en";
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, fr: { translation: fr } },
  lng: browserLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false, defaultVariables: { app: APP_NAME } },
});

export default i18n;
