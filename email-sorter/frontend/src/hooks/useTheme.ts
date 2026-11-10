import { useCallback, useSyncExternalStore } from "react";

export type ThemePref = "auto" | "light" | "dark";

const KEY = "inbox-sorter.theme";
const EVENT = "inbox-sorter:theme";
const QUERY = "(prefers-color-scheme: dark)";

function readPref(): ThemePref {
  try {
    const stored = window.localStorage.getItem(KEY);
    return stored === "light" || stored === "dark" ? stored : "auto";
  } catch {
    return "auto";
  }
}

function subscribe(onChange: () => void): () => void {
  const media = window.matchMedia(QUERY);
  window.addEventListener(EVENT, onChange);
  media.addEventListener("change", onChange);
  return () => {
    window.removeEventListener(EVENT, onChange);
    media.removeEventListener("change", onChange);
  };
}

/** Light, dark, or follow the device. The page itself reads `data-theme`. */
export function useTheme() {
  const pref = useSyncExternalStore(subscribe, readPref, () => "auto" as ThemePref);
  const systemDark = useSyncExternalStore(
    subscribe,
    () => window.matchMedia(QUERY).matches,
    () => false,
  );

  const setPref = useCallback((next: ThemePref) => {
    try {
      if (next === "auto") {
        window.localStorage.removeItem(KEY);
      } else {
        window.localStorage.setItem(KEY, next);
      }
    } catch {
      // The choice still applies until the page is closed.
    }

    if (next === "auto") {
      delete document.documentElement.dataset.theme;
    } else {
      document.documentElement.dataset.theme = next;
    }
    window.dispatchEvent(new Event(EVENT));
  }, []);

  return { pref, setPref, dark: pref === "dark" || (pref === "auto" && systemDark) };
}
