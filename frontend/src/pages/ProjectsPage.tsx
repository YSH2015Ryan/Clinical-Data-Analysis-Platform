import { Button, Form, Input, Modal, Popconfirm, Space, Table, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  clearTokens,
  createProject,
  deleteProject,
  getRole,
  listProjects,
  type ApiError,
  type Project,
} from "../api";
import { useNavigate } from "react-router-dom";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { formatDateTime } from "../i18n/locale";

export default function ProjectsPage() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<{ name: string; description: string }>();
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listProjects();
      setItems(page.items);
    } catch (e) {
      message.error((e as ApiError).message || t("common.error.load"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCreate = async () => {
    const values = await form.validateFields();
    try {
      await createProject(values.name, values.description ?? "");
      message.success(t("projects.created"));
      setModalOpen(false);
      form.resetFields();
      void reload();
    } catch (e) {
      message.error((e as ApiError).message || t("projects.createFailed"));
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteProject(id);
      message.success(t("projects.deleted"));
      void reload();
    } catch (e) {
      message.error((e as ApiError).message || t("projects.deleteFailed"));
    }
  };

  return (
    <div className="cdap-fade" style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <div className="page-head">
        <Space
          wrap
          style={{ width: "100%", justifyContent: "space-between", alignItems: "flex-end" }}
        >
          <div>
            <p className="page-eyebrow">{t("projects.eyebrow")}</p>
            <Typography.Title level={3} style={{ margin: 0 }}>
              {t("projects.title")}
            </Typography.Title>
            <p className="page-sub" style={{ margin: "6px 0 0" }}>
              {loading ? t("projects.loading") : t("projects.count", { count: items.length })}
            </p>
          </div>
          <Space wrap>
            <LanguageSwitcher />
            {getRole() === "admin" && (
              <>
                <Button onClick={() => navigate("/admin/plugins")}>{t("projects.plugins")}</Button>
                <Button onClick={() => navigate("/admin/ai-settings")}>
                  {t("projects.aiSettings")}
                </Button>
              </>
            )}
            <Button type="primary" onClick={() => setModalOpen(true)}>
              {t("projects.createProject")}
            </Button>
            <Button
              onClick={() => {
                clearTokens();
                navigate("/login");
              }}
            >
              {t("projects.logout")}
            </Button>
          </Space>
        </Space>
      </div>
      <Table<Project>
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        onRow={(record) => ({
          onClick: () => navigate(`/projects/${record.id}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          { title: t("projects.name"), dataIndex: "name" },
          { title: t("projects.description"), dataIndex: "description" },
          {
            title: t("projects.createdAt"),
            dataIndex: "created_at",
            render: (v: string) => formatDateTime(v, i18n.language),
          },
          {
            title: t("projects.actions"),
            render: (_, record) => (
              <span onClick={(e) => e.stopPropagation()}>
                <Popconfirm
                  title={t("projects.deleteConfirm")}
                  onConfirm={() => void onDelete(record.id)}
                >
                  <Button danger size="small">
                    {t("common.action.delete")}
                  </Button>
                </Popconfirm>
              </span>
            ),
          },
        ]}
      />
      <Modal
        title={t("projects.createProject")}
        open={modalOpen}
        onOk={() => void onCreate()}
        onCancel={() => setModalOpen(false)}
        okText={t("common.action.create")}
        cancelText={t("common.action.cancel")}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label={t("projects.projectName")}
            name="name"
            rules={[{ required: true, max: 120, message: t("projects.nameRequired") }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label={t("projects.description")} name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
