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
import PreprocessPanel from "./PreprocessPanel";
import TaskDetectCard from "./TaskDetectCard";
import ScreeningCard from "./ScreeningCard";

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
  AI_RECOMMEND: "AI 智能推荐",  // 新增
};

const COLLAPSED_ROWS = 10;

const REPORT_LABEL: Record<QualityReport["status"], string> = {
  PASSED: "通过",
  PASSED_WITH_WARNINGS: "有警告",
  FAILED: "未通过",
};

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

/** 各修复动作的风险说明（docs/05 §5：确认弹窗必须载明风险 + 新版本机制） */
const FIX_RISK: Record<QuickFixAction["type"], string> = {
  drop_column: "该列将从新版本中彻底移除，其中的数据在新版本不可恢复（适用于确认无用的列）。",
  drop_duplicates: "完全重复的数据行将被删除，仅保留一份；若重复本身是真实记录，会造成样本损失。",
  to_missing: "无法识别的取值将被置为缺失，原取值在新版本不可恢复。",
  remap_semantic: "该列的语义将被重新标记，影响任务识别与校验结论。",
  rename_column: "列名将被重命名，需确保新列名与现有列不冲突。",
  pivot_long_to_wide: "长表将被转换为宽表（每个患者一行），重复值将取平均，结构将发生重大改变。",
  winsorize_outliers: "异常值将被截断到 1%-99% 分位数，极端值会被修改但不会被删除。",
  impute_missing: "缺失值将被自动填充（数值列用中位数，分类列用众数），原始缺失状态不可恢复。",
  drop_rows_with_pattern: "匹配指定模式的行将被永久删除，无法恢复。",
  normalize_units: "单位将被标准化转换，原始单位和数值会被修改。",
};

/** 各修复动作的按钮文案 */
const FIX_LABEL: Partial<Record<QuickFixAction["type"], string>> = {
  impute_missing: "一键插补",
  winsorize_outliers: "一键截尾",
  drop_rows_with_pattern: "一键删除",
};

/** 无一键修复动作时的原因与出路（docs/05 §5：行内明示为何不能自动修复） */
const NO_FIX_REASON: Record<string, string> = {
  RV001: "文件编码错误无法读取。请用 Excel「另存为 → CSV UTF-8」或记事本「另存为 → UTF-8」转换后重新上传。",
  RV002: "文件不含数据行。请检查文件内容后重新上传。",
  RV003: "存在重复列名。请在 Excel 中将重复列重命名（如「血压」→「收缩压」、「血压.1」→「舒张压」）后重新上传。",
  RV101: "缺少目标变量（要预测的结果）。若已有结果列但未识别，请在下方列画像」中标记为 Label/Event；否则需在 Excel 中添加结列。",
  RV102: "建议补充推荐字段（如年龄、性别），但非强制。可在 Excel 中添加这些列以支持分层分析。",
  RV302: "日期格式不一致。平台将自动统一为 YYYY-MM-DD 格式，无需手动修复。",
  RV502: "超出临床合理范围，需人工核对是单位错误还是真实极端值。请检查单位是否正确（如 mg/dL vs mmol/L），或在 Excel 中修正录入错误。",
  RV601: "类别过多可能是 ID 列或自由文本。如果是 ID 列，可点击「删除列」；如果需要保留，可考虑合并相似类别。",
  RV701: "类别不平衡是数据特征。平台将自动使用类别权重和 PR-AUC 评估，无需手动修复。",
  RV801: "长表结构（一行一条记录）。需要转换为宽表（一行一个患者）。可使用 Excel 数据透视表，或即将推出的平台向导。",
  RV803: "同一检验项目有多种单位，需统一单位。请在 Excel 中使用公式转换（如 mmol/L × 18 = mg/dL），或等待平台「单位标准化」功能。",
  RV804: "极端值需人工核对。可能是单位错误（多打几个 0）或录入错误，请在 Excel 中检查最大/最小值。",
  RV705: "疑似同一患者多次记录。请确认是多次就诊（正常）还是重复录入（需删除）。",
};

const NO_FIX_DEFAULT = "该问题需人工判断，暂不支持自动修复：请按「建议」列的指引手动处理";

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
          {
            title: "问题",
            dataIndex: "message",
            render: (msg: string, r) => (
              <Space size={4} wrap>
                <span>{msg}</span>
                {r.row_indices && r.row_indices.length > 0 && (
                  <Tooltip
                    title={`影响的行(Excel 行号):${r.row_indices
                      .map((i) => i + 2)
                      .join("、")}${(r.affected_rows ?? 0) > r.row_indices.length ? " …(仅列前 20 行)" : ""}`}
                  >
                    <Tag color="orange" style={{ cursor: "help" }}>
                      {r.affected_rows ?? r.row_indices.length} 行
                    </Tag>
                  </Tooltip>
                )}
              </Space>
            ),
          },
          {
            title: "建议",
            render: (_, r) => {
              const suggestion = r.suggestion || r.detail || "—";
              return (
                <Space direction="vertical" size={0}>
                  {suggestion.length > 100 ? (
                    <Typography.Paragraph
                      ellipsis={{ rows: 2, expandable: true, symbol: "展开" }}
                      style={{ marginBottom: 0, fontSize: 12 }}
                    >
                      {suggestion}
                    </Typography.Paragraph>
                  ) : (
                    <Typography.Text style={{ fontSize: 12 }}>{suggestion}</Typography.Text>
                  )}
                  {r.guidance && (
                    <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setGuide(r)}>
                      查看详细修复指引
                    </Button>
                  )}
                </Space>
              );
            },
          },
          {
            title: "修复方式",
            width: 260,
            render: (_, r) => {
              const action = fixActionFor(r);
              if (!action)
                return (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {NO_FIX_REASON[r.rule_id] ?? NO_FIX_DEFAULT}
                  </Typography.Text>
                );
              return (
                <Popconfirm
                  title="确认一键修复？"
                  description={
                    <div style={{ maxWidth: 320 }}>
                      <div>风险：{FIX_RISK[action.type]}</div>
                      <div style={{ marginTop: 4 }}>
                        修复将生成一个<strong>新的文件版本</strong>
                        （保存在原数据集目录下），你上传的源文件不会被修改；
                        也可以放弃自动修复，改为手动修改源文件后重新上传。
                      </div>
                    </div>
                  }
                  okText="确认修复"
                  cancelText="取消"
                  onConfirm={() => void onFix(action)}
                >
                  <Button size="small" danger={r.severity === "blocker"} loading={fixing}>
                    {FIX_LABEL[action.type] ?? "一键修复"}
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
          {expanded ? "收起" : `展开全部(共 ${issues.length} 条)`}
        </Button>
      )}
      <Modal
        open={!!guide}
        title={
          guide && (
            <Space>
              <Typography.Text code>{guide.rule_id}</Typography.Text>
              <span>详细修复指引{guide.column ? ` — 列「${guide.column}」` : ""}</span>
            </Space>
          )
        }
        footer={null}
        onCancel={() => setGuide(null)}
        width={640}
      >
        <Typography.Paragraph
          style={{ whiteSpace: "pre-wrap", maxHeight: "60vh", overflowY: "auto", marginBottom: 0 }}
        >
          {guide?.guidance}
        </Typography.Paragraph>
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

  const taskLabels: Record<string, string> = {
    regression: "回归分析",
    classification: "分类分析",
    survival: "生存分析",
    time_series: "时间序列",
    eda: "探索性分析",
  };

  return (
    <Alert
      type="info"
      icon={<RobotOutlined />}
      message="AI 智能推荐"
      description={
        <div style={{ marginTop: 8 }}>
          {/* 推荐的分析类型 */}
          {recommended_tasks.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>推荐分析类型：</Typography.Text>
              <Space size={4} style={{ marginTop: 4 }}>
                {recommended_tasks.map((task: string) => (
                  <Tag key={task} color="blue">
                    {taskLabels[task] || task}
                  </Tag>
                ))}
              </Space>
            </div>
          )}

          {/* 推荐的目标列 */}
          {recommended_targets.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>推荐目标列：</Typography.Text>
              {recommended_targets.map((target: any, idx: number) => (
                <div key={idx} style={{ marginTop: 4, marginLeft: 16 }}>
                  <Tag color="green">{target.column}</Tag>
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {target.reason} ({taskLabels[target.task_type] || target.task_type})
                  </Typography.Text>
                </div>
              ))}
            </div>
          )}

          {/* 探索性分析建议 */}
          {eda_suggestions.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <Typography.Text strong>探索性分析建议：</Typography.Text>
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
              <Typography.Text strong>不适合的分析：</Typography.Text>
              {Object.entries(unsuitable_tasks).map(([task, reason]) => (
                <div key={task} style={{ marginTop: 4, marginLeft: 16 }}>
                  <CloseCircleOutlined style={{ color: "#ff4d4f", marginRight: 4 }} />
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    {taskLabels[task] || task}: {reason}
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
      message.success(`已生成新版本 v${v.version_no}（基于 v${currentVersion?.version_no ?? 1} 修复，原文件不变）`);
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
        `已一次性应用 ${allFixableActions.length} 项修复，生成新版本 v${v.version_no}（基于 v${currentVersion?.version_no ?? 1}，原文件不变）`,
      );
      await reload();
    } catch (e) {
      message.error((e as ApiError).message || "批量修复失败");
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

          {/* AI 智能推荐卡片 */}
          <AIRecommendationCard issues={report.issues} />

          <Card
            title={
              <Space style={{ width: "100%", justifyContent: "space-between" }}>
                <span>问题清单</span>
                <Space>
                  {currentVersion && (
                    <Typography.Text type="secondary" style={{ fontWeight: "normal", fontSize: 12 }}>
                      当前基于第 <strong>v{currentVersion.version_no}</strong> 版数据
                      {currentVersion.version_no === 1 ? "（原始上传版）" : "（已修复版）"}
                    </Typography.Text>
                  )}
                  {allFixableActions.length > 0 && (
                    <Popconfirm
                      title="一键修复全部可修复问题"
                      description={
                        <div style={{ maxWidth: 360 }}>
                          <p>将对以下 <strong>{allFixableActions.length}</strong> 项问题一次性修复，生成新版本：</p>
                          <ul style={{ paddingLeft: 16, margin: "4px 0" }}>
                            {allFixableActions.map((a, i) => (
                              <li key={i}>
                                {a.type === "drop_column" && `删除列「${a.column}」（缺失率过高）`}
                                {a.type === "drop_duplicates" && "删除重复行"}
                                {a.type === "to_missing" && `将「${a.column}」非法值置为缺失`}
                              </li>
                            ))}
                          </ul>
                          <p style={{ color: "#cf1322", marginTop: 8 }}>
                            修复后原文件不变，数据变更在新版本中不可撤销。
                          </p>
                        </div>
                      }
                      onConfirm={onFixAll}
                      okText="确认修复全部"
                      cancelText="取消"
                      okButtonProps={{ danger: true }}
                    >
                      <Button
                        type="primary"
                        icon={<ThunderboltOutlined />}
                        loading={fixingAll}
                        disabled={fixing}
                        size="small"
                      >
                        一键修复全部（{allFixableActions.length} 项）
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </Space>
            }
            style={{ marginBottom: 16 }}
          >
            {report.issues.length === 0 ? (
              <Typography.Text type="secondary">未发现问题</Typography.Text>
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
            onConfirm={(taskType) =>
              projectId
                ? navigate(
                    `/projects/${projectId}/analysis/new?dataset=${id}&task=${taskType}`,
                  )
                : message.warning("请从项目页进入以开始分析")
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
