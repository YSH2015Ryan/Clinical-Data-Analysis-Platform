import { Button, Space, Table, Tag, Typography, Upload, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  listDatasets,
  uploadDataset,
  type ApiError,
  type DatasetDetail,
} from "../api";

const STATUS_COLOR: Record<DatasetDetail["status"], string> = {
  UPLOADED: "default",
  VALIDATING: "processing",
  VALIDATED: "success",
  FAILED: "error",
  ARCHIVED: "default",
};

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [items, setItems] = useState<DatasetDetail[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const reload = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const page = await listDatasets(id);
      setItems(page.items);
    } catch (e) {
      message.error((e as ApiError).message || "加载失败");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const onUpload = async (file: File) => {
    if (!id) return;
    try {
      const resp = await uploadDataset(id, file);
      message.success("上传成功，校验中");
      void reload();
      navigate(`/datasets/${resp.dataset_id}`);
    } catch (e) {
      message.error((e as ApiError).message || "上传失败");
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          数据集
        </Typography.Title>
        <Space>
          <Upload
            accept=".csv,.xlsx,.xls,.tsv,.txt"
            showUploadList={false}
            customRequest={({ file }) => void onUpload(file as File)}
          >
            <Button type="primary" icon={<UploadOutlined />}>
              上传数据集
            </Button>
          </Upload>
          <Button onClick={() => navigate("/projects")}>返回项目</Button>
        </Space>
      </Space>
      <Table<DatasetDetail>
        rowKey="id"
        loading={loading}
        dataSource={items}
        pagination={false}
        onRow={(record) => ({
          onClick: () => navigate(`/datasets/${record.id}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          { title: "名称", dataIndex: "name" },
          { title: "编码", dataIndex: "encoding", render: (v: string | null) => v ?? "—" },
          {
            title: "状态",
            dataIndex: "status",
            render: (v: DatasetDetail["status"]) => <Tag color={STATUS_COLOR[v]}>{v}</Tag>,
          },
          {
            title: "行数",
            render: (_, r) => r.preview?.total_rows ?? "—",
          },
        ]}
      />
    </div>
  );
}
