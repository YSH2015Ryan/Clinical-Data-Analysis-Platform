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
import { useTranslation } from "react-i18next";
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
import LanguageSwitcher from "../components/LanguageSwitcher";
import { RunStatusTag } from "../components/RunProgressBoard";
import { formatNumber } from "../i18n/locale";

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
  const { t } = useTranslation();
  const metricNames = useMemo(() => {
    const names = new Set<string>();
    cmp.table.forEach((row) => Object.keys(row.metrics ?? {}).forEach((k) => names.add(k)));
    return [...names];
  }, [cmp]);

  const columns = [
    {
      title: t("comparison.table.model"),
      dataIndex: "model_key",
      key: "model_key",
      render: (key: string) => (
        <Space>
          <Typography.Text strong>{key}</Typography.Text>
          <RankTag modelKey={key} ranking={cmp.ranking} />
        </Space>
      ),
    },
    {
      title: t("comparison.table.status"),
      dataIndex: "status",
      key: "status",
      render: (s: ModelMetricsRow["status"], row: ModelMetricsRow) =>
        s === "FAILED" ? (
          <Tooltip title={row.error ?? ""}>
            <Tag color="red">{t("run.modelStatus.FAILED")}</Tag>
          </Tooltip>
        ) : (
          <Tag color={s === "SUCCESS" ? "green" : "default"}>{t(`run.modelStatus.${s}`)}</Tag>
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
      title: t("comparison.table.duration"),
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
  const { t } = useTranslation();
  const rec = cmp.recommendation;
  return (
    <Card title={t("comparison.recommendation.title")} size="small" style={{ marginTop: 16 }}>
      <Space direction="vertical" style={{ width: "100%" }}>
        {rec.top.map((item) => (
          <Alert
            key={item.model_key}
            type={item.rank === 1 ? "success" : "info"}
            message={
              <Space>
                <Tag color={MEDAL[item.rank]}>Top{item.rank}</Tag>
                <Typography.Text strong>{item.model_key}</Typography.Text>
              </Space>
            }
            description={item.reason}
          />
        ))}
        {(rec.not_recommended ?? []).map((n) => (
          <Alert
            key={n.model_key}
            type="warning"
            message={t("comparison.recommendation.notRecommended", { model: n.model_key })}
            description={n.reason}
          />
        ))}
        {rec.formula && (
          <Typography.Text type="secondary">
            {t("comparison.recommendation.formula", { formula: rec.formula })}
          </Typography.Text>
        )}
      </Space>
    </Card>
  );
}

function ChartsGrid({ cmp, kinds }: { cmp: ComparisonResult; kinds: string[] }) {
  const { t } = useTranslation();
  const panels = useMemo(
    () => cmp.charts.filter((c) => kinds.includes(c.kind)).flatMap((c) => buildPanels(c, t)),
    [cmp, kinds, t],
  );
  if (panels.length === 0) return <Empty description={t("comparison.chartsEmpty")} />;
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
  const { t } = useTranslation();
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
                <Tag
                  color={
                    row.status === "SUCCESS" ? "green" : row.status === "FAILED" ? "red" : "default"
                  }
                >
                  {t(`run.modelStatus.${row.status}`)}
                </Tag>
                {row.status === "FAILED" && (
                  <Button size="small" loading={rerunning} onClick={() => onRerun(row.model_key)}>
                    {t("comparison.details.rerun")}
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
                    {name}: {fmtMeanStd(cell)}
                  </Typography.Text>
                ))}
                <Typography.Text type="secondary">
                  {t("comparison.table.duration")}:{" "}
                  {row.duration_ms != null ? `${(row.duration_ms / 1000).toFixed(1)}s` : "—"}
                </Typography.Text>
              </Space>
            ) : (
              <Typography.Text type="secondary">{t("comparison.details.noMetrics")}</Typography.Text>
            )}
          </Card>
        </Col>
      ))}
    </Row>
  );
}

function IterateCard({ runId }: { runId: string }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
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
      message.error((e as ApiError).message || t("comparison.iterate.askFailed"));
    } finally {
      setAsking(false);
    }
  };

  const rerunBySuggestion = () => {
    if (!result?.suggestion) return;
    navigate(`/projects/${result.project_id}/analysis/new?dataset=${result.dataset_id}`, {
      state: { iterate: result.suggestion },
    });
  };

  const s = result?.suggestion;
  return (
    <Card title={t("comparison.iterate.title")} size="small" style={{ marginTop: 16 }}>
      <Space direction="vertical" style={{ width: "100%" }}>
        <Typography.Text type="secondary">{t("comparison.iterate.description")}</Typography.Text>
        <Space.Compact style={{ width: "100%" }}>
          <Input
            value={question}
            maxLength={500}
            placeholder={t("comparison.iterate.placeholder")}
            onChange={(e) => setQuestion(e.target.value)}
            onPressEnter={() => void ask()}
          />
          <Button type="primary" loading={asking} onClick={() => void ask()}>
            {t("comparison.iterate.ask")}
          </Button>
        </Space.Compact>
        {result && (
          <Alert
            type="info"
            message={
              <Space>
                {t("comparison.iterate.answer")}
                <Tag color={result.llm_enhanced ? "blue" : "default"}>
                  {result.llm_enhanced
                    ? t("comparison.iterate.aiEnhanced")
                    : t("comparison.iterate.ruleAnswer")}
                </Tag>
              </Space>
            }
            description={result.answer}
          />
        )}
        {s && (
          <Alert
            type="success"
            message={t("comparison.iterate.suggestion")}
            description={
              <Space direction="vertical" size={4}>
                <Typography.Text>{s.summary}</Typography.Text>
                {s.add_features.length > 0 && (
                  <Space wrap>
                    {t("comparison.iterate.addFeatures")}
                    {s.add_features.map((f) => (
                      <Tag key={f} color="green">
                        {f}
                      </Tag>
                    ))}
                  </Space>
                )}
                {s.drop_features.length > 0 && (
                  <Space wrap>
                    {t("comparison.iterate.dropFeatures")}
                    {s.drop_features.map((f) => (
                      <Tag key={f} color="red">
                        {f}
                      </Tag>
                    ))}
                  </Space>
                )}
                {s.selected_models && (
                  <Space wrap>
                    {t("comparison.iterate.models")}
                    {s.selected_models.map((m) => (
                      <Tag key={m}>{m}</Tag>
                    ))}
                  </Space>
                )}
                <Button size="small" type="primary" onClick={rerunBySuggestion}>
                  {t("comparison.iterate.rerunSuggested")}
                </Button>
              </Space>
            }
          />
        )}
      </Space>
    </Card>
  );
}

const CHART_TAB_KINDS = [
  "roc",
  "calibration",
  "dca",
  "confusion_matrix",
  "km",
  "cindex_forest",
  "prediction_scatter",
];
const EXPLAIN_TAB_KINDS = ["feature_importance", "hr_forest"];

export default function ComparisonPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<AnalysisRunDetail | null>(null);
  const [cmp, setCmp] = useState<ComparisonResult | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rerunning, setRerunning] = useState(false);
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();

  useEffect(() => {
    if (!id) return;
    Promise.all([getRun(id), getComparison(id)])
      .then(([r, c]) => {
        setRun(r);
        setCmp(c);
      })
      .catch((e) => setLoadError((e as ApiError).message || t("comparison.loadFailed")));
  }, [id, t]);

  const onRerun = async (modelKey: string) => {
    if (!id) return;
    setRerunning(true);
    try {
      await rerunModel(id, modelKey);
      message.success(t("comparison.rerunQueued", { model: modelKey }));
      navigate(`/runs/${id}`);
    } catch (e) {
      message.error((e as ApiError).message || t("comparison.rerunFailed"));
    } finally {
      setRerunning(false);
    }
  };

  if (loadError) {
    return (
      <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
        <Alert type="error" message={t("comparison.unavailable")} description={loadError} />
        <Space style={{ marginTop: 16 }}>
          <Button onClick={() => navigate(-1)}>{t("run.monitor.back")}</Button>
          <Button onClick={() => navigate("/projects")}>{t("run.monitor.backHome")}</Button>
        </Space>
      </div>
    );
  }

  return (
    <div style={{ maxWidth: 1280, margin: "24px auto", padding: "0 16px" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("comparison.title")} {run && <RunStatusTag status={run.status} />}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          <Button
            disabled={!id}
            onClick={() =>
              id &&
              void downloadRunManifest(id).catch((e) =>
                message.error((e as ApiError).message || t("comparison.manifestFailed")),
              )
            }
          >
            {t("comparison.downloadManifest")}
          </Button>
          <Button
            type="primary"
            disabled={run?.status !== "COMPLETED"}
            onClick={() => navigate(`/runs/${id}/reports`)}
          >
            {t("comparison.generateReport")}
          </Button>
          <Button onClick={() => navigate(`/runs/${id}`)}>{t("comparison.backMonitor")}</Button>
          <Button onClick={() => navigate("/projects")}>{t("run.monitor.backHome")}</Button>
        </Space>
      </Space>

      {/* §72：探索性模式红色横幅（固定声明，非 LLM 生成） */}
      {run?.exploratory_mode && (
        <Alert
          type="error"
          style={{ marginBottom: 16 }}
          message={t("comparison.exploratoryTitle")}
          description={
            <div>
              <div>{t("comparison.exploratoryBody")}</div>
              <div style={{ marginTop: 4, fontWeight: 600 }}>
                {t("comparison.exploratoryStatement")}
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
          message={t("comparison.samplingTitle")}
          description={t("comparison.samplingBody", {
            original: formatNumber(run.integrity.sampling.original_rows, i18n.language),
            sampled: formatNumber(run.integrity.sampling.sampled_rows, i18n.language),
          })}
        />
      )}

      {cmp ? (
        <Tabs
          items={[
            {
              key: "metrics",
              label: t("comparison.tabs.metrics"),
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
              label: t("comparison.tabs.charts"),
              children: <ChartsGrid cmp={cmp} kinds={CHART_TAB_KINDS} />,
            },
            {
              key: "explain",
              label: t("comparison.tabs.explain"),
              children: <ChartsGrid cmp={cmp} kinds={EXPLAIN_TAB_KINDS} />,
            },
            {
              key: "models",
              label: t("comparison.tabs.models"),
              children: <ModelDetailCards cmp={cmp} onRerun={onRerun} rerunning={rerunning} />,
            },
          ]}
        />
      ) : (
        <Card>{t("comparison.loading")}</Card>
      )}
    </div>
  );
}
