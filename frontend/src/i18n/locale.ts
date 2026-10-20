import dayjs from "dayjs";
import "dayjs/locale/zh-cn";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";

export const LOCALE_STORAGE_KEY = "cdap.locale";
export const SUPPORTED_LOCALES = ["zh-CN", "en"] as const;
export type SupportedLocale = (typeof SUPPORTED_LOCALES)[number];

export function normalizeLocale(locale: string | null | undefined): SupportedLocale {
  const normalized = locale?.trim().replaceAll("_", "-").toLowerCase();
  return normalized?.startsWith("en") ? "en" : "zh-CN";
}

export function getAntdLocale(locale: string): typeof zhCN {
  return normalizeLocale(locale) === "en" ? enUS : zhCN;
}

export function applyLocale(locale: string, title: string): void {
  const normalized = normalizeLocale(locale);
  dayjs.locale(normalized === "en" ? "en" : "zh-cn");
  document.documentElement.lang = normalized;
  document.title = title;
}

export function formatDateTime(value: string, locale: string): string {
  return new Intl.DateTimeFormat(normalizeLocale(locale), {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatNumber(
  value: number,
  locale: string,
  options?: Intl.NumberFormatOptions,
): string {
  return new Intl.NumberFormat(normalizeLocale(locale), options).format(value);
}
