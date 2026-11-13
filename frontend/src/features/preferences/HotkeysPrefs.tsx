import { useState } from "react";
import { useTranslation } from "react-i18next";

import { FINAL_KEYS, type Hotkey, MODIFIERS, formatKeys, hotkeyLabel } from "../console/hotkeys";

interface Props {
  hotkeys: Hotkey[];
  /** True while the list is the one shipped with KVM Studio. */
  isDefault: boolean;
  onChange: (hotkeys: Hotkey[]) => void;
  onReset: () => void;
}

interface Draft {
  /** null: a new combination. */
  index: number | null;
  name: string;
  modifiers: string[];
  key: string;
}

function draftOf(index: number | null, hotkey?: Hotkey): Draft {
  const keys = hotkey?.keys ?? [];
  const last = keys.at(-1) ?? "";
  const endsWithModifier = (MODIFIERS as readonly string[]).includes(last);
  return {
    index,
    name: hotkey?.name ?? "",
    modifiers: endsWithModifier ? keys : keys.slice(0, -1),
    key: endsWithModifier ? "" : last,
  };
}

/** Preferences, Hotkeys: the combinations of Send Key. */
export function HotkeysPrefs({ hotkeys, isDefault, onChange, onReset }: Props) {
  const { t } = useTranslation();
  const [selected, setSelected] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(null);
  const current = hotkeys[selected];

  const draftKeys = draft
    ? [...MODIFIERS.filter((m) => draft.modifiers.includes(m)), ...(draft.key ? [draft.key] : [])]
    : [];

  const apply = () => {
    if (!draft || draftKeys.length === 0) return;
    const hotkey: Hotkey = { name: draft.name.trim(), keys: draftKeys };
    if (draft.index === null) {
      onChange([...hotkeys, hotkey]);
      setSelected(hotkeys.length);
    } else {
      onChange(hotkeys.map((h, i) => (i === draft.index ? hotkey : h)));
    }
    setDraft(null);
  };

  return (
    <>
      <p className="prefs-muted">{t("prefs.hotkeysIntro")}</p>
      <ul
        className="list prefs-list prefs-hotkeys"
        role="listbox"
        aria-label={t("prefs.section.hotkeys")}
      >
        {hotkeys.map((hotkey, i) => (
          <li
            key={i}
            role="option"
            aria-selected={i === selected}
            className="list-row"
            onClick={() => setSelected(i)}
            onDoubleClick={() => setDraft(draftOf(i, hotkey))}
          >
            <span>{hotkeyLabel(hotkey, t)}</span>
            {hotkey.name.trim() && <span className="muted mono">{formatKeys(hotkey.keys, t)}</span>}
          </li>
        ))}
        {hotkeys.length === 0 && <li className="list-empty">{t("prefs.noHotkey")}</li>}
      </ul>
      <div className="prefs-list-buttons">
        <button type="button" className="button" onClick={() => setDraft(draftOf(null))}>
          {t("prefs.addHotkey")}
        </button>
        <button
          type="button"
          className="button"
          disabled={!current}
          onClick={() => current && setDraft(draftOf(selected, current))}
        >
          {t("prefs.editHotkey")}
        </button>
        <button
          type="button"
          className="button"
          disabled={!current}
          onClick={() => {
            onChange(hotkeys.filter((_h, i) => i !== selected));
            setSelected((s) => Math.max(0, Math.min(s, hotkeys.length - 2)));
            setDraft(null);
          }}
        >
          {t("prefs.removeHotkey")}
        </button>
        <button
          type="button"
          className="button"
          disabled={isDefault}
          onClick={() => {
            onReset();
            setSelected(0);
            setDraft(null);
          }}
        >
          {t("prefs.resetHotkeys")}
        </button>
      </div>
      {draft && (
        <div className="prefs-subform">
          <label className="prefs-field prefs-inline">
            <span>{t("prefs.hotkeyName")}</span>
            <input
              type="text"
              value={draft.name}
              maxLength={60}
              placeholder={draftKeys.length ? formatKeys(draftKeys, t) : ""}
              onChange={(e) => setDraft({ ...draft, name: e.target.value })}
            />
          </label>
          <div className="prefs-field prefs-inline">
            <span>{t("prefs.hotkeyModifiers")}</span>
            <span className="prefs-modifiers">
              {MODIFIERS.map((m) => (
                <label key={m} className="prefs-check">
                  <input
                    type="checkbox"
                    checked={draft.modifiers.includes(m)}
                    onChange={(e) =>
                      setDraft({
                        ...draft,
                        modifiers: e.target.checked
                          ? [...draft.modifiers, m]
                          : draft.modifiers.filter((x) => x !== m),
                      })
                    }
                  />
                  {t(`keys.${m}`, { defaultValue: m })}
                </label>
              ))}
            </span>
          </div>
          <label className="prefs-field prefs-inline">
            <span>{t("prefs.hotkeyKey")}</span>
            <select value={draft.key} onChange={(e) => setDraft({ ...draft, key: e.target.value })}>
              <option value="">{t("prefs.hotkeyNoKey")}</option>
              {FINAL_KEYS.map((k) => (
                <option key={k} value={k}>
                  {t(`keys.${k}`, { defaultValue: k })}
                </option>
              ))}
            </select>
          </label>
          <div className="prefs-list-buttons">
            <button
              type="button"
              className="button button-primary"
              disabled={draftKeys.length === 0}
              onClick={apply}
            >
              {draft.index === null ? t("prefs.addHotkey") : t("common.apply")}
            </button>
            <button type="button" className="button" onClick={() => setDraft(null)}>
              {t("common.cancel")}
            </button>
          </div>
        </div>
      )}
    </>
  );
}
