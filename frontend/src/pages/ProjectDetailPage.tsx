import { Button, Progress, Space, Table, Tag, Typography, Upload, message } from "antd";
import { CloseOutlined, UploadOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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
import LanguageSwitcher from "../components/LanguageSwitcher";
import { RunStatusTag } from "../components/RunProgressBoard";
import { formatDateTime } from "../i18n/locale";

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
  const { i18n, t } = useTranslation();

  const reload = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const page = await listDatasets(id);
      setItems(page.items);
      setRuns((await listProjectRuns(id)).items);
    } catch (e) {
      message.error((e as ApiError).message || t("common.error.load"));
    } finally {
      setLoading(false);
    }
  }, [id, t]);

  useEffect(() => {
    void reload();
  }, [reload]);

  useEffect(() => () => uploadController.current?.abort(), []);

  const onUpload = async (file: File) => {
    if (!id) return;
    if (file.size > MAX_UPLOAD_BYTES) {
      message.error(t("common.error.fileTooLarge"));
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
      message.success(t("projects.detail.uploadSuccess"));
      void reload();
      navigate(`/datasets/${resp.dataset_id}`, { state: { projectId: id } });
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") {
        message.info(t("projects.detail.uploadCanceled"));
      } else {
        message.error((e as ApiError).message || t("projects.detail.uploadFailed"));
      }
    } finally {
      uploadController.current = null;
      setUploading(null);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("projects.detail.datasets")}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          <Button onClick={() => navigate(`/projects/${id}/preparation/new`)}>
            {t("projects.detail.prepare")}
          </Button>
          <Button onClick={() => navigate(`/projects/${id}/analysis/new`)}>
            {t("projects.detail.newAnalysis")}
          </Button>
          <Upload
            accept=".csv,.xlsx,.xls,.tsv,.txt"
            disabled={uploading !== null}
            showUploadList={false}
            beforeUpload={(file) => {
              if (file.size > MAX_UPLOAD_BYTES) {
                message.error(t("common.error.fileTooLarge"));
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
              {uploading ? t("projects.detail.uploading") : t("projects.detail.upload")}
            </Button>
          </Upload>
          <Button onClick={() => navigate("/projects")}>{t("projects.detail.back")}</Button>
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
              aria-label={t("projects.detail.cancelUpload")}
              title={t("projects.detail.cancelUpload")}
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
          { title: t("projects.name"), dataIndex: "name" },
          {
            title: t("projects.detail.encoding"),
            dataIndex: "encoding",
            render: (v: string | null) => v ?? "—",
          },
          {
            title: t("projects.detail.status"),
            dataIndex: "status",
            render: (v: DatasetDetail["status"]) => (
              <Tag color={STATUS_COLOR[v]}>{t(`common.datasetStatus.${v}`)}</Tag>
            ),
          },
          {
            title: t("projects.detail.rows"),
            render: (_, r) => r.preview?.total_rows ?? "—",
          },
        ]}
      />

      <Typography.Title level={4} style={{ marginTop: 32 }}>
        {t("projects.detail.runs")}
      </Typography.Title>
      <Table<AnalysisRun>
        rowKey="id"
        dataSource={runs}
        pagination={false}
        locale={{ emptyText: t("projects.detail.noRuns") }}
        onRow={(record) => ({
          onClick: () => navigate(`/runs/${record.id}`),
          style: { cursor: "pointer" },
        })}
        columns={[
          {
            title: t("projects.createdAt"),
            dataIndex: "created_at",
            render: (v: string) => formatDateTime(v, i18n.language),
          },
          {
            title: t("projects.detail.taskType"),
            dataIndex: "task_type",
            render: (v: AnalysisRun["task_type"]) => t(`common.taskType.${v}`),
          },
          {
            title: t("projects.detail.status"),
            dataIndex: "status",
            render: (v: AnalysisRun["status"]) => <RunStatusTag status={v} />,
          },
        ]}
      />
    </div>
  );
}
