/** 报告页（docs/10 §4）：历史列表 + HTML 内嵌预览（iframe sandbox）+ 下载。
 *
 * PENDING 报告每 3s 轮询至 READY/FAILED；预览经 download 端点取 Blob URL
 * （302 预签名需 Bearer，iframe 无法带头）。
 */

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Modal,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import {
  ApiError,
  ReportFormat,
  ReportItem,
  createReport,
  downloadReport,
  fetchReportBlob,
  listRunReports,
} from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { formatDateTime } from "../i18n/locale";

const POLL_MS = 3000;

const STATUS_COLOR: Record<string, string> = {
  PENDING: "processing",
  READY: "success",
  FAILED: "error",
};

export default function ReportsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();
  const [reports, setReports] = useState<ReportItem[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [creating, setCreating] = useState<ReportFormat | null>(null);
  const [preview, setPreview] = useState<{ url: string; title: string } | null>(null);
  const timer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!id) return;
    try {
      const items = await listRunReports(id);
      setReports(items);
      if (!items.some((r) => r.status === "PENDING") && timer.current) {
        window.clearInterval(timer.current);
        timer.current = null;
      }
    } catch (e) {
      setLoadError((e as ApiError).message || t("reports.loadFailed"));
    }
  }, [id, t]);

  useEffect(() => {
    void refresh();
    timer.current = window.setInterval(() => void refresh(), POLL_MS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [refresh]);

  const onCreate = async (format: ReportFormat) => {
    if (!id) return;
    setCreating(format);
    try {
      await createReport(id, format);
      message.success(t("reports.queued"));
      if (!timer.current) timer.current = window.setInterval(() => void refresh(), POLL_MS);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || t("reports.createFailed"));
    } finally {
      setCreating(null);
    }
  };

  const onPreview = async (report: ReportItem) => {
    try {
      const blob = await fetchReportBlob(report.id);
      setPreview({
        url: URL.createObjectURL(blob),
        title: t("reports.previewTitle", { format: report.format.toUpperCase() }),
      });
    } catch (e) {
      message.error((e as ApiError).message || t("reports.previewFailed"));
    }
  };

  const onDownload = async (report: ReportItem) => {
    try {
      await downloadReport(report);
    } catch (e) {
      message.error((e as ApiError).message || t("reports.downloadFailed"));
    }
  };

  if (loadError) {
    return (
      <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
        <Alert type="error" message={t("reports.unavailable")} description={loadError} />
        <Space style={{ marginTop: 16 }}>
          <Button onClick={() => navigate(-1)}>{t("run.monitor.back")}</Button>
          <Button onClick={() => navigate("/projects")}>{t("run.monitor.backHome")}</Button>
        </Space>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("reports.title")}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          <Button
            type="primary"
            loading={creating === "html"}
            onClick={() => void onCreate("html")}
          >
            {t("reports.create.html")}
          </Button>
          <Button loading={creating === "pdf"} onClick={() => void onCreate("pdf")}>
            {t("reports.create.pdf")}
          </Button>
          <Tooltip title={t("reports.tooltip.docx")}>
            <Button loading={creating === "docx"} onClick={() => void onCreate("docx")}>
              {t("reports.create.docx")}
            </Button>
          </Tooltip>
          <Tooltip title={t("reports.tooltip.markdown")}>
            <Button loading={creating === "markdown"} onClick={() => void onCreate("markdown")}>
              {t("reports.create.markdown")}
            </Button>
          </Tooltip>
          <Button onClick={() => navigate(`/runs/${id}/comparison`)}>
            {t("reports.backComparison")}
          </Button>
          <Button onClick={() => navigate("/projects")}>{t("run.monitor.backHome")}</Button>
        </Space>
      </Space>

      <Card>
        {reports && reports.length > 0 ? (
          <Table<ReportItem>
            rowKey="id"
            dataSource={reports}
            pagination={false}
            columns={[
              {
                title: t("reports.table.format"),
                dataIndex: "format",
                render: (f: string) => f.toUpperCase(),
              },
              {
                title: t("reports.table.status"),
                dataIndex: "status",
                render: (s: ReportItem["status"]) => (
                  <Tag color={STATUS_COLOR[s]}>{t(`reports.status.${s}`)}</Tag>
                ),
              },
              { title: t("reports.table.template"), dataIndex: "template_key" },
              {
                title: t("reports.table.createdAt"),
                dataIndex: "created_at",
                render: (v: string) => formatDateTime(v, i18n.language),
              },
              {
                title: t("reports.table.actions"),
                render: (_, r) => (
                  <Space>
                    <Button
                      size="small"
                      disabled={r.status !== "READY"}
                      onClick={() => void onPreview(r)}
                    >
                      {t("reports.table.preview")}
                    </Button>
                    <Button
                      size="small"
                      disabled={r.status !== "READY"}
                      onClick={() => void onDownload(r)}
                    >
                      {t("reports.table.download")}
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        ) : (
          <Empty description={t("reports.empty")} />
        )}
      </Card>

      <Modal
        open={preview !== null}
        title={preview?.title}
        width="80%"
        footer={null}
        onCancel={() => {
          if (preview) URL.revokeObjectURL(preview.url);
          setPreview(null);
        }}
      >
        {preview && (
          <iframe
            sandbox=""
            title={t("reports.iframeTitle")}
            src={preview.url}
            style={{ width: "100%", height: "70vh", border: "none" }}
          />
        )}
      </Modal>

      <Descriptions size="small" style={{ marginTop: 16 }}>
        <Descriptions.Item label={t("reports.disclaimerLabel")}>
          {t("reports.disclaimer")}
        </Descriptions.Item>
      </Descriptions>
    </div>
  );
}
