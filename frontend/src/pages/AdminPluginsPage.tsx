/** 插件管理页（docs/14 /admin/plugins；docs/15 §1）：启用/禁用 + 默认参数编辑。
 *
 * 仅 admin 可见（路由层按 JWT role 门控，服务端 RBAC 强校验）；
 * 禁用后该模型在新建分析时不可选，历史运行不受影响。
 */

import { Button, Card, Input, Modal, Space, Table, Tag, Tooltip, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ApiError, ModelPlugin, listAdminPlugins, updateAdminPlugin } from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";

/** 标识 → 功能简介资源键（hover 提示；与 backend/app/plugins/builtin 一一对应）。 */
const PLUGIN_DESCRIPTION_KEYS: Record<string, string> = {
  logreg: "admin.plugins.descriptions.logreg",
  rf: "admin.plugins.descriptions.rf",
  svm: "admin.plugins.descriptions.svm",
  xgboost: "admin.plugins.descriptions.xgboost",
  lightgbm: "admin.plugins.descriptions.lightgbm",
  catboost: "admin.plugins.descriptions.catboost",
  lasso: "admin.plugins.descriptions.lasso",
  elasticnet: "admin.plugins.descriptions.elasticnet",
  rf_reg: "admin.plugins.descriptions.rfReg",
  xgboost_reg: "admin.plugins.descriptions.xgboostReg",
  km: "admin.plugins.descriptions.km",
  coxph: "admin.plugins.descriptions.coxph",
  rsf: "admin.plugins.descriptions.rsf",
  gbs: "admin.plugins.descriptions.gbs",
  deepsurv: "admin.plugins.descriptions.deepsurv",
  dummy: "admin.plugins.descriptions.dummy",
};

export default function AdminPluginsPage() {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const [plugins, setPlugins] = useState<ModelPlugin[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState<ModelPlugin | null>(null);
  const [paramsText, setParamsText] = useState("{}");
  const [saving, setSaving] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setPlugins(await listAdminPlugins());
    } catch (e) {
      setLoadError((e as ApiError).message || t("admin.plugins.errors.load"));
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const toggle = async (plugin: ModelPlugin, enabled: boolean) => {
    try {
      await updateAdminPlugin(plugin.key, { enabled });
      message.success(
        t(enabled ? "admin.plugins.messages.enabled" : "admin.plugins.messages.disabled", {
          name: plugin.name,
        }),
      );
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || t("admin.plugins.errors.update"));
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
      message.error(t("admin.plugins.errors.invalidJson"));
      return;
    }
    setSaving(true);
    try {
      await updateAdminPlugin(editing.key, { default_params: parsed });
      message.success(t("admin.plugins.messages.paramsSaved"));
      setEditing(null);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || t("admin.plugins.errors.update"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Card
        title={t("admin.plugins.title")}
        extra={
          <Space wrap>
            <LanguageSwitcher />
            <Button onClick={() => navigate("/projects")}>
              {t("admin.plugins.backToProjects")}
            </Button>
          </Space>
        }
      >
        {loadError ? (
          <Typography.Text type="danger">{loadError}</Typography.Text>
        ) : (
          <Table<ModelPlugin>
            rowKey="key"
            loading={plugins === null}
            dataSource={plugins ?? []}
            pagination={false}
            columns={[
              {
                title: t("admin.plugins.table.key"),
                dataIndex: "key",
                render: (key: string) => (
                  <Tooltip
                    title={t(PLUGIN_DESCRIPTION_KEYS[key] ?? "admin.plugins.descriptionUnavailable")}
                    placement="right"
                  >
                    <span style={{ borderBottom: "1px dashed #bbb", cursor: "help" }}>{key}</span>
                  </Tooltip>
                ),
              },
              { title: t("admin.plugins.table.name"), dataIndex: "name" },
              { title: t("admin.plugins.table.version"), dataIndex: "version", width: 100 },
              {
                title: t("admin.plugins.table.taskTypes"),
                dataIndex: "task_types",
                render: (types: string[]) => (
                  <Space size={4} wrap>
                    {types.map((taskType) => (
                      <Tag key={taskType}>{taskType}</Tag>
                    ))}
                  </Space>
                ),
              },
              {
                title: t("admin.plugins.table.status"),
                dataIndex: "enabled",
                width: 90,
                render: (enabled: boolean) =>
                  enabled ? (
                    <Tag color="success">{t("admin.plugins.status.enabled")}</Tag>
                  ) : (
                    <Tag color="error">{t("admin.plugins.status.disabled")}</Tag>
                  ),
              },
              {
                title: t("admin.plugins.table.actions"),
                width: 220,
                render: (_, plugin) => (
                  <Space wrap>
                    <Button size="small" onClick={() => void toggle(plugin, !plugin.enabled)}>
                      {plugin.enabled
                        ? t("admin.plugins.actions.disable")
                        : t("admin.plugins.actions.enable")}
                    </Button>
                    <Button size="small" onClick={() => openEditor(plugin)}>
                      {t("admin.plugins.actions.defaultParams")}
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        )}
        <Modal
          title={editing ? t("admin.plugins.modal.title", { name: editing.name }) : ""}
          open={editing !== null}
          onOk={() => void saveParams()}
          onCancel={() => setEditing(null)}
          confirmLoading={saving}
          okText={t("admin.plugins.modal.save")}
          cancelText={t("admin.plugins.modal.cancel")}
        >
          <Typography.Paragraph type="secondary">
            {t("admin.plugins.modal.description")}
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
