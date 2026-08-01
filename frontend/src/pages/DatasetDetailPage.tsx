import {
  Alert,
  Button,
  Card,
  Descriptions,
  List,
  Popconfirm,
  Select,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  getDataset,
  getQualityReport,
  quickFix,
  SEMANTIC_OPTIONS,
  type ApiError,
  type ColumnProfile,
  type DatasetDetail,
  type Issue,
  type QualityReport,
  type QuickFixAction,
} from "../api";
import PreprocessPanel from "./PreprocessPanel";
import TaskDetectCard from "./TaskDetectCard";

const SEVERITY_COLOR: Record<Issue["severity"], string> = {
  blocker: "error",
  warning: "warning",
  info: "blue",
};

const SEVERITY_LABEL: Record<Issue["severity"], string> = {
  blocker: "阻塞",
  warning: "警告",
  info: "信息",
};

const REPORT_LABEL: Record<QualityReport["status"], string> = {
  PASSED: "通过",
  PASSED_WITH_WARNINGS: "有警告",
  FAILED: "未通过",
};

const POLL_MS = 2000;

/** 规则 → 一键修复动作映射（docs/05 §5；仅 warning 级显示按钮） */
function fixActionFor(issue: Issue): QuickFixAction | null {
  if (issue.rule_id === "RV201" && issue.column)
    return { type: "drop_column", column: issue.column };
  if (issue.rule_id === "RV401" && !issue.column) return { type: "drop_duplicates" };
  if (issue.rule_id === "RV301" && issue.column)
    return { type: "to_missing", column: issue.column };
  return null;
}

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [report, setReport] = useState<QualityReport | null>(null);
  const [fixing, setFixing] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const projectId = (location.state as { projectId?: string } | null)?.projectId;

  const reload = useCallback(async () => {
    if (!id) return;
    try {
      const ds = await getDataset(id);
      setDataset(ds);
      if (ds.status === "VALIDATED" || ds.status === "FAILED") {
        try {
          setReport(await getQualityReport(id));
        } catch {
          setReport(null); // 报告尚未落库，下一轮轮询
        }
      }
    } catch (e) {
      message.error((e as ApiError).message || "加载失败");
    }
  }, [id]);

  useEffect(() => {
    void reload();
    const timer = setInterval(() => {
      if (dataset?.status === "VALIDATING" || (dataset && !report)) void reload();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [reload, dataset, report]);

  if (!dataset) return null;
  const blocked = (report?.blockers ?? 0) > 0 || dataset.status === "FAILED";

  const onFix = async (action: QuickFixAction) => {
    if (!id) return;
    setFixing(true);
    try {
      const v = await quickFix(id, [action]);
      message.success(`已生成新版本 v${v.version_no}（原文件不变）`);
      await reload();
    } catch (e) {
      message.error((e as ApiError).message || "修复失败");
    } finally {
      setFixing(false);
    }
  };

  const onRemap = async (column: string, semantic: string) => {
    await onFix({ type: "remap_semantic", column, params: { semantic } });
  };

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {dataset.name}
        </Typography.Title>
        <Space>
          <Tooltip
            title={
              blocked
                ? "存在阻塞级质量问题，禁止提交分析"
                : projectId
                  ? undefined
                  : "请从项目页进入以开始分析"
            }
          >
            <Button
              type="primary"
              disabled={blocked || dataset.status !== "VALIDATED" || !projectId}
              onClick={() =>
                projectId && navigate(`/projects/${projectId}/analysis/new?dataset=${id}`)
              }
            >
              开始分析
            </Button>
          </Tooltip>
          <Button onClick={() => navigate(-1)}>返回</Button>
        </Space>
      </Space>

      <Descriptions bordered size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label="状态">{dataset.status}</Descriptions.Item>
        <Descriptions.Item label="编码">{dataset.encoding ?? "—"}</Descriptions.Item>
        <Descriptions.Item label="总行数">
          {dataset.preview?.total_rows ?? "—"}
        </Descriptions.Item>
      </Descriptions>

      {dataset.status === "VALIDATING" && (
        <Alert type="info" showIcon message="数据校验中，请稍候…" style={{ marginBottom: 16 }} />
      )}

      {report && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Space size="large">
              <Statistic title="校验结果" value={REPORT_LABEL[report.status]} />
              <Statistic title="阻塞" value={report.blockers} valueStyle={{ color: "#cf1322" }} />
              <Statistic title="警告" value={report.warnings} valueStyle={{ color: "#d48806" }} />
            </Space>
          </Card>

          <Card title="问题清单" style={{ marginBottom: 16 }}>
            <List<Issue>
              dataSource={report.issues}
              locale={{ emptyText: "未发现问题" }}
              renderItem={(issue) => {
                const action = issue.severity === "warning" ? fixActionFor(issue) : null;
                return (
                  <List.Item
                    actions={
                      action
                        ? [
                            <Popconfirm
                              key="fix"
                              title="一键修复将生成新版本，原文件不变"
                              onConfirm={() => void onFix(action)}
                            >
                              <Button size="small" loading={fixing}>
                                一键修复
                              </Button>
                            </Popconfirm>,
                          ]
                        : undefined
                    }
                  >
                    <List.Item.Meta
                      title={
                        <Space>
                          <Tag color={SEVERITY_COLOR[issue.severity]}>
                            {SEVERITY_LABEL[issue.severity]}
                          </Tag>
                          <Typography.Text code>{issue.rule_id}</Typography.Text>
                          {issue.column && <Tag>{issue.column}</Tag>}
                          <span>{issue.message}</span>
                        </Space>
                      }
                      description={issue.suggestion || issue.detail || undefined}
                    />
                  </List.Item>
                );
              }}
            />
          </Card>

          <Card title="列画像" style={{ marginBottom: 16 }}>
            <Table<ColumnProfile>
              rowKey="name"
              size="small"
              dataSource={report.column_profiles}
              pagination={false}
              columns={[
                { title: "列名", dataIndex: "name" },
                { title: "推断类型", dataIndex: "inferred_type" },
                {
                  title: "语义",
                  render: (_, r) => (
                    <Space size={4}>
                      {r.semantic ? (
                        <Tag color="geekblue">
                          {r.semantic}
                          {r.semantic_confidence != null &&
                            ` (${Math.round(r.semantic_confidence * 100)}%)`}
                        </Tag>
                      ) : (
                        "—"
                      )}
                      <Select
                        size="small"
                        placeholder="重映射"
                        style={{ width: 110 }}
                        options={SEMANTIC_OPTIONS.map((s) => ({ value: s, label: s }))}
                        onChange={(v) => void onRemap(r.name, v)}
                      />
                    </Space>
                  ),
                },
                {
                  title: "缺失率",
                  dataIndex: "missing_rate",
                  render: (v: number) => `${(v * 100).toFixed(1)}%`,
                },
                { title: "唯一值", dataIndex: "unique" },
                { title: "异常值", dataIndex: "outliers", render: (v?: number) => v ?? "—" },
                {
                  title: "范围",
                  render: (_, r) => (r.min != null ? `${r.min} ~ ${r.max}` : "—"),
                },
              ]}
            />
          </Card>
        </>
      )}

      {dataset.status === "VALIDATED" && !blocked && id && (
        <>
          <PreprocessPanel
            datasetId={id}
            columns={report?.column_profiles.map((c) => c.name) ?? []}
          />
          <TaskDetectCard
            datasetId={id}
            onConfirm={(taskType) => message.success(`已确认任务类型：${taskType}（将随分析运行快照保存）`)}
          />
        </>
      )}
    </div>
  );
}
