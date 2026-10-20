import dayjs from "dayjs";
import enUS from "antd/locale/en_US";
import zhCN from "antd/locale/zh_CN";
import { describe, expect, it } from "vitest";
import { applyLocale, getAntdLocale, normalizeLocale } from "./locale";

describe("locale normalization", () => {
  it("maps regional Chinese and English locales to supported locales", () => {
    expect(normalizeLocale("zh-TW")).toBe("zh-CN");
    expect(normalizeLocale("en-US")).toBe("en");
    expect(normalizeLocale("fr-FR")).toBe("zh-CN");
    expect(normalizeLocale(null)).toBe("zh-CN");
  });

  it("maps Ant Design locales explicitly", () => {
    expect(getAntdLocale("en-US")).toBe(enUS);
    expect(getAntdLocale("zh-TW")).toBe(zhCN);
  });

  it("synchronizes dayjs and HTML metadata", () => {
    applyLocale("en-US", "Clinical Analysis");
    expect(dayjs.locale()).toBe("en");
    expect(document.documentElement.lang).toBe("en");
    expect(document.title).toBe("Clinical Analysis");

    applyLocale("zh-TW", "临床分析");
    expect(dayjs.locale()).toBe("zh-cn");
    expect(document.documentElement.lang).toBe("zh-CN");
    expect(document.title).toBe("临床分析");
  });
});
