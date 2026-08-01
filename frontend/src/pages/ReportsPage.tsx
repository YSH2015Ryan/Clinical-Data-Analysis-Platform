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

const POLL_MS = 3000;

const STATUS_COLOR: Record<string, string> = {
  PENDING: "processing",
  READY: "success",
  FAILED: "error",
};

export default function ReportsPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
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
      setLoadError((e as ApiError).message || "报告列表加载失败");
    }
  }, [id]);

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
      message.success("报告已入队，生成中…");
      if (!timer.current) timer.current = window.setInterval(() => void refresh(), POLL_MS);
      await refresh();
    } catch (e) {
      message.error((e as ApiError).message || "报告生成失败");
    } finally {
      setCreating(null);
    }
  };

  const onPreview = async (report: ReportItem) => {
    try {
      const blob = await fetchReportBlob(report.id);
      setPreview({
        url: URL.createObjectURL(blob),
        title: `报告预览（${report.format.toUpperCase()}）`,
      });
    } catch (e) {
      message.error((e as ApiError).message || "预览加载失败");
    }
  };

  const onDownload = async (report: ReportItem) => {
    try {
      await downloadReport(report);
    } catch (e) {
      message.error((e as ApiError).message || "下载失败");
    }
  };

  if (loadError) {
    return (
      <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
        <Alert type="error" message="报告列表不可用" description={loadError} />
        <Button style={{ marginTop: 16 }} onClick={() => navigate(-1)}>
          返回
        </Button>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          分析报告
        </Typography.Title>
        <Space>
          <Button
            type="primary"
            loading={creating === "html"}
            onClick={() => void onCreate("html")}
          >
            生成 HTML 报告
          </Button>
          <Button loading={creating === "pdf"} onClick={() => void onCreate("pdf")}>
            生成 PDF 报告
          </Button>
          <Tooltip title="Word/Markdown 导出开发中（T7.6）">
            <Button disabled>Word / Markdown</Button>
          </Tooltip>
          <Button onClick={() => navigate(`/runs/${id}/comparison`)}>返回比较</Button>
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
                title: "格式",
                dataIndex: "format",
                render: (f: string) => f.toUpperCase(),
              },
              {
                title: "状态",
                dataIndex: "status",
                render: (s: string) => <Tag color={STATUS_COLOR[s]}>{s}</Tag>,
              },
              { title: "模板", dataIndex: "template_key" },
              { title: "创建时间", dataIndex: "created_at" },
              {
                title: "操作",
                render: (_, r) => (
                  <Space>
                    <Button
                      size="small"
                      disabled={r.status !== "READY"}
                      onClick={() => void onPreview(r)}
                    >
                      预览
                    </Button>
                    <Button
                      size="small"
                      disabled={r.status !== "READY"}
                      onClick={() => void onDownload(r)}
                    >
                      下载
                    </Button>
                  </Space>
                ),
              },
            ]}
          />
        ) : (
          <Empty description="暂无报告，点击上方按钮生成" />
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
            title="报告预览"
            src={preview.url}
            style={{ width: "100%", height: "70vh", border: "none" }}
          />
        )}
      </Modal>

      <Descriptions size="small" style={{ marginTop: 16 }}>
        <Descriptions.Item label="免责声明">
          报告由 CDAP 自动生成，仅供科研参考，不构成临床诊断建议。
        </Descriptions.Item>
      </Descriptions>
    </div>
  );
}
