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

/** 规则 → 一键修复动作映射（docs/05 §5；可安全自动化的规则，阻塞/警告均开放）
 *  T6.8:覆盖高发规则——缺失插补、异常值截尾、高基数删列、药敏行删除 */
function fixActionFor(issue: Issue): QuickFixAction | null {
  if (issue.rule_id === "RV201" && issue.column)
    return { type: "impute_missing", column: issue.column, params: { strategy: "auto" } };
  if (issue.rule_id === "RV401" && !issue.column) return { type: "drop_duplicates" };
  if (issue.rule_id === "RV301" && issue.column)
    return { type: "to_missing", column: issue.column };
  if (issue.rule_id === "RV501" && issue.column)
    return { type: "winsorize_outliers", column: issue.column, params: {} };
  if (issue.rule_id === "RV804" && issue.column)
    return { type: "winsorize_outliers", column: issue.column, params: {} };
  if (issue.rule_id === "RV601" && issue.column)
    return { type: "drop_column", column: issue.column };
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
  to_missing: "无法识别的取值将被置为缺失，原始取值在新版本不可恢复。",
  remap_semantic: "该列的语义将被重新标记，影响任务识别与校验结论。",
  rename_column: "列名将被修改，内容不变。",
  pivot_long_to_wide: "长表将透视为宽表，同一患者同一项目多条记录取均值。",
  winsorize_outliers: "超出合理范围的极端值将被截断到边界值，原始取值在新版本不可恢复。",
  impute_missing: "缺失值将被自动填充（数值列用中位数、分类列用众数），填充值不可逆。",
  drop_rows_with_pattern: "匹配模式的行将被删除（如药敏判定记录），样本量会减少。",
  normalize_units: "数值将按换算系数转换并统一单位，原始取值在新版本不可恢复。",
};

/** 各修复动作的按钮文案 */
const FIX_LABEL: Partial<Record<QuickFixAction["type"], string>> = {
  impute_missing: "一键插补",
  winsorize_outliers: "一键截尾",
  drop_rows_with_pattern: "一键删除",
};

/** 无一键修复动作时的原因与出路（docs/05 §5：行内明示为何不能自动修复） */
const NO_FIX_REASON: Record<string, string> = {
  RV001: "文件本身无法读取，无从自动修复：请检查文件格式与编码（建议 UTF-8 CSV）后重新上传",
  RV002: "文件不含数据行，没有可修复的内容：请检查源文件后重新上传",
  RV003: "存在重名列，系统无法判断应保留哪一列：请在源文件中重命名后重新上传",
  RV101: "结局数据无法凭空生成：若结局列已存在但未被识别，请在下方「列画像」把该列角色重映射为 Label/Event；若数据本不含结局（如检验长表），请走项目页「数据准备」向导，关联诊断表生成带结局的宽表",
  RV302: "日期格式混乱，系统无法确定哪种写法才是对的：请在源文件中统一日期格式后重新上传",
  RV502: "取值超出临床合理范围，需人工核对是单位错误还是真实极端值，再决定如何处理",
  RV701: "类别不平衡是数据本身的特征，无法靠修复消除：分析时将自动采用分层交叉验证来缓解",
  RV801: "检验长表需先重塑为宽表才能分析：请走项目页「数据准备」向导",
  RV803: "同一项目存在多种单位，需人工统一单位口径，系统无法猜测哪个单位正确",
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
            render: (_, r) => (
              <Space direction="vertical" size={0}>
                <span>{r.suggestion || r.detail || "—"}</span>
                {r.guidance && (
                  <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setGuide(r)}>
                    查看详细修复指引
                  </Button>
                )}
              </Space>
            ),
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
