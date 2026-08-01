/** 插件管理页（docs/14 /admin/plugins；docs/15 §1）：启用/禁用 + 默认参数编辑。
 *
 * 仅 admin 可见（路由层按 JWT role 门控，服务端 RBAC 强校验）；
 * 禁用后该模型在新建分析时不可选，历史运行不受影响。
 */

import { Button, Card, Input, Modal, Space, Table, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, ModelPlugin, listAdminPlugins, updateAdminPlugin } from "../api";

export default function AdminPluginsPage() {
  const navigate = useNavigate();
  const [plugins, setPlugins] = useState<ModelPlugin[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ModelPlugin | null>(null);
  const [paramsText, setParamsText] = useState("{}");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setPlugins(await listAdminPlugins());
    } catch (e) {
      setLoadError((e as ApiError).message || "插件列表加载失败");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (plugin: ModelPlugin, enabled: boolean) => {
    try {
      await updateAdminPlugin(plugin.key, { enabled });
      message.success(`${plugin.name} 已${enabled ? "启用" : "禁用"}`);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || "更新失败");
    }
  };

  const openEditor = (plugin: ModelPlugin) => {
    setEditing(plugin);
    setParamsText(JSON.stringify((plugin.capability as { default_params?: object }) ?? {}, null, 2));
  };

  const saveParams = async () => {
    if (!editing) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(paramsText) as Record<string, unknown>;
    } catch {
      message.error("默认参数不是合法 JSON");
      return;
    }
    setSaving(true);
    try {
      await updateAdminPlugin(editing.key, { default_params: parsed });
      message.success("默认参数已更新");
      setEditing(null);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || "更新失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Card title="插件管理" extra={<Button onClick={() => navigate("/projects")}>返回项目</Button>}>
      {loadError ? (
        <Typography.Text type="danger">{loadError}</Typography.Text>
      ) : (
        <Table<ModelPlugin>
          rowKey="key"
          loading={plugins === null}
          dataSource={plugins ?? []}
          pagination={false}
          columns={[
            { title: "标识", dataIndex: "key" },
            { title: "名称", dataIndex: "name" },
            { title: "版本", dataIndex: "version", width: 100 },
            {
              title: "任务类型",
              dataIndex: "task_types",
              render: (types: string[]) => (
                <Space size={4}>
                  {types.map((t) => (
                    <Tag key={t}>{t}</Tag>
                  ))}
                </Space>
              ),
            },
            {
              title: "状态",
              dataIndex: "enabled",
              width: 90,
              render: (enabled: boolean) =>
                enabled ? <Tag color="success">启用</Tag> : <Tag color="error">禁用</Tag>,
            },
            {
              title: "操作",
              width: 220,
              render: (_, plugin) => (
                <Space>
                  <Button size="small" onClick={() => void toggle(plugin, !plugin.enabled)}>
                    {plugin.enabled ? "禁用" : "启用"}
                  </Button>
                  <Button size="small" onClick={() => openEditor(plugin)}>
                    默认参数
                  </Button>
                </Space>
              ),
            },
          ]}
        />
      )}
      <Modal
        title={editing ? `默认参数 — ${editing.name}` : ""}
        open={editing !== null}
        onOk={() => void saveParams()}
        onCancel={() => setEditing(null)}
        confirmLoading={saving}
        okText="保存"
        cancelText="取消"
      >
        <Typography.Paragraph type="secondary">
          JSON 对象；新建分析时作为该模型的默认参数（历史运行不受影响）。
        </Typography.Paragraph>
        <Input.TextArea
          rows={8}
          value={paramsText}
          onChange={(e) => setParamsText(e.target.value)}
          style={{ fontFamily: "monospace" }}
        />
      </Modal>
      </Card>
    </div>
  );
}
