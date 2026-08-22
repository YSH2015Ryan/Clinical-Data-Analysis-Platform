import { Button, Progress, Space, Table, Tag, Typography, Upload, message } from "antd";
import { CloseOutlined, UploadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  listDatasets,
  listProjectRuns,
  MAX_UPLOAD_BYTES,
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
  const [uploading, setUploading] = useState<{ name: string; percent: number } | null>(null);
  const uploadController = useRef<AbortController | null>(null);
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

  useEffect(() => () => uploadController.current?.abort(), []);

  const onUpload = async (file: File) => {
    if (!id) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      message.error("文件超过 200 MB 上限，请压缩或拆分后重试");
      return;
    }
    const controller = new AbortController();
    uploadController.current = controller;
    setUploading({ name: file.name, percent: 0 });
    try {
      const resp = await uploadDataset(id, file, {
        signal: controller.signal,
        onProgress: (percent) => setUploading({ name: file.name, percent }),
      });
      message.success("上传成功，校验中");
      void reload();
      navigate(`/datasets/${resp.dataset_id}`, { state: { projectId: id } });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        message.info("上传已取消");
      } else {
        message.error((e as ApiError).message || "上传失败");
      }
    } finally {
      uploadController.current = null;
      setUploading(null);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          数据集
        </Typography.Title>
        <Space wrap>
          <Button onClick={() => navigate(`/projects/${id}/preparation/new`)}>数据准备</Button>
          <Button onClick={() => navigate(`/projects/${id}/analysis/new`)}>新建分析</Button>
          <Upload
            accept=".csv,.xlsx,.xls,.tsv,.txt"
            disabled={uploading !== null}
            showUploadList={false}
            beforeUpload={(file) => {
              if (file.size > MAX_UPLOAD_BYTES) {
                message.error("文件超过 200 MB 上限，请压缩或拆分后重试");
                return Upload.LIST_IGNORE;
              }
              return true;
            }}
            customRequest={({ file }) => void onUpload(file as File)}
          >
            <Button
              type="primary"
              icon={<UploadOutlined />}
              loading={uploading !== null}
              disabled={uploading !== null}
            >
              {uploading ? "正在上传" : "上传数据集"}
            </Button>
          </Upload>
          <Button onClick={() => navigate("/projects")}>返回项目</Button>
        </Space>
      </Space>
      {uploading && (
        <div style={{ marginBottom: 16, maxWidth: 560 }}>
          <Space style={{ width: "100%", justifyContent: "space-between" }}>
            <Typography.Text ellipsis style={{ maxWidth: "calc(100% - 44px)" }}>
              {uploading.name}
            </Typography.Text>
            <Button
              type="text"
              danger
              icon={<CloseOutlined />}
              aria-label="取消上传"
              title="取消上传"
              onClick={() => uploadController.current?.abort()}
            />
          </Space>
          <Progress percent={uploading.percent} status="active" size="small" />
        </div>
      )}
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
