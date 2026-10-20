import {
  Alert,
  Button,
  Card,
  Descriptions,
  Modal,
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
import { MinusOutlined, PlusOutlined, ThunderboltOutlined, RobotOutlined, CheckCircleOutlined, CloseCircleOutlined } from "@ant-design/icons";
import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  getDataset,
  getQualityReport,
  listDatasetVersions,
  quickFix,
  SEMANTIC_OPTIONS,
  type ApiError,
  type ColumnProfile,
  type DatasetDetail,
  type DatasetVersion,
  type Issue,
  type QualityReport,
  type QuickFixAction,
} from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";
import { normalizeLocale } from "../i18n/locale";
import PreprocessPanel from "./PreprocessPanel";
import TaskDetectCard from "./TaskDetectCard";
import ScreeningCard from "./ScreeningCard";
import DatasetInsightCard from "./DatasetInsightCard";

const SEVERITY_COLOR: Record<Issue["severity"], string> = {
  blocker: "error",
  critical: "volcano",
  warning: "warning",
  info: "blue",
};

/** 优先级：阻塞 > 严重 > 警告 > 信息（分组排序用） */
const SEVERITY_RANK: Record<Issue["severity"], number> = {
  blocker: 0,
  critical: 1,
  warning: 2,
  info: 3,
};

function formatNumber(value: number, locale: string): string {
  return new Intl.NumberFormat(normalizeLocale(locale)).format(value);
}

function formatList(values: Array<string | number>, locale: string): string {
  return new Intl.ListFormat(normalizeLocale(locale), {
    style: "long",
    type: "conjunction",
  }).format(values.map(String));
}

const COLLAPSED_ROWS = 10;

const POLL_MS = 2000;

/** 规则 → 一键修复动作映射（docs/05 §5；可安全自动化的规则，阻塞/警告均开放）
 *  T6.8:覆盖高发规则——缺失插补、异常值截尾、高基数删列、药敏行删除 */
function fixActionFor(issue: Issue): QuickFixAction | null {
  // RV201 缺失率过高 → 删除列 或 插补
  if (issue.rule_id === "RV201" && issue.column) {
    // 阻塞级别（>50%）→ 删除列；警告级别（20-50%）→ 插补
    if (issue.severity === "blocker") {
      return { type: "drop_column", column: issue.column };
    }
    return { type: "impute_missing", column: issue.column, params: { strategy: "auto" } };
  }
  // RV401 完全重复行 → 去重
  if (issue.rule_id === "RV401" && !issue.column) return { type: "drop_duplicates" };
  // RV301 非法值 → 转为缺失
  if (issue.rule_id === "RV301" && issue.column)
    return { type: "to_missing", column: issue.column };
  // RV501/RV804 异常值/极端值 → 截尾
  if (issue.rule_id === "RV501" && issue.column)
    return { type: "winsorize_outliers", column: issue.column, params: {} };
  if (issue.rule_id === "RV804" && issue.column)
    return { type: "winsorize_outliers", column: issue.column, params: {} };
  // RV601 高基数列（疑似 ID）→ 删除列
  if (issue.rule_id === "RV601" && issue.column)
    return { type: "drop_column", column: issue.column };
  // RV802 药敏试验记录 → 删除匹配行
  if (issue.rule_id === "RV802")
    return {
      type: "drop_rows_with_pattern",
      column: issue.column ?? undefined,
      params: { pattern: "敏感|耐药|中介" },
    };
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
  const [guide, setGuide] = useState<Issue | null>(null); // T6.1:富文案修复指引弹窗
  const { i18n, t } = useTranslation();
  const severity = issues.reduce(
    (top, i) => (SEVERITY_RANK[i.severity] < SEVERITY_RANK[top] ? i.severity : top),
    issues[0].severity,
  );
  const shown = expanded ? issues : issues.slice(0, COLLAPSED_ROWS);
  const affectedRowsTitle = (issue: Issue): string => {
    const rows = formatList((issue.row_indices ?? []).map((i) => i + 2), i18n.language);
    return (issue.affected_rows ?? 0) > (issue.row_indices?.length ?? 0)
      ? t("dataset.quality.affectedRowsLimited", { rows })
      : t("dataset.quality.affectedRows", { rows });
  };
  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      title={
        <Space>
          <Tag color={SEVERITY_COLOR[severity]}>{t(`dataset.quality.${severity}`)}</Tag>
          <Typography.Text code>{ruleId}</Typography.Text>
          <span>
            {t(`dataset.quality.rules.${ruleId}`, {
              defaultValue: t("dataset.quality.otherIssue"),
            })}
          </span>
        </Space>
      }
      extra={
        <Typography.Text type="secondary">
          {t("dataset.quality.itemCount", { count: issues.length })}
        </Typography.Text>
      }
    >
      <Table<Issue>
        rowKey={(r) => `${r.rule_id}-${r.column ?? ""}-${r.message}`}
        size="small"
        dataSource={shown}
        pagination={false}
        columns={[
          {
            title: t("dataset.quality.columns.severity"),
            dataIndex: "severity",
            width: 80,
            render: (s: Issue["severity"]) => (
              <Tag color={SEVERITY_COLOR[s]}>{t(`dataset.quality.${s}`)}</Tag>
            ),
          },
          {
            title: t("dataset.quality.columns.column"),
            dataIndex: "column",
            width: 140,
            render: (c?: string) => (c ? <Tag>{c}</Tag> : "—"),
          },
          {
            title: t("dataset.quality.columns.problem"),
            dataIndex: "message",
            render: (msg: string, r) => (
              <Space size={4} wrap>
                <span>{msg}</span>
                {r.row_indices && r.row_indices.length > 0 && (
                  <Tooltip title={affectedRowsTitle(r)}>
                    <Tag color="orange" style={{ cursor: "help" }}>
                      {t("dataset.quality.rowCount", {
                        count: r.affected_rows ?? r.row_indices.length,
                      })}
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: t("dataset.quality.columns.suggestion"),
            render: (_, r) => {
              const suggestion = r.suggestion || r.detail || "—";
              return (
                <Space direction="vertical" size={0}>
                  {suggestion.length > 100 ? (
                    <Typography.Paragraph
                      ellipsis={{
                        rows: 2,
                        expandable: true,
                        symbol: t("dataset.quality.expand"),
                      }}
                      style={{ marginBottom: 0, fontSize: 12 }}
                    >
                      {suggestion}
                    </Typography.Paragraph>
                  ) : (
                    <Typography.Text style={{ fontSize: 12 }}>{suggestion}</Typography.Text>
                  )}
                  {r.guidance && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setGuide(r)}>
                      {t("dataset.quality.viewGuide")}
                    </Button>
                  )}
                </Space>
              );
            },
          },
          {
            title: t("dataset.quality.columns.fix"),
            width: 260,
            render: (_, r) => {
              const action = fixActionFor(r);
              if (!action)
                return (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t(`dataset.quality.noFix.${r.rule_id}`, {
                      defaultValue: t("dataset.quality.noFix.default"),
                    })}
                  </Typography.Text>
                );
              return (
                <Popconfirm
                  title={t("dataset.quality.confirmFixTitle")}
                  description={
                    <div style={{ maxWidth: 320 }}>
                      <div>
                        {t("dataset.quality.riskDescription", {
                          risk: t(`dataset.quality.fixRisk.${action.type}`),
                        })}
                      </div>
                      <div style={{ marginTop: 4 }}>{t("dataset.quality.fixCreatesVersion")}</div>
                    </div>
                  }
                  okText={t("dataset.quality.confirmFix")}
                  cancelText={t("common.action.cancel")}
                  onConfirm={() => void onFix(action)}
                >
                  <Button size="small" danger={r.severity === "blocker"} loading={fixing}>
                    {t(`dataset.quality.fixLabels.${action.type}`, {
                      defaultValue: t("dataset.quality.quickFix"),
                    })}
                  </Button>
                </Popconfirm>
              );
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
          {expanded
            ? t("dataset.quality.collapse")
            : t("dataset.quality.expandAll", { count: issues.length })}
        </Button>
      )}
      <Modal
        open={!!guide}
        title={
          guide && (
            <Space>
              <Typography.Text code>{guide.rule_id}</Typography.Text>
              <span>
                {guide.column
                  ? t("dataset.quality.guideTitleWithColumn", { column: guide.column })
                  : t("dataset.quality.guideTitle")}
              </span>
            </Space>
          )
        }
        footer={null}
        onCancel={() => setGuide(null)}
        width={640}
      >
        {guide?.fix_guidance ? (
          // P2-3 结构化闭环：问题 → 影响 → 修法（一键动作直接在此执行）
          <div>
            <Typography.Paragraph style={{ marginBottom: 8 }}>
              {t("dataset.quality.problemStatement", {
                problem: guide.fix_guidance.problem,
              })}
            </Typography.Paragraph>
            <Typography.Paragraph style={{ marginBottom: 12 }}>
              {t("dataset.quality.impactStatement", {
                impact: guide.fix_guidance.impact,
              })}
            </Typography.Paragraph>
            <Typography.Text strong>{t("dataset.quality.methodsHeading")}</Typography.Text>
            <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
              {guide.fix_guidance.methods.map((m, i) => (
                <Card key={i} size="small">
                  <Space style={{ width: "100%", justifyContent: "space-between" }}>
                    <div>
                      <Typography.Text strong>{i + 1}. {m.label}</Typography.Text>
                      <div style={{ fontSize: 12, color: "rgba(0,0,0,0.55)", marginTop: 4 }}>
                        {m.description}
                      </div>
                    </div>
                    {m.action && (
                      <Popconfirm
                        title={t("dataset.quality.confirmExecuteTitle", { label: m.label })}
                        description={
                          <div style={{ maxWidth: 320 }}>
                            {m.risk && (
                              <div>{t("dataset.quality.riskDescription", { risk: m.risk })}</div>
                            )}
                            <div style={{ marginTop: 4 }}>
                              {t("dataset.quality.executeCreatesVersion")}
                            </div>
                          </div>
                        }
                        okText={t("dataset.quality.confirmExecute")}
                        cancelText={t("common.action.cancel")}
                        onConfirm={async () => {
                          setGuide(null);
                          await onFix({
                            type: m.action!.type,
                            column: m.action!.column ?? undefined,
                            params: m.action!.params,
                          });
                        }}
                      >
                        <Button size="small" type="primary" loading={fixing}>
                          {t("dataset.quality.execute")}
                        </Button>
                      </Popconfirm>
                    )}
                  </Space>
                </Card>
              ))}
            </Space>
          </div>
        ) : (
          <Typography.Paragraph
            style={{ whiteSpace: "pre-wrap", maxHeight: "60vh", overflowY: "auto", marginBottom: 0 }}
          >
            {guide?.guidance}
          </Typography.Paragraph>
        )}
      </Modal>
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

/** AI 智能推荐卡片 */
function AIRecommendationCard({ issues }: { issues: Issue[] }) {
  const { t } = useTranslation();
  const aiIssue = issues.find((i) => i.rule_id === "AI_RECOMMEND");
  if (!aiIssue || !aiIssue.detail) return null;

  const detail = (typeof aiIssue.detail === "string"
    ? JSON.parse(aiIssue.detail)
    : aiIssue.detail) as {
    recommended_tasks?: string[];
    recommended_targets?: { column: string; reason: string; task_type: string }[];
    unsuitable_tasks?: Record<string, string>;
    eda_suggestions?: string[];
    can_start_modeling?: boolean;
  };
  const {
    recommended_tasks = [],
    recommended_targets = [],
    unsuitable_tasks = {},
    eda_suggestions = [],
    can_start_modeling = false,
  } = detail;

  const taskKeys: Record<string, string> = {
    regression: "dataset.ai.tasks.regression",
    classification: "dataset.ai.tasks.classification",
    survival: "dataset.ai.tasks.survival",
    time_series: "dataset.ai.tasks.timeSeries",
    eda: "dataset.ai.tasks.eda",
  };
  const taskLabel = (task: string) => (taskKeys[task] ? t(taskKeys[task]) : task);

  return (
    <Alert
      type="info"
      icon={<RobotOutlined />}
      message={t("dataset.ai.title")}
      description={
        <div style={{ marginTop: 8 }}>
          {/* 推荐的分析类型 */}
          {recommended_tasks.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>{t("dataset.ai.recommendedTasks")}</Typography.Text>
              <Space size={4} style={{ marginTop: 4 }}>
                {recommended_tasks.map((task: string) => (
                  <Tag key={task} color="blue">
                    {taskLabel(task)}
                  </Tag>
                ))}
              </Space>
            </div>
          )}

          {/* 推荐的目标列 */}
          {recommended_targets.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>{t("dataset.ai.recommendedTargets")}</Typography.Text>
              {recommended_targets.map((target: any, idx: number) => (
                <div key={idx} style={{ marginTop: 4, marginLeft: 16 }}>
                  <Tag color="green">{target.column}</Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t("dataset.ai.targetReason", {
                      reason: target.reason,
                      task: taskLabel(target.task_type),
                    })}
                  </Typography.Text>
                </div>
              ))}
            </div>
          )}

          {/* 探索性分析建议 */}
          {eda_suggestions.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>{t("dataset.ai.edaSuggestions")}</Typography.Text>
              <div style={{ marginTop: 4, marginLeft: 16 }}>
                {eda_suggestions.map((suggestion: string, idx: number) => (
                  <Tag key={idx} color="cyan" style={{ marginBottom: 4 }}>
                    {suggestion}
                  </Tag>
                ))}
              </div>
            </div>
          )}

          {/* 不适合的分析类型 */}
          {Object.keys(unsuitable_tasks).length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>{t("dataset.ai.unsuitableTasks")}</Typography.Text>
              {Object.entries(unsuitable_tasks).map(([task, reason]) => (
                <div key={task} style={{ marginTop: 4, marginLeft: 16 }}>
                  <CloseCircleOutlined style={{ color: "#ff4d4f", marginRight: 4 }} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {t("dataset.ai.unsuitableEntry", {
                      task: taskLabel(task),
                      reason,
                    })}
                  </Typography.Text>
                </div>
              ))}
            </div>
          )}

          {/* 整体评估 */}
          <div style={{ marginTop: 12, padding: "8px 12px", background: "#f0f5ff", borderRadius: 4 }}>
            <Typography.Text style={{ fontSize: 12 }}>
              {can_start_modeling ? (
                <><CheckCircleOutlined style={{ color: "#52c41a", marginRight: 4 }} /> {aiIssue.suggestion}</>
              ) : (
                <>{aiIssue.suggestion}</>
              )}
            </Typography.Text>
          </div>
        </div>
      }
      style={{ marginBottom: 16 }}
    />
  );
}

export default function DatasetDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [report, setReport] = useState<QualityReport | null>(null);
  const [currentVersion, setCurrentVersion] = useState<DatasetVersion | null>(null);
  const [fixing, setFixing] = useState(false);
  const [fixingAll, setFixingAll] = useState(false);
  const navigate = useNavigate();
  const location = useLocation();
  const { i18n, t } = useTranslation();
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
        // 加载版本信息，用于显示"基于第 vN 版修复"
        try {
          const versions = await listDatasetVersions(id);
          setCurrentVersion(versions[0] ?? null); // 最新版排第一
        } catch {
          setCurrentVersion(null);
        }
      }
    } catch (e) {
      message.error((e as ApiError).message || t("common.error.load"));
    }
  }, [id, t]);

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
      message.success(
        t("dataset.quality.fixSuccess", {
          newVersion: v.version_no,
          baseVersion: currentVersion?.version_no ?? 1,
        }),
      );
      await reload();
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.quality.fixFailed"));
    } finally {
      setFixing(false);
    }
  };

  const onRemap = async (column: string, semantic: string) => {
    await onFix({ type: "remap_semantic", column, params: { semantic } });
  };

  // 收集所有可自动修复的动作（每个规则组取第一条 action 即可，因为同规则操作幂等）
  const allFixableActions: QuickFixAction[] = report
    ? (() => {
        const seen = new Set<string>();
        const actions: QuickFixAction[] = [];
        for (const issue of report.issues) {
          const action = fixActionFor(issue);
          if (!action) continue;
          // drop_column 按列去重，drop_duplicates 只需一次
          const key = action.type === "drop_column" ? `drop_column:${action.column ?? ""}` : action.type;
          if (!seen.has(key)) {
            seen.add(key);
            actions.push(action);
          }
        }
        return actions;
      })()
    : [];

  const onFixAll = async () => {
    if (!id || allFixableActions.length === 0) return;
    setFixingAll(true);
    try {
      const v = await quickFix(id, allFixableActions);
      message.success(
        t("dataset.quality.fixAllSuccess", {
          count: allFixableActions.length,
          newVersion: v.version_no,
          baseVersion: currentVersion?.version_no ?? 1,
        }),
      );
      await reload();
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.quality.fixAllFailed"));
    } finally {
      setFixingAll(false);
    }
  };

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {dataset.name}
        </Typography.Title>
        <Space>
          <LanguageSwitcher />
          <Tooltip
            title={
              blocked
                ? t("dataset.detail.blockedTooltip")
                : projectId
                  ? undefined
                  : t("dataset.detail.projectRequiredTooltip")
            }
          >
            <Button
              type="primary"
              disabled={blocked || dataset.status !== "VALIDATED" || !projectId}
              onClick={() =>
                projectId && navigate(`/projects/${projectId}/analysis/new?dataset=${id}`)
              }
            >
              {t("dataset.detail.startAnalysis")}
            </Button>
          </Tooltip>
          <Button onClick={() => navigate(-1)}>{t("dataset.detail.back")}</Button>
        </Space>
      </Space>

      <Descriptions bordered size="small" style={{ marginBottom: 16 }}>
        <Descriptions.Item label={t("dataset.detail.status")}>
          {t(`common.datasetStatus.${dataset.status}`)}
        </Descriptions.Item>
        <Descriptions.Item label={t("dataset.detail.encoding")}>
          {dataset.encoding ?? "—"}
        </Descriptions.Item>
        <Descriptions.Item label={t("dataset.detail.totalRows")}>
          {dataset.preview?.total_rows != null
            ? formatNumber(dataset.preview.total_rows, i18n.language)
            : "—"}
          {/* §74 Large Dataset Mode：>100k 行进入优化模式（分析时自动分层采样） */}
          {(dataset.preview?.total_rows ?? 0) > 100000 && (
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {t("dataset.detail.largeDatasetMode", {
                count: formatNumber(dataset.preview?.total_rows ?? 0, i18n.language),
                sampleSize: formatNumber(100000, i18n.language),
              })}
            </Tag>
          )}
        </Descriptions.Item>
      </Descriptions>

      {dataset.status === "VALIDATING" && (
        <Alert
          type="info"
          showIcon
          message={t("dataset.detail.validating")}
          style={{ marginBottom: 16 }}
        />
      )}

      {dataset.status === "VALIDATED" && id && <DatasetInsightCard datasetId={id} />}

      {report && (
        <>
          <Card style={{ marginBottom: 16 }}>
            <Space size="large">
              <Statistic
                title={t("dataset.detail.reportStatus")}
                value={t(`dataset.quality.report.${report.status}`)}
              />
              <Statistic
                title={t("dataset.quality.blocker")}
                value={report.blockers}
                valueStyle={{ color: "#cf1322" }}
              />
              <Statistic
                title={t("dataset.quality.critical")}
                value={report.criticals ?? 0}
                valueStyle={{ color: "#d4380d" }}
              />
              <Statistic
                title={t("dataset.quality.warning")}
                value={report.warnings}
                valueStyle={{ color: "#d48806" }}
              />
            </Space>
          </Card>

          {/* AI 智能推荐卡片 */}
          <AIRecommendationCard issues={report.issues} />

          <Card
            title={
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <span>{t("dataset.detail.issueList")}</span>
                <Space>
                  {currentVersion && (
                    <Typography.Text type="secondary" style={{ fontWeight: "normal", fontSize: 12 }}>
                      {t(
                        currentVersion.version_no === 1
                          ? "dataset.detail.currentVersionOriginal"
                          : "dataset.detail.currentVersionFixed",
                        { version: currentVersion.version_no },
                      )}
                    </Typography.Text>
                  )}
                  {allFixableActions.length > 0 && (
                    <Popconfirm
                      title={t("dataset.quality.fixAllTitle")}
                      description={
                        <div style={{ maxWidth: 360 }}>
                          <p>
                            {t("dataset.quality.fixAllDescription", {
                              count: allFixableActions.length,
                            })}
                          </p>
                          <ul style={{ paddingLeft: 16, margin: "4px 0" }}>
                            {allFixableActions.map((a, i) => (
                              <li key={i}>
                                {a.type === "drop_column" &&
                                  t("dataset.quality.fixAllItems.dropColumn", {
                                    column: a.column,
                                  })}
                                {a.type === "drop_duplicates" &&
                                  t("dataset.quality.fixAllItems.dropDuplicates")}
                                {a.type === "to_missing" &&
                                  t("dataset.quality.fixAllItems.toMissing", {
                                    column: a.column,
                                  })}
                              </li>
                            ))}
                          </ul>
                          <p style={{ color: "#cf1322", marginTop: 8 }}>
                            {t("dataset.quality.fixAllWarning")}
                          </p>
                        </div>
                      }
                      onConfirm={onFixAll}
                      okText={t("dataset.quality.confirmFixAll")}
                      cancelText={t("common.action.cancel")}
                      okButtonProps={{ danger: true }}
                    >
                      <Button
                        type="primary"
                        icon={<ThunderboltOutlined />}
                        loading={fixingAll}
                        disabled={fixing}
                        size="small"
                      >
                        {t("dataset.quality.fixAllButton", {
                          count: allFixableActions.length,
                        })}
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {report.issues.length === 0 ? (
              <Typography.Text type="secondary">{t("dataset.detail.noIssues")}</Typography.Text>
            ) : (
              groupIssues(report.issues.filter(i => i.rule_id !== "AI_RECOMMEND")).map(([ruleId, issues]) => (
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

          <Card title={t("dataset.detail.dictionaryTitle")} style={{ marginBottom: 16 }}>
            <Table<ColumnProfile>
              rowKey="name"
              size="small"
              dataSource={report.column_profiles}
              pagination={false}
              columns={[
                { title: t("dataset.detail.columns.columnName"), dataIndex: "name" },
                { title: t("dataset.detail.columns.inferredType"), dataIndex: "inferred_type" },
                {
                  title: t("dataset.detail.columns.semantic"),
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
                        placeholder={t("dataset.detail.remapPlaceholder")}
                        style={{ width: 110 }}
                        options={SEMANTIC_OPTIONS.map((s) => ({ value: s, label: s }))}
                        onChange={(v) => void onRemap(r.name, v)}
                      />
                    </Space>
                  ),
                },
                {
                  title: t("dataset.detail.columns.unit"),
                  dataIndex: "unit",
                  render: (v?: string | null) => v ?? "—",
                },
                {
                  title: t("dataset.detail.columns.clinicalRole"),
                  dataIndex: "clinical_role",
                  render: (v?: string) =>
                    v ? (
                      <Tag color={v === "outcome" ? "volcano" : undefined}>
                        {t(`dataset.detail.clinicalRoles.${v}`, { defaultValue: v })}
                      </Tag>
                    ) : (
                      "—"
                    ),
                },
                {
                  title: t("dataset.detail.columns.timepoint"),
                  dataIndex: "timepoint",
                  render: (v?: string) => v ?? "—",
                },
                {
                  title: t("dataset.detail.columns.missingRate"),
                  dataIndex: "missing_rate",
                  render: (v: number) => `${(v * 100).toFixed(1)}%`,
                },
                { title: t("dataset.detail.columns.unique"), dataIndex: "unique" },
                {
                  title: t("dataset.detail.columns.outliers"),
                  dataIndex: "outliers",
                  render: (v?: number) => v ?? "—",
                },
                {
                  title: t("dataset.detail.columns.range"),
                  render: (_, r) => (r.min != null ? `${r.min} ~ ${r.max}` : "—"),
                },
                {
                  title: t("dataset.detail.columns.referenceRange"),
                  render: (_, r) =>
                    r.reference_range ? (
                      <Space size={4}>
                        {`${r.reference_range.low} ~ ${r.reference_range.high}${
                          r.reference_range.unit ? ` ${r.reference_range.unit}` : ""
                        }`}
                        <Tag
                          color={
                            (
                              {
                                domain_knowledge: "blue",
                                dataset_inferred: "default",
                                user_defined: "green",
                              } as Record<string, string>
                            )[r.reference_range.source]
                          }
                        >
                          {t(`dataset.detail.referenceSources.${r.reference_range.source}`, {
                            defaultValue: r.reference_range.source,
                          })}
                        </Tag>
                      </Space>
                    ) : (
                      "—"
                    ),
                },
                {
                  title: t("dataset.detail.columns.warnings"),
                  render: (_, r) =>
                    r.warnings && r.warnings.length > 0 ? (
                      <Space size={4} wrap>
                        {r.warnings.map((w) => (
                          <Tag key={w} color="orange">
                            {w}
                          </Tag>
                        ))}
                      </Space>
                    ) : (
                      t("dataset.detail.noWarnings")
                    ),
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
            onConfirm={(taskType) =>
              projectId
                ? navigate(
                    `/projects/${projectId}/analysis/new?dataset=${id}&task=${taskType}`,
                  )
                : message.warning(t("dataset.detail.projectRequiredTooltip"))
            }
          />
          <ScreeningCard
            datasetId={id}
            columns={report?.column_profiles.map((c) => c.name) ?? []}
          />
        </>
      )}
    </div>
  );
}
