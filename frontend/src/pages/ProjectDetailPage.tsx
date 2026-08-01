import { Button, Space, Table, Tag, Typography, Upload, message } from "antd";
import { UploadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  listDatasets,
  listProjectRuns,
  uploadDataset,
  type AnalysisRun,
  type ApiError,
  type DatasetDetail,
} from "../api";
import { RunStatusTag } from "../components/RunProgressBoard";

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
  const [runs, setRuns] = useState<AnalysisRun[]>([]);
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const reload = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const page = await listDatasets(id);
      setItems(page.items);
      setRuns((await listProjectRuns(id)).items);
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
      navigate(`/datasets/${resp.dataset_id}`, { state: { projectId: id } });
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
          <Button onClick={() => navigate(`/projects/${id}/analysis/new`)}>新建分析</Button>
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
          onClick: () => navigate(`/datasets/${record.id}`, { state: { projectId: id } }),
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

      <Typography.Title level={4} style={{ marginTop: 32 }}>
        分析运行
      </Typography.Title>
      <Table<AnalysisRun>
        rowKey="id"
        dataSource={runs}
        pagination={false}
        locale={{ emptyText: "暂无分析运行" }}
        onRow={(record) => ({
          onClick: () => navigate(`/runs/${record.id}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          {
            title: "创建时间",
            dataIndex: "created_at",
            render: (v: string) => new Date(v).toLocaleString(),
          },
          { title: "任务类型", dataIndex: "task_type" },
          {
            title: "状态",
            dataIndex: "status",
            render: (v: AnalysisRun["status"]) => <RunStatusTag status={v} />,
          },
        ]}
      />
    </div>
  );
}
