/** 数据体检卡（P2-2，docs/08 §3.2 阶段 A）：上传后自动产出的 EDA + 体检结论。
 *
 * 数据来源 GET /datasets/{id}/insight；全部数值为后端引擎真实计算结果，
 * 前端只做可视化（直方图/Top 计数/相关性对/EPV），不做任何推断。
 */

import { Alert, Card, Col, Collapse, Row, Space, Statistic, Table, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import {
  getDatasetInsight,
  type ApiError,
  type DatasetInsight,
  type EdaDistribution,
} from "../api";
import ChartPanel from "../components/ChartPanel";

const TASK_LABEL: Record<string, string> = {
  survival: "生存分析",
  classification: "分类/风险预测",
  regression: "回归/预后",
  eda: "探索性分析",
};

const RESEARCH_TYPE_LABEL: Record<string, string> = {
  cohort: "队列/生存研究",
  case_control: "病例-对照研究",
  cross_sectional: "横断面研究",
  time_series: "时序研究",
};

const ACTION_LABEL: Record<string, string> = {
  impute_missing: "缺失插补",
  winsorize_outliers: "异常值截尾",
  to_missing: "非法值置缺失",
};

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

/** 单列分布小图：连续→直方图，分类→Top 计数条形图 */
function DistributionChart({ dist }: { dist: EdaDistribution }) {
  if (dist.kind === "continuous" && dist.histogram) {
    const { counts, bin_edges } = dist.histogram;
    const labels = counts.map((_, i) => {
      const lo = bin_edges[i];
      const hi = bin_edges[i + 1];
      return lo != null && hi != null ? `${lo.toFixed(1)}~${hi.toFixed(1)}` : `${i}`;
    });
    return (
      <ChartPanel
        height={180}
        option={{
          grid: { left: 40, right: 8, top: 8, bottom: 40 },
          xAxis: {
            type: "category",
            data: labels,
            axisLabel: { rotate: 45, fontSize: 10 },
          },
          yAxis: { type: "value" },
          series: [{ type: "bar", data: counts, itemStyle: { color: "#5B8FF9" } }],
          tooltip: { trigger: "axis" },
        }}
      />
    );
  }
  if (dist.kind === "categorical" && dist.top_counts) {
    return (
      <ChartPanel
        height={180}
        option={{
          grid: { left: 60, right: 16, top: 8, bottom: 24 },
          xAxis: { type: "value" },
          yAxis: {
            type: "category",
            data: dist.top_counts.map((c) => c.value).reverse(),
            axisLabel: { fontSize: 10 },
          },
          series: [
            {
              type: "bar",
              data: dist.top_counts.map((c) => c.count).reverse(),
              itemStyle: { color: "#61DDAA" },
            },
          ],
          tooltip: { trigger: "axis" },
        }}
      />
    );
  }
  return null;
}

export default function DatasetInsightCard({ datasetId }: { datasetId: string }) {
  const [insight, setInsight] = useState<DatasetInsight | null>(null);
  const [pending, setPending] = useState(true);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const data = await getDatasetInsight(datasetId);
        if (!stop) {
          setInsight(data);
          setPending(false);
        }
      } catch (e) {
        // 404 = 体检任务仍在跑（阶段 A 续跑中），轮询等待
        if ((e as ApiError).code === "INTERNAL_ERROR" && !stop) setPending(false);
      }
    };
    void load();
    const timer = setInterval(() => {
      if (!insight) void load();
    }, 3000);
    return () => {
      stop = true;
      clearInterval(timer);
    };
  }, [datasetId, insight]);

  if (!insight) {
    return pending ? (
      <Alert
        type="info"
        showIcon
        message="数据体检报告生成中…（自动修复 + 探索性分析，通常数秒）"
        style={{ marginBottom: 16 }}
      />
    ) : null;
  }

  const { eda, task_recommendation: rec, research_profile: rp, auto_fix_log: fixLog, summary } =
    insight.payload;
  const ss = eda.sample_size;
  const topMissing = eda.missing.columns.filter((c) => c.missing > 0).slice(0, 10);
  const contPairs = eda.correlations.continuous.top_pairs;
  const catPairs = eda.correlations.categorical.top_pairs;

  return (
    <Card title="数据体检报告（自动生成）" style={{ marginBottom: 16 }}>
      {/* 体检结论（真实数值摘要） */}
      <Alert
        type={rec.can_start_modeling ? "success" : "warning"}
        message="体检结论"
        description={
          <ul style={{ margin: "4px 0", paddingLeft: 20 }}>
            {summary.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        }
        style={{ marginBottom: 16 }}
      />

      {fixLog.length > 0 && (
        <Alert
          type="info"
          message={`已自动完成 ${fixLog.length} 项安全修复（生成新版本，源文件不变）`}
          description={
            <Space size={4} wrap style={{ marginTop: 4 }}>
              {fixLog.map((e, i) => (
                <Tag key={i}>
                  {e.column}: {ACTION_LABEL[e.action] ?? e.action}（{e.affected_rows} 行）
                </Tag>
              ))}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* 核心统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Statistic title="行数" value={eda.row_count} />
        </Col>
        <Col span={4}>
          <Statistic title="列数" value={eda.column_count} />
        </Col>
        <Col span={4}>
          <Statistic
            title="完整病例比例"
            value={(eda.missing.complete_case_ratio * 100).toFixed(1)}
            suffix="%"
          />
        </Col>
        {ss.n_events != null && (
          <>
            <Col span={4}>
              <Statistic title={`事件数（${ss.event_column}）`} value={ss.n_events} />
            </Col>
            <Col span={4}>
              <Statistic
                title="EPV"
                value={ss.epv ?? 0}
                valueStyle={{ color: ss.epv_adequate ? "#3f8600" : "#cf1322" }}
              />
            </Col>
          </>
        )}
        <Col span={4}>
          <Statistic
            title="研究设计画像"
            value={RESEARCH_TYPE_LABEL[rp.research_type] ?? rp.research_type}
          />
        </Col>
      </Row>

      {/* 推荐任务与研究建议 */}
      <div style={{ marginBottom: 16 }}>
        <Space size={4} wrap>
          <Typography.Text strong>推荐任务：</Typography.Text>
          {rec.recommended_tasks.length > 0 ? (
            rec.recommended_tasks.map((t) => (
              <Tag key={t} color="blue">
                {TASK_LABEL[t] ?? t}
              </Tag>
            ))
          ) : (
            <Tag>探索性分析</Tag>
          )}
          <Typography.Text strong style={{ marginLeft: 16 }}>
            推荐模型：
          </Typography.Text>
          {rp.recommended_models.map((m) => (
            <Tag key={m} color="geekblue">
              {m}
            </Tag>
          ))}
        </Space>
        <Typography.Paragraph type="secondary" style={{ fontSize: 12, marginTop: 8, marginBottom: 0 }}>
          {rp.reasoning}
        </Typography.Paragraph>
      </div>

      {/* 详细图表（折叠） */}
      <Collapse
        items={[
          {
            key: "dist",
            label: `变量分布（${eda.distributions.length} 列）`,
            children: (
              <Row gutter={[16, 16]}>
                {eda.distributions.slice(0, 12).map((d) => (
                  <Col span={8} key={d.name}>
                    <Card
                      size="small"
                      title={
                        <Space size={4}>
                          <span>{d.name}</span>
                          {d.semantic && <Tag color="geekblue">{d.semantic}</Tag>}
                          {d.missing > 0 && (
                            <Tag color="orange">缺 {d.missing}</Tag>
                          )}
                        </Space>
                      }
                    >
                      <DistributionChart dist={d} />
                      {d.stats && (
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          均值 {fmt(d.stats.mean)} / 标准差 {fmt(d.stats.std)} / 中位数{" "}
                          {fmt(d.stats.median)} / 范围 {fmt(d.stats.min)}~{fmt(d.stats.max)}
                        </Typography.Text>
                      )}
                    </Card>
                  </Col>
                ))}
              </Row>
            ),
          },
          {
            key: "missing",
            label: `缺失模式（${topMissing.length} 列含缺失）`,
            children:
              topMissing.length === 0 ? (
                <Typography.Text type="secondary">无缺失</Typography.Text>
              ) : (
                <Table
                  rowKey="name"
                  size="small"
                  dataSource={topMissing}
                  pagination={false}
                  columns={[
                    { title: "列", dataIndex: "name" },
                    { title: "缺失数", dataIndex: "missing" },
                    {
                      title: "缺失率",
                      dataIndex: "missing_rate",
                      render: (v: number) => `${(v * 100).toFixed(1)}%`,
                    },
                  ]}
                />
              ),
          },
          {
            key: "corr",
            label: "相关性 Top 对",
            children: (
              <Row gutter={16}>
                <Col span={12}>
                  <Typography.Text strong>连续变量（Pearson r）</Typography.Text>
                  {contPairs.length === 0 ? (
                    <Typography.Paragraph type="secondary">无</Typography.Paragraph>
                  ) : (
                    <ul style={{ paddingLeft: 20 }}>
                      {contPairs.map((p, i) => (
                        <li key={i}>
                          {p.a} × {p.b}: r = {p.r.toFixed(3)}
                        </li>
                      ))}
                    </ul>
                  )}
                </Col>
                <Col span={12}>
                  <Typography.Text strong>分类变量（Cramér's V）</Typography.Text>
                  {catPairs.length === 0 ? (
                    <Typography.Paragraph type="secondary">无</Typography.Paragraph>
                  ) : (
                    <ul style={{ paddingLeft: 20 }}>
                      {catPairs.map((p, i) => (
                        <li key={i}>
                          {p.a} × {p.b}: V = {p.cramers_v.toFixed(3)}
                        </li>
                      ))}
                    </ul>
                  )}
                </Col>
              </Row>
            ),
          },
        ]}
      />
    </Card>
  );
}
