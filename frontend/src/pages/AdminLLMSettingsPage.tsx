/** AI 设置页（docs/14 /admin/settings/llm*；roadmap T6.6）。
 *
 * 仅 admin 可见。运行层配置（模型策略/分功能开关/云端 key/温度）在此调整，
 * 保存后立即生效无需重启；部署层（Ollama 地址、云端总闸）由服务器开发人员
 * 经环境变量管理，本页只读展示。
 *
 * 红线：云端 key 只写不读（掩码回显）；不向云端发送行级患者数据（服务端强制校验）。
 */

import {
  Alert,
  AutoComplete,
  Button,
  Card,
  Form,
  Input,
  Radio,
  Select,
  Slider,
  Space,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  LlmFeatureSwitch,
  LlmSettings,
  getLlmSettings,
  listOllamaModels,
  testLlmProvider,
  updateLlmSettings,
} from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";

const SWITCH_MODE_KEYS: Record<LlmFeatureSwitch, string> = {
  off: "admin.llm.form.switchModes.off",
  local: "admin.llm.form.switchModes.local",
  local_first: "admin.llm.form.switchModes.localFirst",
  cloud: "admin.llm.form.switchModes.cloud",
};

const FEATURE_LABEL_KEYS: Record<string, string> = {
  research_profile: "admin.llm.form.features.researchProfile",
  report_interpretation: "admin.llm.form.features.reportInterpretation",
  validation_explain: "admin.llm.form.features.validationExplain",
  iteration: "admin.llm.form.features.iteration",
};

export default function AdminLLMSettingsPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [settings, setSettings] = useState<LlmSettings | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [ollamaModels, setOllamaModels] = useState<string[]>([]);
  const [testing, setTesting] = useState<"local" | "cloud" | null>(null);
  const [saving, setSaving] = useState(false);
  const [newOpenAIKey, setNewOpenAIKey] = useState("");
  const [newAnthropicKey, setNewAnthropicKey] = useState("");
  const [form] = Form.useForm();

  const refresh = useCallback(async () => {
    try {
      const s = await getLlmSettings();
      setSettings(s);
      form.setFieldsValue({
        model_choice: s.config.model_choice,
        temperature: s.config.temperature,
        ollama_model: s.config.ollama_model,
        cloud_provider: s.config.cloud_provider,
        feature_switches: s.config.feature_switches,
      });
    } catch (e) {
      setLoadError((e as ApiError).message || t("admin.llm.errors.load"));
    }
  }, [form, t]);

  useEffect(() => {
    void refresh();
    void listOllamaModels()
      .then((r) => setOllamaModels(r.models))
      .catch(() => setOllamaModels([]));
  }, [refresh]);

  const runTest = async (provider: "local" | "cloud") => {
    setTesting(provider);
    const providerLabel = t(
      provider === "local" ? "admin.llm.providers.local" : "admin.llm.providers.cloud",
    );
    try {
      const r = await testLlmProvider(provider);
      if (r.ok) {
        message.success(
          t("admin.llm.messages.testSuccess", {
            provider: providerLabel,
            latency: r.latency_ms,
          }),
        );
      } else {
        message.error(
          t("admin.llm.messages.testFailure", {
            provider: providerLabel,
            detail: r.detail,
          }),
        );
      }
    } catch (e) {
      message.error((e as ApiError).message || t("admin.llm.errors.test"));
    } finally {
      setTesting(null);
    }
  };

  const save = async () => {
    const values = form.getFieldsValue() as {
      model_choice: LlmSettings["config"]["model_choice"];
      temperature: number;
      ollama_model: string;
      cloud_provider: string;
      feature_switches: LlmSettings["config"]["feature_switches"];
    };
    setSaving(true);
    try {
      await updateLlmSettings({
        ...values,
        ...(newOpenAIKey.trim() ? { openai_api_key: newOpenAIKey.trim() } : {}),
        ...(newAnthropicKey.trim() ? { anthropic_api_key: newAnthropicKey.trim() } : {}),
      });
      setNewOpenAIKey("");
      setNewAnthropicKey("");
      message.success(t("admin.llm.messages.saved"));
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || t("admin.llm.errors.save"));
    } finally {
      setSaving(false);
    }
  };

  const clearKey = async (provider: "openai" | "anthropic") => {
    setSaving(true);
    try {
      await updateLlmSettings({
        [provider === "openai" ? "openai_api_key" : "anthropic_api_key"]: "",
      });
      message.success(
        t("admin.llm.messages.keyCleared", {
          provider: t(
            provider === "openai" ? "admin.llm.providers.openai" : "admin.llm.providers.anthropic",
          ),
        }),
      );
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || t("admin.llm.errors.operation"));
    } finally {
      setSaving(false);
    }
  };

  const status = settings?.status;
  const config = settings?.config;
  const cloudProviderLabel =
    config?.cloud_provider === "anthropic"
      ? t("admin.llm.providers.anthropic")
      : t("admin.llm.providers.openai");

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Card
        title={t("admin.llm.title")}
        extra={
          <Space wrap>
            <LanguageSwitcher />
            <Button onClick={() => navigate("/projects")}>
              {t("admin.llm.backToProjects")}
            </Button>
          </Space>
        }
      >
        {loadError && <Alert type="error" message={loadError} style={{ marginBottom: 16 }} />}

        <Typography.Title level={5}>{t("admin.llm.status.title")}</Typography.Title>
        <Space size="middle" wrap style={{ marginBottom: 8 }}>
          <Card size="small" style={{ minWidth: 260 }}>
            <Space direction="vertical" size={4}>
              <Space wrap>
                <Typography.Text strong>{t("admin.llm.status.localTitle")}</Typography.Text>
                {status?.local.available ? (
                  <Tag color="success">{t("admin.llm.status.available")}</Tag>
                ) : (
                  <Tag color="default">{t("admin.llm.status.unavailable")}</Tag>
                )}
              </Space>
              <Typography.Text type="secondary">
                {t("admin.llm.status.model", {
                  model: status?.local.model ?? config?.ollama_model ?? "-",
                })}
              </Typography.Text>
              <Button
                size="small"
                loading={testing === "local"}
                onClick={() => void runTest("local")}
              >
                {t("admin.llm.status.testConnection")}
              </Button>
            </Space>
          </Card>
          <Card size="small" style={{ minWidth: 260 }}>
            <Space direction="vertical" size={4}>
              <Space wrap>
                <Typography.Text strong>
                  {t("admin.llm.status.cloudTitle", { provider: cloudProviderLabel })}
                </Typography.Text>
                {config && !config.cloud_enabled ? (
                  <Tag color="warning">{t("admin.llm.status.deploymentDisabled")}</Tag>
                ) : status?.cloud.available ? (
                  <Tag color="success">{t("admin.llm.status.available")}</Tag>
                ) : (
                  <Tag color="default">{t("admin.llm.status.unavailable")}</Tag>
                )}
              </Space>
              <Typography.Text type="secondary">
                {t("admin.llm.status.model", { model: status?.cloud.model ?? "-" })}
              </Typography.Text>
              <Button
                size="small"
                loading={testing === "cloud"}
                disabled={config ? !config.cloud_enabled : true}
                onClick={() => void runTest("cloud")}
              >
                {t("admin.llm.status.testConnection")}
              </Button>
            </Space>
          </Card>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
          {t("admin.llm.status.fallbackDescription")}
        </Typography.Paragraph>

        <Form form={form} layout="vertical" requiredMark={false} disabled={settings === null}>
          <Form.Item name="model_choice" label={t("admin.llm.form.defaultStrategy")}>
            <Radio.Group
              style={{ display: "flex", flexWrap: "wrap", rowGap: 8 }}
              options={[
                { value: "auto", label: t("admin.llm.form.strategies.auto") },
                { value: "local", label: t("admin.llm.form.strategies.local") },
                { value: "cloud", label: t("admin.llm.form.strategies.cloud") },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="ollama_model"
            label={t("admin.llm.form.ollamaModel")}
            extra={
              ollamaModels.length === 0
                ? t("admin.llm.form.ollamaModelsUnavailable")
                : undefined
            }
          >
            <AutoComplete
              placeholder={t("admin.llm.form.ollamaPlaceholder")}
              options={ollamaModels.map((model) => ({ value: model, label: model }))}
              filterOption={(input, option) =>
                String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>

          <Form.Item name="temperature" label={t("admin.llm.form.temperature")}>
            <Slider min={0} max={1} step={0.05} marks={{ 0: "0", 0.3: "0.3", 1: "1" }} />
          </Form.Item>

          <Typography.Title level={5}>{t("admin.llm.form.featureSwitches")}</Typography.Title>
          {Object.entries(FEATURE_LABEL_KEYS).map(([key, labelKey]) => (
            <Form.Item key={key} name={["feature_switches", key]} label={t(labelKey)}>
              <Select
                style={{ maxWidth: 360 }}
                options={(Object.entries(SWITCH_MODE_KEYS) as [LlmFeatureSwitch, string][]).map(
                  ([value, textKey]) => ({ value, label: t(textKey) }),
                )}
              />
            </Form.Item>
          ))}

          <Typography.Title level={5}>{t("admin.llm.form.cloudConfig")}</Typography.Title>
          {config && !config.cloud_enabled && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message={t("admin.llm.form.cloudDisabledTitle")}
              description={t("admin.llm.form.cloudDisabledDescription")}
            />
          )}
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message={t("admin.llm.form.complianceTitle")}
            description={t("admin.llm.form.complianceDescription")}
          />

          <Form.Item name="cloud_provider" label={t("admin.llm.form.cloudProvider")}>
            <Radio.Group
              disabled={!config?.cloud_enabled}
              style={{ display: "flex", flexWrap: "wrap", rowGap: 8 }}
            >
              <Radio.Button value="openai">
                {t("admin.llm.form.cloudProviderOptions.openai")}
              </Radio.Button>
              <Radio.Button value="anthropic">
                {t("admin.llm.form.cloudProviderOptions.anthropic")}
              </Radio.Button>
            </Radio.Group>
          </Form.Item>

          {config?.cloud_provider === "openai" && (
            <Form.Item
              label={
                config.cloud_has_key
                  ? t("admin.llm.form.apiKeyConfigured", {
                      provider: t("admin.llm.providers.openai"),
                      preview: config.cloud_key_preview,
                    })
                  : t("admin.llm.form.apiKeyNotConfigured", {
                      provider: t("admin.llm.providers.openai"),
                    })
              }
            >
              <Space.Compact style={{ maxWidth: 480, width: "100%" }}>
                <Input.Password
                  value={newOpenAIKey}
                  onChange={(e) => setNewOpenAIKey(e.target.value)}
                  placeholder={t("admin.llm.form.apiKeyPlaceholders.openai")}
                  autoComplete="new-password"
                />
                {config.cloud_has_key && (
                  <Button danger loading={saving} onClick={() => void clearKey("openai")}>
                    {t("admin.llm.form.clearKey")}
                  </Button>
                )}
              </Space.Compact>
            </Form.Item>
          )}

          {config?.cloud_provider === "anthropic" && (
            <Form.Item
              label={
                config.cloud_has_key
                  ? t("admin.llm.form.apiKeyConfigured", {
                      provider: t("admin.llm.providers.anthropic"),
                      preview: config.cloud_key_preview,
                    })
                  : t("admin.llm.form.apiKeyNotConfigured", {
                      provider: t("admin.llm.providers.anthropic"),
                    })
              }
            >
              <Space.Compact style={{ maxWidth: 480, width: "100%" }}>
                <Input.Password
                  value={newAnthropicKey}
                  onChange={(e) => setNewAnthropicKey(e.target.value)}
                  placeholder={t("admin.llm.form.apiKeyPlaceholders.anthropic")}
                  autoComplete="new-password"
                />
                {config.cloud_has_key && (
                  <Button danger loading={saving} onClick={() => void clearKey("anthropic")}>
                    {t("admin.llm.form.clearKey")}
                  </Button>
                )}
              </Space.Compact>
            </Form.Item>
          )}

          <Button type="primary" loading={saving} onClick={() => void save()}>
            {t("admin.llm.form.save")}
          </Button>
        </Form>
      </Card>
    </div>
  );
}
