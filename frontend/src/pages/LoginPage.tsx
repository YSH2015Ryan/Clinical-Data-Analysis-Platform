import { Button, Form, Input, message } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { login, setTokens, type ApiError } from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";

export default function LoginPage() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { t } = useTranslation();

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const tokens = await login(values.email, values.password);
      setTokens(tokens.access_token, tokens.refresh_token);
      navigate("/projects");
    } catch (e) {
      const err = e as ApiError;
      message.error(err.message || t("auth.failed"));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-wrap">
      <div className="login-brand">
        <p className="login-eyebrow">{t("auth.eyebrow")}</p>
        <h1 className="login-title">
          {t("auth.title")}
          <br />
          <span style={{ fontSize: "0.5em", color: "#555" }}>{t("auth.subtitle")}</span>
        </h1>
        <p className="login-sub">{t("auth.description")}</p>
        <ul className="login-points">
          <li>
            <span>{t("auth.qualityTitle")}</span>
            {t("auth.qualityText")}
          </li>
          <li>
            <span>{t("auth.modelsTitle")}</span>
            {t("auth.modelsText")}
          </li>
          <li>
            <span>{t("auth.reportsTitle")}</span>
            {t("auth.reportsText")}
          </li>
        </ul>
      </div>
      <div className="login-form-col">
        <div className="login-card">
          <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
            <LanguageSwitcher />
          </div>
          <p className="login-card-title">{t("auth.cardTitle")}</p>
          <p className="login-card-sub">{t("auth.cardSubtitle")}</p>
          <Form layout="vertical" onFinish={onFinish} requiredMark={false}>
            <Form.Item
              label={t("auth.email")}
              name="email"
              rules={[{ required: true, type: "email", message: t("auth.emailRequired") }]}
            >
              <Input autoFocus />
            </Form.Item>
            <Form.Item
              label={t("auth.password")}
              name="password"
              rules={[{ required: true, message: t("auth.passwordRequired") }]}
            >
              <Input.Password />
            </Form.Item>
            <Button type="primary" htmlType="submit" block loading={loading}>
              {t("auth.submit")}
            </Button>
          </Form>
        </div>
      </div>
    </div>
  );
}
