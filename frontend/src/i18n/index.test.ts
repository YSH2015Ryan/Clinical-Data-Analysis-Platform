import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LOCALE_STORAGE_KEY } from "./locale";

async function loadI18n() {
  return import("./index");
}

describe("language preference", () => {
  beforeEach(() => {
    vi.resetModules();
    window.localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("prefers an explicitly stored locale over the browser locale", async () => {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, "en");
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("zh-TW");
    const { default: i18n } = await loadI18n();
    expect(i18n.language).toBe("en");
  });

  it.each([
    ["zh-TW", "zh-CN"],
    ["en-US", "en"],
    ["fr-FR", "zh-CN"],
  ])("normalizes browser locale %s to %s", async (browserLocale, expected) => {
    vi.spyOn(window.navigator, "language", "get").mockReturnValue(browserLocale);
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue([browserLocale]);
    const { default: i18n } = await loadI18n();
    expect(i18n.language).toBe(expected);
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBeNull();
  });

  it("persists only a manual selection", async () => {
    const { changeLocale, default: i18n } = await loadI18n();
    await changeLocale("en-US");
    expect(i18n.language).toBe("en");
    expect(window.localStorage.getItem(LOCALE_STORAGE_KEY)).toBe("en");
  });

  it("still switches language when localStorage is unavailable", async () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new DOMException("Blocked", "SecurityError");
    });
    const { changeLocale, default: i18n } = await loadI18n();
    await expect(changeLocale("en")).resolves.toBeUndefined();
    expect(i18n.language).toBe("en");
  });
});
