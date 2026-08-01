/** 结果比较页 /runs/:id/comparison（docs/11 §2.4）：性能表/图表/可解释性/模型详情 4 Tab。 */

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
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
  getComparison,
  getRun,
  rerunModel,
  type AnalysisRunDetail,
  type ApiError,
  type ComparisonResult,
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
        <Button style={{ marginTop: 16 }} onClick={() => navigate(-1)}>
          返回
        </Button>
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
            type="primary"
            disabled={run?.status !== "COMPLETED"}
            onClick={() => navigate(`/runs/${id}/reports`)}
          >
            生成报告
          </Button>
          <Button onClick={() => navigate(`/runs/${id}`)}>返回监控</Button>
        </Space>
      </Space>

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
