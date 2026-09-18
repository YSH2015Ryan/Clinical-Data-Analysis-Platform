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

const SWITCH_LABELS: Record<LlmFeatureSwitch, string> = {
  off: "关闭",
  local: "仅本地",
  local_first: "本地优先（失败降级云端）",
  cloud: "仅云端",
};

const FEATURE_LABELS: Record<string, string> = {
  research_profile: "研究画像（研究问题与设计建议）",
  report_interpretation: "报告解读段落",
  validation_explain: "校验报错人话解释",
  iteration: "对话式迭代（重跑建议）",
};

export default function AdminLLMSettingsPage() {
  const navigate = useNavigate();
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
      setLoadError((e as ApiError).message || "加载失败");
    }
  }, [form]);

  useEffect(() => {
    void refresh();
    void listOllamaModels()
      .then((r) => setOllamaModels(r.models))
      .catch(() => setOllamaModels([]));
  }, [refresh]);

  const runTest = async (provider: "local" | "cloud") => {
    setTesting(provider);
    try {
      const r = await testLlmProvider(provider);
      if (r.ok) {
        message.success(`${provider === "local" ? "本地" : "云端"}连接正常（${r.latency_ms}ms）`);
      } else {
        message.error(`${provider === "local" ? "本地" : "云端"}不可用：${r.detail}`);
      }
    } catch (e) {
      message.error((e as ApiError).message || "测试失败");
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
      message.success("已保存并即时生效");
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || "保存失败");
    } finally {
      setSaving(false);
    }
  };

  const clearKey = async (provider: "openai" | "anthropic") => {
    setSaving(true);
    try {
      await updateLlmSettings({ 
        [provider === "openai" ? "openai_api_key" : "anthropic_api_key"]: "" 
      });
      message.success(`${provider === "openai" ? "OpenAI" : "Anthropic"} key 已清除`);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || "操作失败");
    } finally {
      setSaving(false);
    }
  };

  const status = settings?.status;
  const config = settings?.config;

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Card title="AI 设置" extra={<Button onClick={() => navigate("/projects")}>返回项目</Button>}>
        {loadError && <Alert type="error" message={loadError} style={{ marginBottom: 16 }} />}

        <Typography.Title level={5}>Provider 状态</Typography.Title>
        <Space size="middle" wrap style={{ marginBottom: 8 }}>
          <Card size="small" style={{ minWidth: 260 }}>
            <Space direction="vertical" size={4}>
              <Space>
                <Typography.Text strong>本地（Ollama）</Typography.Text>
                {status?.local.available ? (
                  <Tag color="success">可用</Tag>
                ) : (
                  <Tag color="default">不可用</Tag>
                )}
              </Space>
              <Typography.Text type="secondary">
                模型：{status?.local.model ?? config?.ollama_model ?? "-"}
              </Typography.Text>
              <Button
                size="small"
                loading={testing === "local"}
                onClick={() => void runTest("local")}
              >
                连接测试
              </Button>
            </Space>
          </Card>
          <Card size="small" style={{ minWidth: 260 }}>
            <Space direction="vertical" size={4}>
              <Space>
                <Typography.Text strong>
                  云端（{config?.cloud_provider === "anthropic" ? "Anthropic" : "OpenAI"}）
                </Typography.Text>
                {config && !config.cloud_enabled ? (
                  <Tag color="warning">部署层已禁用</Tag>
                ) : status?.cloud.available ? (
                  <Tag color="success">可用</Tag>
                ) : (
                  <Tag color="default">不可用</Tag>
                )}
              </Space>
              <Typography.Text type="secondary">
                模型：{status?.cloud.model ?? "-"}
              </Typography.Text>
              <Button
                size="small"
                loading={testing === "cloud"}
                disabled={config ? !config.cloud_enabled : true}
                onClick={() => void runTest("cloud")}
              >
                连接测试
              </Button>
            </Space>
          </Card>
        </Space>
        <Typography.Paragraph type="secondary" style={{ marginBottom: 24 }}>
          降级链：按下方分功能开关逐功能决定「仅本地 / 本地优先（本地失败时降级云端）/
          仅云端 / 关闭」。LLM 不可用时相关功能自动回退内置规则模板，主流程不阻塞。
        </Typography.Paragraph>

        <Form form={form} layout="vertical" requiredMark={false} disabled={settings === null}>
          <Form.Item name="model_choice" label="默认模型策略">
            <Radio.Group
              options={[
                { value: "auto", label: "自动（本地优先，失败降级云端）" },
                { value: "local", label: "仅本地" },
                { value: "cloud", label: "仅云端" },
              ]}
            />
          </Form.Item>

          <Form.Item
            name="ollama_model"
            label="本地模型（Ollama 已安装列表中选择）"
            extra={ollamaModels.length === 0 ? "未获取到模型列表（Ollama 不可用），可手动输入" : undefined}
          >
            <AutoComplete
              placeholder="选择或输入模型名"
              options={ollamaModels.map((m) => ({ value: m, label: m }))}
              filterOption={(input, option) =>
                String(option?.value ?? "").toLowerCase().includes(input.toLowerCase())
              }
            />
          </Form.Item>

          <Form.Item name="temperature" label="生成温度（0–1，越低越稳定）">
            <Slider min={0} max={1} step={0.05} marks={{ 0: "0", 0.3: "0.3", 1: "1" }} />
          </Form.Item>

          <Typography.Title level={5}>分功能开关</Typography.Title>
          {Object.entries(FEATURE_LABELS).map(([key, label]) => (
            <Form.Item key={key} name={["feature_switches", key]} label={label}>
              <Select
                style={{ maxWidth: 360 }}
                options={(
                  Object.entries(SWITCH_LABELS) as [LlmFeatureSwitch, string][]
                ).map(([value, text]) => ({ value, label: text }))}
              />
            </Form.Item>
          ))}

          <Typography.Title level={5}>云端配置</Typography.Title>
          {config && !config.cloud_enabled && (
            <Alert
              type="info"
              showIcon
              style={{ marginBottom: 12 }}
              message="云端已由部署层禁用（LLM_CLOUD_ENABLED=false）"
              description="如需启用，请服务器开发人员修改环境变量并重启服务。"
            />
          )}
          <Alert
            type="warning"
            showIcon
            style={{ marginBottom: 12 }}
            message="合规提示"
            description="开启云端后，平台只会向云端发送聚合统计结果与列元数据，绝不发送行级患者数据（服务端强制校验）。医疗机构采购与数据出境合规要求请自行评估。"
          />
          
          <Form.Item name="cloud_provider" label="云端提供商">
            <Radio.Group disabled={!config?.cloud_enabled}>
              <Radio.Button value="openai">OpenAI</Radio.Button>
              <Radio.Button value="anthropic">Anthropic Claude</Radio.Button>
            </Radio.Group>
          </Form.Item>

          {config?.cloud_provider === "openai" && (
            <Form.Item
              label={`OpenAI API Key（只写不读${config?.cloud_has_key ? `，当前：${config.cloud_key_preview}` : "，当前未配置"}）`}
            >
              <Space.Compact style={{ maxWidth: 480, width: "100%" }}>
                <Input.Password
                  value={newOpenAIKey}
                  onChange={(e) => setNewOpenAIKey(e.target.value)}
                  placeholder="sk-..."
                  autoComplete="new-password"
                />
                {config?.cloud_has_key && (
                  <Button danger loading={saving} onClick={() => void clearKey("openai")}>
                    清除
                  </Button>
                )}
              </Space.Compact>
            </Form.Item>
          )}

          {config?.cloud_provider === "anthropic" && (
            <Form.Item
              label={`Anthropic API Key（只写不读${config?.cloud_has_key ? `，当前：${config.cloud_key_preview}` : "，当前未配置"}）`}
            >
              <Space.Compact style={{ maxWidth: 480, width: "100%" }}>
                <Input.Password
                  value={newAnthropicKey}
                  onChange={(e) => setNewAnthropicKey(e.target.value)}
                  placeholder="sk-ant-..."
                  autoComplete="new-password"
                />
                {config?.cloud_has_key && (
                  <Button danger loading={saving} onClick={() => void clearKey("anthropic")}>
                    清除
                  </Button>
                )}
              </Space.Compact>
            </Form.Item>
          )}

          <Button type="primary" loading={saving} onClick={() => void save()}>
            保存并生效
          </Button>
        </Form>
      </Card>
    </div>
  );
}
