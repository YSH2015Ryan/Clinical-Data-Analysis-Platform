import {
  Alert,
  Button,
  Card,
  Descriptions,
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
import { MinusOutlined, PlusOutlined } from "@ant-design/icons";
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

/** 优先级：阻塞 > 警告 > 信息（分组排序用） */
const SEVERITY_RANK: Record<Issue["severity"], number> = {
  blocker: 0,
  warning: 1,
  info: 2,
};

/** 规则类型中文名（与 engines/validation.py 对应；未知规则回退显示规则号） */
const RULE_LABEL: Record<string, string> = {
  RV001: "文件解析失败",
  RV002: "空表",
  RV003: "重复列名",
  RV101: "任务必需字段缺失",
  RV102: "推荐字段缺失",
  RV201: "缺失率过高",
  RV301: "数值列混入非法值",
  RV302: "日期格式不一致",
  RV401: "重复行",
  RV501: "异常值（IQR）",
  RV502: "临床不合理范围",
  RV601: "高基数分类",
  RV701: "类别不平衡",
  RV801: "长表结构",
  RV802: "疑似药敏试验记录",
  RV803: "同一项目多种单位",
  RV804: "数值极端值",
};

const COLLAPSED_ROWS = 10;

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

/** 问题清单分组：按规则类型拆分、组内优先级排序、超 10 行折叠（展开按钮查看全部） */
function IssueGroup({
  ruleId,
  issues,
  fixing,
  onFix,
}: {
  ruleId: string;
  issues: Issue[];
  fixing: boolean;
  onFix: (action: QuickFixAction) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const severity = issues.reduce(
    (top, i) => (SEVERITY_RANK[i.severity] < SEVERITY_RANK[top] ? i.severity : top),
    issues[0].severity,
  );
  const shown = expanded ? issues : issues.slice(0, COLLAPSED_ROWS);
  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={
        <Space>
          <Tag color={SEVERITY_COLOR[severity]}>{SEVERITY_LABEL[severity]}</Tag>
          <Typography.Text code>{ruleId}</Typography.Text>
          <span>{RULE_LABEL[ruleId] ?? "其他问题"}</span>
        </Space>
      }
      extra={<Typography.Text type="secondary">{issues.length} 条</Typography.Text>}
    >
      <Table<Issue>
        rowKey={(r) => `${r.rule_id}-${r.column ?? ""}-${r.message}`}
        size="small"
        dataSource={shown}
        pagination={false}
        columns={[
          {
            title: "级别",
            dataIndex: "severity",
            width: 80,
            render: (s: Issue["severity"]) => (
              <Tag color={SEVERITY_COLOR[s]}>{SEVERITY_LABEL[s]}</Tag>
            ),
          },
          {
            title: "列",
            dataIndex: "column",
            width: 140,
            render: (c?: string) => (c ? <Tag>{c}</Tag> : "—"),
          },
          { title: "问题", dataIndex: "message" },
          {
            title: "建议",
            render: (_, r) => r.suggestion || r.detail || "—",
          },
          {
            title: "操作",
            width: 100,
            render: (_, r) => {
              const action = r.severity === "warning" ? fixActionFor(r) : null;
              return action ? (
                <Popconfirm
                  title="一键修复将生成新版本，原文件不变"
                  onConfirm={() => void onFix(action)}
                >
                  <Button size="small" loading={fixing}>
                    一键修复
                  </Button>
                </Popconfirm>
              ) : null;
            },
          },
        ]}
      />
      {issues.length > COLLAPSED_ROWS && (
        <Button
          type="link"
          size="small"
          icon={expanded ? <MinusOutlined /> : <PlusOutlined />}
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "收起" : `展开全部（共 ${issues.length} 条）`}
        </Button>
      )}
    </Card>
  );
}

/** 按规则类型分组；组间按最高严重级别（阻塞优先）再按条数排序 */
function groupIssues(issues: Issue[]): [string, Issue[]][] {
  const groups = new Map<string, Issue[]>();
  for (const issue of issues) {
    const list = groups.get(issue.rule_id) ?? [];
    list.push(issue);
    groups.set(issue.rule_id, list);
  }
  const rankOf = (list: Issue[]) =>
    Math.min(...list.map((i) => SEVERITY_RANK[i.severity]));
  return [...groups.entries()].sort(
    (a, b) => rankOf(a[1]) - rankOf(b[1]) || b[1].length - a[1].length,
  );
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
            {report.issues.length === 0 ? (
              <Typography.Text type="secondary">未发现问题</Typography.Text>
            ) : (
              groupIssues(report.issues).map(([ruleId, issues]) => (
                <IssueGroup
                  key={ruleId}
                  ruleId={ruleId}
                  issues={issues}
                  fixing={fixing}
                  onFix={onFix}
                />
              ))
            )}
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
