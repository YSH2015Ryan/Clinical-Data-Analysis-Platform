import { Button, Form, Input, Modal, Popconfirm, Space, Table, Typography, message } from "antd";
import { useCallback, useEffect, useState } from "react";
import {
  clearTokens,
  createProject,
  deleteProject,
  listProjects,
  type ApiError,
  type Project,
} from "../api";
import { useNavigate } from "react-router-dom";

export default function ProjectsPage() {
  const [items, setItems] = useState<Project[]>([]);
  const [loading, setLoading] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [form] = Form.useForm<{ name: string; description: string }>();
  const navigate = useNavigate();

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const page = await listProjects();
      setItems(page.items);
    } catch (e) {
      message.error((e as ApiError).message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onCreate = async () => {
    const values = await form.validateFields();
    try {
      await createProject(values.name, values.description ?? "");
      message.success("项目已创建");
      setModalOpen(false);
      form.resetFields();
      void reload();
    } catch (e) {
      message.error((e as ApiError).message || "创建失败");
    }
  };

  const onDelete = async (id: string) => {
    try {
      await deleteProject(id);
      message.success("已删除");
      void reload();
    } catch (e) {
      message.error((e as ApiError).message || "删除失败");
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          我的项目
        </Typography.Title>
        <Space>
          <Button type="primary" onClick={() => setModalOpen(true)}>
            新建项目
          </Button>
          <Button
            onClick={() => {
              clearTokens();
              navigate("/login");
            }}
          >
            退出登录
          </Button>
        </Space>
      </Space>
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
          { title: "名称", dataIndex: "name" },
          { title: "描述", dataIndex: "description" },
          {
            title: "创建时间",
            dataIndex: "created_at",
            render: (v: string) => new Date(v).toLocaleString(),
          },
          {
            title: "操作",
            render: (_, record) => (
              <span onClick={(e) => e.stopPropagation()}>
                <Popconfirm title="确认删除该项目？" onConfirm={() => void onDelete(record.id)}>
                  <Button danger size="small">
                    删除
                  </Button>
                </Popconfirm>
              </span>
            ),
          },
        ]}
      />
      <Modal
        title="新建项目"
        open={modalOpen}
        onOk={() => void onCreate()}
        onCancel={() => setModalOpen(false)}
        okText="创建"
        cancelText="取消"
      >
        <Form form={form} layout="vertical">
          <Form.Item
            label="项目名称"
            name="name"
            rules={[{ required: true, max: 120, message: "请输入名称（≤120 字）" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item label="描述" name="description">
            <Input.TextArea rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
