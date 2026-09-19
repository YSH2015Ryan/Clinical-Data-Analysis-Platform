/** 结果比较页 /runs/:id/comparison（docs/11 §2.4）：性能表/图表/可解释性/模型详情 4 Tab。
 * T6.13：性能表 Tab 内嵌「迭代问答」卡（POST /analysis-runs/{id}/iterate），
 * 回答「如果把 X 当协变量会怎样」并可按结构化建议跳转向导重跑。
 */

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Input,
  Row,
  Space,
  Table,
  Tabs,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  downloadRunManifest,
  getComparison,
  getRun,
  iterateRun,
  rerunModel,
  type AnalysisRunDetail,
  type ApiError,
  type ComparisonResult,
  type IterateResponse,
  type ModelMetricsRow,
} from "../api";
import { buildPanels } from "../chartOptions";
import ChartPanel from "../components/ChartPanel";
import { RunStatusTag } from "../components/RunProgressBoard";

const MEDAL: Record<number, string> = { 1: "gold", 2: "silver", 3: "#cd7f32" };

function RankTag({ modelKey, ranking }: { modelKey: string; ranking: string[] }) {
  const rank = ranking.indexOf(modelKey) + 1;
  if (rank >= 1 && rank <= 3) return <Tag color={MEDAL[rank]}>Top{rank}</Tag>;
  return null;
}

function fmtMeanStd(cell: { mean: number; std: number } | undefined): string {
  if (!cell) return "—";
  return `${cell.mean.toFixed(4)}±${cell.std.toFixed(4)}`;
}

function MetricsTable({ cmp }: { cmp: ComparisonResult }) {
  const metricNames = useMemo(() => {
    const names = new Set<string>();
    cmp.table.forEach((row) => Object.keys(row.metrics ?? {}).forEach((k) => names.add(k)));
    return [...names];
  }, [cmp]);

  const columns = [
    { title: "模型", dataIndex: "model_key", key: "model_key",
      render: (key: string) => (
        <Space>
          <Typography.Text strong>{key}</Typography.Text>
          <RankTag modelKey={key} ranking={cmp.ranking} />
        </Space>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      key: "status",
      render: (s: string, row: ModelMetricsRow) =>
        s === "FAILED" ? (
          <Tooltip title={row.error ?? ""}>
            <Tag color="red">FAILED</Tag>
          </Tooltip>
        ) : (
          <Tag color={s === "SUCCESS" ? "green" : "default"}>{s}</Tag>
        ),
    },
    ...metricNames.map((name) => ({
      title: name,
      key: name,
      sorter: (a: ModelMetricsRow, b: ModelMetricsRow) =>
        (a.metrics?.[name]?.mean ?? Number.NaN) - (b.metrics?.[name]?.mean ?? Number.NaN),
      render: (_: unknown, row: ModelMetricsRow) => fmtMeanStd(row.metrics?.[name]),
    })),
    {
      title: "耗时",
      dataIndex: "duration_ms",
      key: "duration_ms",
      sorter: (a: ModelMetricsRow, b: ModelMetricsRow) =>
        (a.duration_ms ?? 0) - (b.duration_ms ?? 0),
      render: (ms: number | null) => (ms == null ? "—" : `${(ms / 1000).toFixed(1)}s`),
    },
  ];

  return (
    <Table
      rowKey="model_key"
      columns={columns}
      dataSource={cmp.table}
      pagination={false}
      size="middle"
    />
  );
}

function RecommendationCards({ cmp }: { cmp: ComparisonResult }) {
  const rec = cmp.recommendation;
  return (
    <Card title="排名与推荐理由" size="small" style={{ marginTop: 16 }}>
      <Space direction="vertical" style={{ width: "100%" }}>
        {rec.top.map((t) => (
          <Alert
            key={t.model_key}
            type={t.rank === 1 ? "success" : "info"}
            message={
              <Space>
                <Tag color={MEDAL[t.rank]}>Top{t.rank}</Tag>
                <Typography.Text strong>{t.model_key}</Typography.Text>
              </Space>
            }
            description={t.reason}
          />
        ))}
        {(rec.not_recommended ?? []).map((n) => (
          <Alert key={n.model_key} type="warning" message={`不推荐 ${n.model_key}`} description={n.reason} />
        ))}
        {rec.formula && (
          <Typography.Text type="secondary">排名公式：{rec.formula}</Typography.Text>
        )}
      </Space>
    </Card>
  );
}

function ChartsGrid({ cmp, kinds }: { cmp: ComparisonResult; kinds: string[] }) {
  const panels = cmp.charts
    .filter((c) => kinds.includes(c.kind))
    .flatMap((c) => buildPanels(c));
  if (panels.length === 0) return <Empty description="暂无图表数据" />;
  return (
    <Row gutter={[16, 16]}>
      {panels.map((p) => (
        <Col key={p.title} xs={24} lg={12}>
          <Card title={p.title} size="small">
            <ChartPanel option={p.option} height={p.height ?? 360} />
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function ModelDetailCards({
  cmp,
  onRerun,
  rerunning,
}: {
  cmp: ComparisonResult;
  onRerun: (key: string) => void;
  rerunning: boolean;
}) {
  return (
    <Row gutter={[16, 16]}>
      {cmp.table.map((row) => (
        <Col key={row.model_key} xs={24} lg={12}>
          <Card
            size="small"
            title={
              <Space>
                {row.model_key}
                <RankTag modelKey={row.model_key} ranking={cmp.ranking} />
              </Space>
            }
            extra={
              <Space>
                <Tag color={row.status === "SUCCESS" ? "green" : row.status === "FAILED" ? "red" : "default"}>
                  {row.status}
                </Tag>
                {row.status === "FAILED" && (
                  <Button size="small" loading={rerunning} onClick={() => onRerun(row.model_key)}>
                    重跑此模型
                  </Button>
                )}
              </Space>
            }
          >
            {row.error && <Alert type="error" message={row.error} style={{ marginBottom: 8 }} />}
            {row.metrics ? (
              <Space direction="vertical" size={4}>
                {Object.entries(row.metrics).map(([name, cell]) => (
                  <Typography.Text key={name}>
                    {name}：{fmtMeanStd(cell)}
                  </Typography.Text>
                ))}
                <Typography.Text type="secondary">
                  耗时：{row.duration_ms != null ? `${(row.duration_ms / 1000).toFixed(1)}s` : "—"}
                </Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="secondary">无指标（模型未成功）</Typography.Text>
            )}
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function IterateCard({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const [result, setResult] = useState<IterateResponse | null>(null);

  const ask = async () => {
    const q = question.trim();
    if (!q) return;
    setAsking(true);
    try {
      setResult(await iterateRun(runId, q));
    } catch (e) {
      message.error((e as ApiError).message || "提问失败");
    } finally {
      setAsking(false);
    }
  };

  const rerunBySuggestion = () => {
    if (!result?.suggestion) return;
    navigate(
      `/projects/${result.project_id}/analysis/new?dataset=${result.dataset_id}`,
      { state: { iterate: result.suggestion } },
    );
  };

  const s = result?.suggestion;
  return (
    <Card title="迭代问答" size="small" style={{ marginTop: 16 }}>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary">
          例如「如果把某列当协变量会怎样」「去掉某列再跑一遍」。回答基于本次运行的真实指标，
          如有可执行的重跑建议会给出结构化方案。
        </Typography.Text>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={question}
            maxLength={500}
            placeholder="输入你的问题…"
            onChange={(e) => setQuestion(e.target.value)}
            onPressEnter={() => void ask()}
          />
          <Button type="primary" loading={asking} onClick={() => void ask()}>
            提问
          </Button>
        </Space.Compact>
        {result && (
          <Alert
            type="info"
            message={
              <Space>
                回答
                <Tag color={result.llm_enhanced ? "blue" : "default"}>
                  {result.llm_enhanced ? "AI 增强" : "规则回答"}
                </Tag>
              </Space>
            }
            description={result.answer}
          />
        )}
        {s && (
          <Alert
            type="success"
            message="重跑建议"
            description={
              <Space direction="vertical" size={4}>
                <Typography.Text>{s.summary}</Typography.Text>
                {s.add_features.length > 0 && (
                  <Space wrap>
                    加入协变量：
                    {s.add_features.map((f) => (
                      <Tag key={f} color="green">
                        {f}
                      </Tag>
                    ))}
                  </Space>
                )}
                {s.drop_features.length > 0 && (
                  <Space wrap>
                    剔除变量：
                    {s.drop_features.map((f) => (
                      <Tag key={f} color="red">
                        {f}
                      </Tag>
                    ))}
                  </Space>
                )}
                {s.selected_models && (
                  <Space wrap>
                    模型集：
                    {s.selected_models.map((m) => (
                      <Tag key={m}>{m}</Tag>
                    ))}
                  </Space>
                )}
                <Button size="small" type="primary" onClick={rerunBySuggestion}>
                  按建议重跑（进入分析向导）
                </Button>
              </Space>
            }
          />
        )}
      </Space>
    </Card>
  );
}

const CHART_TAB_KINDS = ["roc", "calibration", "dca", "confusion_matrix", "km", "cindex_forest", "prediction_scatter"];
const EXPLAIN_TAB_KINDS = ["feature_importance", "hr_forest"];

export default function ComparisonPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<AnalysisRunDetail | null>(null);
  const [cmp, setCmp] = useState<ComparisonResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    if (!id) return;
    Promise.all([getRun(id), getComparison(id)])
      .then(([r, c]) => {
        setRun(r);
        setCmp(c);
      })
      .catch((e) => setLoadError((e as ApiError).message || "比较结果加载失败"));
  }, [id]);

  const onRerun = async (modelKey: string) => {
    if (!id) return;
    setRerunning(true);
    try {
      await rerunModel(id, modelKey);
      message.success(`已重新入队：${modelKey}，跳转运行监控`);
      navigate(`/runs/${id}`);
    } catch (e) {
      message.error((e as ApiError).message || "重跑失败");
    } finally {
      setRerunning(false);
    }
  };

  if (loadError) {
    return (
      <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
        <Alert type="error" message="比较结果不可用" description={loadError} />
        <Space style={{ marginTop: 16 }}>
          <Button onClick={() => navigate(-1)}>返回</Button>
          <Button onClick={() => navigate("/projects")}>返回主页</Button>
        </Space>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1280, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          结果比较 {run && <RunStatusTag status={run.status} />}
        </Typography.Title>
        <Space>
          <Button
            disabled={!id}
            onClick={() =>
              id &&
              void downloadRunManifest(id).catch((e) =>
                message.error((e as ApiError).message || "Manifest 下载失败"),
              )
            }
          >
            下载 Manifest
          </Button>
          <Button
            type="primary"
            disabled={run?.status !== "COMPLETED"}
            onClick={() => navigate(`/runs/${id}/reports`)}
          >
            生成报告
          </Button>
          <Button onClick={() => navigate(`/runs/${id}`)}>返回监控</Button>
          <Button onClick={() => navigate("/projects")}>返回主页</Button>
        </Space>
      </Space>

      {/* §72：探索性模式红色横幅（固定声明，非 LLM 生成） */}
      {run?.exploratory_mode && (
        <Alert
          type="error"
          style={{ marginBottom: 16 }}
          message="探索性分析模式（§72）：检测到重大数据或方法学问题，经研究者确认后继续"
          description={
            <div>
              <div>以下结果仅供方法学筛查参考，不得作为确认性结论。</div>
              <div style={{ marginTop: 4, fontWeight: 600 }}>
                Results should not be interpreted as unbiased predictive performance.
              </div>
            </div>
          }
        />
      )}

      {/* §73-74：大数据集优化模式（结果页同步提示，采样口径影响指标解读） */}
      {run?.integrity?.sampling?.sampled && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message="Large Dataset Mode（优化模式）"
          description={`本次分析基于分层采样数据（${run.integrity.sampling.original_rows.toLocaleString()} → ${run.integrity.sampling.sampled_rows.toLocaleString()} 行，seed=42）；下列指标为采样口径，论文中应如实声明。`}
        />
      )}

      {cmp ? (
        <Tabs
          items={[
            {
              key: "metrics",
              label: "性能表",
              children: (
                <>
                  <MetricsTable cmp={cmp} />
                  <RecommendationCards cmp={cmp} />
                  {id && run?.status === "COMPLETED" && <IterateCard runId={id} />}
                </>
              ),
            },
            {
              key: "charts",
              label: "对比图表",
              children: <ChartsGrid cmp={cmp} kinds={CHART_TAB_KINDS} />,
            },
            {
              key: "explain",
              label: "可解释性",
              children: <ChartsGrid cmp={cmp} kinds={EXPLAIN_TAB_KINDS} />,
            },
            {
              key: "models",
              label: "模型详情",
              children: <ModelDetailCards cmp={cmp} onRerun={onRerun} rerunning={rerunning} />,
            },
          ]}
        />
      ) : (
        <Card>加载中…</Card>
      )}
    </div>
  );
}
