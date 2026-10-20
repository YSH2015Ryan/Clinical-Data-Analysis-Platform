import { Select } from "antd";
import { useTranslation } from "react-i18next";
import { changeLocale } from "../i18n";
import { normalizeLocale } from "../i18n/locale";

export default function LanguageSwitcher() {
  const { i18n, t } = useTranslation();

  return (
    <Select
      aria-label={t("common.language.label")}
      size="small"
      style={{ width: 128 }}
      value={normalizeLocale(i18n.language)}
      onChange={(value) => void changeLocale(value)}
      options={[
        { value: "zh-CN", label: "简体中文" },
        { value: "en", label: "English" },
      ]}
    />
  );
}
