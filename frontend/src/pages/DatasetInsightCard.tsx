/** 数据体检卡（P2-2，docs/08 §3.2 阶段 A）：上传后自动产出的 EDA + 体检结论。
 *
 * 数据来源 GET /datasets/{id}/insight；全部数值为后端引擎真实计算结果，
 * 前端只做可视化（直方图/Top 计数/相关性对/EPV），不做任何推断。
 */

import { Alert, Card, Col, Collapse, Row, Space, Statistic, Table, Tag, Tooltip, Typography } from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  getDatasetInsight,
  type ApiError,
  type DatasetInsight,
  type EdaDistribution,
  type ResearchOpportunities,
  type ResearchOpportunityItem,
} from "../api";
import ChartPanel from "../components/ChartPanel";

const TASK_KEY: Record<string, string> = {
  survival: "dataset.insight.tasks.survival",
  classification: "dataset.insight.tasks.classification",
  regression: "dataset.insight.tasks.regression",
  eda: "dataset.insight.tasks.eda",
};

const RESEARCH_TYPE_KEY: Record<string, string> = {
  cohort: "dataset.insight.researchTypes.cohort",
  case_control: "dataset.insight.researchTypes.caseControl",
  cross_sectional: "dataset.insight.researchTypes.crossSectional",
  time_series: "dataset.insight.researchTypes.timeSeries",
};

const ACTION_KEY: Record<string, string> = {
  impute_missing: "dataset.insight.actions.imputeMissing",
  winsorize_outliers: "dataset.insight.actions.winsorizeOutliers",
  to_missing: "dataset.insight.actions.toMissing",
};

/** T6.14 缺口类型标签 */
const DEFICIT_KEY: Record<string, string> = {
  epv: "dataset.insight.deficits.epv",
  imbalance: "dataset.insight.deficits.imbalance",
  survival_events: "dataset.insight.deficits.survivalEvents",
  variable_roles: "dataset.insight.deficits.variableRoles",
  power: "dataset.insight.deficits.power",
};

function fmt(v: number | null | undefined, digits = 2): string {
  return v == null ? "—" : v.toFixed(digits);
}

/** P2-06/§81：五类研究机会渲染（Hypothesis-generating，依据串随条展示） */
function OpportunityList({
  title,
  items,
}: {
  title: string;
  items: ResearchOpportunityItem[];
}) {
  const { t } = useTranslation();
  if (items.length === 0) return null;
  return (
    <div style={{ marginBottom: 8 }}>
      <Typography.Text strong>{title}</Typography.Text>
      <ul style={{ margin: "4px 0", paddingLeft: 20 }}>
        {items.map((it, i) => (
          <li key={i} style={{ marginBottom: 4 }}>
            {it.text}
            <br />
            <Typography.Text type="secondary" style={{ fontSize: 11 }}>
              {t("dataset.insight.basis", { basis: it.basis })}
            </Typography.Text>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ResearchOpportunitiesBlock({ ro }: { ro: ResearchOpportunities }) {
  const { t } = useTranslation();
  const total =
    ro.observed_patterns.length +
    ro.unexpected_associations.length +
    ro.potential_subgroup_differences.length +
    ro.potential_prediction_tasks.length +
    ro.potential_hypotheses.length;
  return (
    <Collapse
      style={{ marginBottom: 16 }}
      items={[
        {
          key: "ro",
          label: t("dataset.insight.opportunitiesLabel", { count: total }),
          children: (
            <>
              <Alert type="info" message={ro.notice} style={{ marginBottom: 12 }} />
              <OpportunityList
                title={t("dataset.insight.opportunityTitles.observedPatterns")}
                items={ro.observed_patterns}
              />
              <OpportunityList
                title={t("dataset.insight.opportunityTitles.unexpectedAssociations")}
                items={ro.unexpected_associations}
              />
              <OpportunityList
                title={t("dataset.insight.opportunityTitles.subgroupDifferences")}
                items={ro.potential_subgroup_differences}
              />
              <OpportunityList
                title={t("dataset.insight.opportunityTitles.predictionTasks")}
                items={ro.potential_prediction_tasks}
              />
              <OpportunityList
                title={t("dataset.insight.opportunityTitles.hypotheses")}
                items={ro.potential_hypotheses}
              />
              {total === 0 && (
                <Typography.Text type="secondary">
                  {t("dataset.insight.noOpportunities")}
                </Typography.Text>
              )}
            </>
          ),
        },
      ]}
    />
  );
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
  const { t } = useTranslation();

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
        message={t("dataset.insight.pending")}
        style={{ marginBottom: 16 }}
      />
    ) : null;
  }

  const { eda, task_recommendation: rec, research_profile: rp, auto_fix_log: fixLog, summary } =
    insight.payload;
  const supplement = insight.payload.supplement_plan;
  const opportunities = insight.payload.research_opportunities;
  const ss = eda.sample_size;
  const topMissing = eda.missing.columns.filter((c) => c.missing > 0).slice(0, 10);
  const contPairs = eda.correlations.continuous.top_pairs;
  const catPairs = eda.correlations.categorical.top_pairs;

  return (
    <Card title={t("dataset.insight.title")} style={{ marginBottom: 16 }}>
      {/* 体检结论（真实数值摘要） */}
      <Alert
        type={rec.can_start_modeling ? "success" : "warning"}
        message={t("dataset.insight.conclusion")}
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
          message={t("dataset.insight.autoFixCompleted", { count: fixLog.length })}
          description={
            <Space size={4} wrap style={{ marginTop: 4 }}>
              {fixLog.map((e, i) => (
                <Tag key={i}>
                  {t("dataset.insight.autoFixEntry", {
                    column: e.column,
                    action: ACTION_KEY[e.action] ? t(ACTION_KEY[e.action]) : e.action,
                    count: e.affected_rows,
                  })}
                </Tag>
              ))}
            </Space>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* T6.14 数据缺口建议（规则引擎真实计算；依据串可展开核对） */}
      {supplement && supplement.items.length > 0 && (
        <Alert
          type="warning"
          showIcon
          message={t("dataset.insight.deficitSuggestions", {
            count: supplement.items.length,
          })}
          description={
            <ul style={{ margin: "4px 0", paddingLeft: 20 }}>
              {supplement.items.map((item, i) => (
                <li key={i} style={{ marginBottom: 8 }}>
                  <Tag color="orange">
                    {DEFICIT_KEY[item.deficit_type]
                      ? t(DEFICIT_KEY[item.deficit_type])
                      : item.deficit_type}
                  </Tag>
                  {item.suggestion}
                  <br />
                  <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                    {t("dataset.insight.basis", { basis: item.basis })}
                  </Typography.Text>
                </li>
              ))}
            </ul>
          }
          style={{ marginBottom: 16 }}
        />
      )}

      {/* P2-06/§81 研究机会与假设生成（规则引擎真实计算，Hypothesis-generating） */}
      {opportunities && <ResearchOpportunitiesBlock ro={opportunities} />}

      {/* 核心统计 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}>
          <Statistic title={t("dataset.insight.rows")} value={eda.row_count} />
        </Col>
        <Col span={4}>
          <Statistic title={t("dataset.insight.columns")} value={eda.column_count} />
        </Col>
        <Col span={4}>
          <Statistic
            title={t("dataset.insight.completeCaseRatio")}
            value={(eda.missing.complete_case_ratio * 100).toFixed(1)}
            suffix="%"
          />
        </Col>
        {ss.n_events != null && (
          <>
            <Col span={4}>
              <Statistic
                title={t("dataset.insight.eventCount", { column: ss.event_column })}
                value={ss.n_events}
              />
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
            title={t("dataset.insight.researchDesign")}
            value={
              RESEARCH_TYPE_KEY[rp.research_type]
                ? t(RESEARCH_TYPE_KEY[rp.research_type])
                : rp.research_type
            }
          />
        </Col>
      </Row>

      {/* 推荐任务与研究建议 */}
      <div style={{ marginBottom: 16 }}>
        <Space size={4} wrap>
          <Typography.Text strong>{t("dataset.insight.recommendedTasks")}</Typography.Text>
          {rec.recommended_tasks.length > 0 ? (
            rec.recommended_tasks.map((task) => (
              <Tag key={task} color="blue">
                {TASK_KEY[task] ? t(TASK_KEY[task]) : task}
              </Tag>
            ))
          ) : (
            <Tag>{t("dataset.insight.defaultTask")}</Tag>
          )}
          <Typography.Text strong style={{ marginLeft: 16 }}>
            {t("dataset.insight.recommendedModels")}
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
            label: t("dataset.insight.distributionSection", {
              count: eda.distributions.length,
            }),
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
                            <Tag color="orange">
                              {t("dataset.insight.missingCount", { count: d.missing })}
                            </Tag>
                          )}
                        </Space>
                      }
                    >
                      <DistributionChart dist={d} />
                      {d.stats && (
                        <Typography.Text type="secondary" style={{ fontSize: 11 }}>
                          {t("dataset.insight.distributionStats", {
                            mean: fmt(d.stats.mean),
                            std: fmt(d.stats.std),
                            median: fmt(d.stats.median),
                            min: fmt(d.stats.min),
                            max: fmt(d.stats.max),
                          })}
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
            label: t("dataset.insight.missingSection", { count: topMissing.length }),
            children: (
              <>
                {/* P1-11（§12）：缺失与结局相关 → 必须 WARNING */}
                {eda.missingness?.has_outcome_associated_missingness && (
                  <Alert
                    type="warning"
                    showIcon
                    style={{ marginBottom: 8 }}
                    message={t("dataset.insight.outcomeMissingTitle")}
                    description={t("dataset.insight.outcomeMissingDescription")}
                  />
                )}
                {topMissing.length === 0 ? (
                  <Typography.Text type="secondary">
                    {t("dataset.insight.noMissing")}
                  </Typography.Text>
                ) : (
                  <Table
                    rowKey="name"
                    size="small"
                    dataSource={topMissing}
                    pagination={false}
                    columns={[
                      { title: t("dataset.insight.missingColumns.column"), dataIndex: "name" },
                      { title: t("dataset.insight.missingColumns.missing"), dataIndex: "missing" },
                      {
                        title: t("dataset.insight.missingColumns.missingRate"),
                        dataIndex: "missing_rate",
                        render: (v: number) => `${(v * 100).toFixed(1)}%`,
                      },
                      {
                        title: t("dataset.insight.missingColumns.mechanism"),
                        key: "mechanism",
                        render: (_, r) => {
                          const mz = eda.missingness?.variables.find(
                            (v) => v.column === r.name,
                          );
                          if (!mz) return "—";
                          const color = {
                            likely_mcar: "green",
                            likely_mar: "gold",
                            possible_mnar: "red",
                            undetermined: "default",
                          }[mz.mechanism];
                          return (
                            <Tooltip title={mz.imputation_advice}>
                              <Tag color={color}>
                                {t(`dataset.insight.mechanisms.${mz.mechanism}`, {
                                  defaultValue: mz.mechanism,
                                })}
                              </Tag>
                            </Tooltip>
                          );
                        },
                      },
                    ]}
                  />
                )}
              </>
            ),
          },
          {
            key: "corr",
            label: t("dataset.insight.correlationSection"),
            children: (
              <Row gutter={16}>
                <Col span={12}>
                  <Typography.Text strong>
                    {t("dataset.insight.continuousCorrelation")}
                  </Typography.Text>
                  {contPairs.length === 0 ? (
                    <Typography.Paragraph type="secondary">
                      {t("dataset.insight.noData")}
                    </Typography.Paragraph>
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
                  <Typography.Text strong>
                    {t("dataset.insight.categoricalCorrelation")}
                  </Typography.Text>
                  {catPairs.length === 0 ? (
                    <Typography.Paragraph type="secondary">
                      {t("dataset.insight.noData")}
                    </Typography.Paragraph>
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
