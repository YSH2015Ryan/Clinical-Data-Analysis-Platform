/** 单因素筛选 + 亚组分析 + 混杂校正卡片（T6.10 / P1-12；数据集详情页「科研助手」）。
 *
 * 单因素筛选：选择任务类型与结局列 → 逐特征关联检验表（按 p 升序，入选标绿），
 * 入选特征供多因素建模参考；亚组分析：选择暴露与亚组变量 → 分层效应（OR/HR/β
 * + 95%CI）+ 交互作用 p；混杂校正（P1-12，updateplan §29）：研究者指定混杂清单，
 * Unadjusted vs Adjusted 并列展示，文案注明「调整后关联 ≠ 因果效应」。
 * 所有数值由后端真实计算。
 */

import { Alert, Button, Card, Form, InputNumber, Select, Space, Table, Tag, Typography, message } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  adjustedAssociation,
  leakageExperiment,
  subgroupAnalysis,
  univariateScreen,
  type AdjustedAssociationResult,
  type ApiError,
  type CorrectionMethod,
  type LeakageExperimentResult,
  type SubgroupAnalysisResult,
  type TaskType,
  type UnivariateScreenResult,
} from "../api";
import { normalizeLocale } from "../i18n/locale";

const TASK_TYPES: TaskType[] = ["survival", "classification", "regression"];

/** P1-13（§30）：多重比较校正选项。 */
const CORRECTION_METHODS: CorrectionMethod[] = ["bh", "bonferroni", "none"];

function formatList(values: string[], locale: string): string {
  return new Intl.ListFormat(normalizeLocale(locale), {
    style: "long",
    type: "conjunction",
  }).format(values);
}

const fmtP = (v: number | null | undefined) =>
  v == null ? "—" : v < 0.001 ? "<0.001" : v.toFixed(4);

export default function ScreeningCard({
  datasetId,
  columns,
}: {
  datasetId: string;
  columns: string[];
}) {
  const [screenForm] = Form.useForm();
  const [subgroupForm] = Form.useForm();
  const [adjustForm] = Form.useForm();
  const [screening, setScreening] = useState(false);
  const [screenResult, setScreenResult] = useState<UnivariateScreenResult | null>(null);
  const [subgrouping, setSubgrouping] = useState(false);
  const [subgroupResult, setSubgroupResult] = useState<SubgroupAnalysisResult | null>(null);
  const [adjusting, setAdjusting] = useState(false);
  const [adjustResult, setAdjustResult] = useState<AdjustedAssociationResult | null>(null);
  const [experimentForm] = Form.useForm();
  const [experimenting, setExperimenting] = useState(false);
  const [experimentResult, setExperimentResult] = useState<LeakageExperimentResult | null>(null);
  const { i18n, t } = useTranslation();

  const columnOptions = columns.map((c) => ({ value: c, label: c }));
  const taskOptions = TASK_TYPES.map((task) => ({
    value: task,
    label: t(`dataset.screening.taskTypes.${task}`),
  }));
  const correctionOptions = CORRECTION_METHODS.map((method) => ({
    value: method,
    label: t(`dataset.screening.corrections.${method}`),
  }));

  const runScreen = async () => {
    const v = await screenForm.validateFields();
    setScreening(true);
    try {
      setScreenResult(await univariateScreen(datasetId, v));
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.screening.errors.screen"));
    } finally {
      setScreening(false);
    }
  };

  const runSubgroup = async () => {
    const v = await subgroupForm.validateFields();
    setSubgrouping(true);
    try {
      setSubgroupResult(await subgroupAnalysis(datasetId, v));
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.screening.errors.subgroup"));
    } finally {
      setSubgrouping(false);
    }
  };

  const runAdjust = async () => {
    const v = await adjustForm.validateFields();
    setAdjusting(true);
    try {
      setAdjustResult(await adjustedAssociation(datasetId, v));
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.screening.errors.adjustment"));
    } finally {
      setAdjusting(false);
    }
  };

  const runExperiment = async () => {
    const v = await experimentForm.validateFields();
    setExperimenting(true);
    try {
      setExperimentResult(await leakageExperiment(datasetId, v));
    } catch (e) {
      message.error((e as ApiError).message || t("dataset.screening.errors.leakage"));
    } finally {
      setExperimenting(false);
    }
  };

  const outcomeFields = (form: ReturnType<typeof Form.useForm>[0]) => (
    <Form.Item noStyle shouldUpdate>
      {() =>
        form.getFieldValue("task_type") === "survival" ? (
          <>
            <Form.Item
              name="time_col"
              label={t("dataset.screening.followupTime")}
              rules={[{ required: true, message: t("dataset.screening.selectFollowupTime") }]}
            >
              <Select
                options={columnOptions}
                placeholder={t("dataset.screening.timePlaceholder")}
              />
            </Form.Item>
            <Form.Item
              name="event_col"
              label={t("dataset.screening.eventColumn")}
              rules={[{ required: true, message: t("dataset.screening.selectEventColumn") }]}
            >
              <Select
                options={columnOptions}
                placeholder={t("dataset.screening.eventPlaceholder")}
              />
            </Form.Item>
          </>
        ) : (
          <Form.Item
            name="label_col"
            label={t("dataset.screening.outcomeColumn")}
            rules={[{ required: true, message: t("dataset.screening.selectOutcomeColumn") }]}
          >
            <Select
              options={columnOptions}
              placeholder={t("dataset.screening.outcomePlaceholder")}
            />
          </Form.Item>
        )
      }
    </Form.Item>
  );

  return (
    <Card title={t("dataset.screening.title")} style={{ marginBottom: 16 }}>
      <Typography.Title level={5}>{t("dataset.screening.screeningTitle")}</Typography.Title>
      <Form form={screenForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label={t("dataset.screening.taskType")}
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select style={{ width: 120 }} options={taskOptions} />
        </Form.Item>
        {outcomeFields(screenForm)}
        <Form.Item name="alpha" label="α" initialValue={0.05}>
          <InputNumber min={0.0001} max={0.2} step={0.01} style={{ width: 90 }} />
        </Form.Item>
        <Form.Item
          name="correction"
          label={t("dataset.screening.multipleComparison")}
          initialValue="bh"
        >
          <Select style={{ width: 190 }} options={correctionOptions} />
        </Form.Item>
        <Button type="primary" loading={screening} onClick={() => void runScreen()}>
          {t("dataset.screening.start")}
        </Button>
      </Form>
      {screenResult && (
        <>
          {screenResult.correction_warning && (
            <Alert
              type="warning"
              showIcon
              style={{ marginBottom: 8 }}
              message={screenResult.correction_warning}
            />
          )}
          <Typography.Paragraph type="secondary">
            {t("dataset.screening.selectedFeaturesSummary", {
              correction: screenResult.correction_label,
              alpha: screenResult.alpha,
              count: screenResult.n_tests,
              features:
                screenResult.selected_features.length > 0
                  ? formatList(screenResult.selected_features, i18n.language)
                  : t("dataset.screening.none"),
            })}
          </Typography.Paragraph>
          <Table
            rowKey="feature"
            size="small"
            dataSource={screenResult.rows}
            pagination={false}
            style={{ marginBottom: 24 }}
            columns={[
              { title: t("dataset.screening.table.feature"), dataIndex: "feature" },
              { title: t("dataset.screening.table.test"), dataIndex: "test" },
              {
                title: t("dataset.screening.table.effect"),
                dataIndex: "effect",
                render: (v: number | null) => v ?? "—",
              },
              {
                title: t("dataset.screening.table.rawP"),
                dataIndex: "p_value",
                render: fmtP,
              },
              {
                title: t("dataset.screening.table.adjustedP"),
                dataIndex: "p_adjusted",
                render: fmtP,
              },
              { title: "n", dataIndex: "n_used", width: 70 },
              {
                title: t("dataset.screening.table.selected"),
                dataIndex: "selected",
                width: 70,
                render: (v: boolean) =>
                  v ? (
                    <Tag color="green">{t("dataset.screening.selectedTag")}</Tag>
                  ) : (
                    <Tag>{t("dataset.screening.notSelectedTag")}</Tag>
                  ),
              },
            ]}
          />
        </>
      )}

      <Typography.Title level={5}>{t("dataset.screening.subgroupTitle")}</Typography.Title>
      <Form form={subgroupForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label={t("dataset.screening.taskType")}
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select style={{ width: 120 }} options={taskOptions} />
        </Form.Item>
        {outcomeFields(subgroupForm)}
        <Form.Item
          name="exposure"
          label={t("dataset.screening.exposureVariable")}
          rules={[{ required: true, message: t("dataset.screening.selectExposure") }]}
        >
          <Select
            options={columnOptions}
            placeholder={t("dataset.screening.exposurePlaceholder")}
            style={{ minWidth: 120 }}
          />
        </Form.Item>
        <Form.Item
          name="subgroup_vars"
          label={t("dataset.screening.subgroupVariables")}
          rules={[{ required: true, message: t("dataset.screening.selectSubgroups") }]}
        >
          <Select
            mode="multiple"
            options={columnOptions}
            placeholder={t("dataset.screening.subgroupPlaceholder")}
            style={{ minWidth: 200 }}
          />
        </Form.Item>
        <Form.Item
          name="correction"
          label={t("dataset.screening.multipleComparison")}
          initialValue="bh"
        >
          <Select style={{ width: 190 }} options={correctionOptions} />
        </Form.Item>
        <Button type="primary" loading={subgrouping} onClick={() => void runSubgroup()}>
          {t("dataset.screening.startSubgroup")}
        </Button>
      </Form>
      {subgroupResult?.correction_warning && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 8 }}
          message={subgroupResult.correction_warning}
        />
      )}
      {subgroupResult && subgroupResult.n_tests > 0 && (
        <Typography.Paragraph type="secondary">
          {t("dataset.screening.interactionNote", {
            correction: subgroupResult.correction_label,
            count: subgroupResult.n_tests,
          })}
        </Typography.Paragraph>
      )}
      {subgroupResult &&
        subgroupResult.subgroups.map((sub) => (
          <div key={sub.variable} style={{ marginBottom: 16 }}>
            <Typography.Text strong>
              {sub.interaction_p == null
                ? t("dataset.screening.subgroup.groupTitle", { variable: sub.variable })
                : t(
                    (sub.interaction_p_adjusted ?? sub.interaction_p) < 0.05
                      ? "dataset.screening.subgroup.withEffectModification"
                      : "dataset.screening.subgroup.withoutEffectModification",
                    {
                      variable: sub.variable,
                      interactionP: fmtP(sub.interaction_p),
                      adjustedP: fmtP(sub.interaction_p_adjusted),
                    },
                  )}
            </Typography.Text>
            <Table
              rowKey="level"
              size="small"
              dataSource={sub.levels}
              pagination={false}
              columns={[
                { title: t("dataset.screening.subgroup.level"), dataIndex: "level" },
                { title: "n", dataIndex: "n", width: 70 },
                {
                  title:
                    subgroupResult.task_type === "regression"
                      ? "β (95%CI)"
                      : subgroupResult.task_type === "survival"
                        ? "HR (95%CI)"
                        : "OR (95%CI)",
                  render: (_, r) =>
                    r.effect != null && r.ci_lower != null && r.ci_upper != null
                      ? `${r.effect} (${r.ci_lower} ~ ${r.ci_upper})`
                      : (r.note ?? "—"),
                },
              ]}
            />
          </div>
        ))}

      <Typography.Title level={5}>{t("dataset.screening.adjustmentTitle")}</Typography.Title>
      <Form form={adjustForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label={t("dataset.screening.taskType")}
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select style={{ width: 120 }} options={taskOptions} />
        </Form.Item>
        {outcomeFields(adjustForm)}
        <Form.Item
          name="exposure"
          label={t("dataset.screening.exposureVariable")}
          rules={[{ required: true, message: t("dataset.screening.selectExposure") }]}
        >
          <Select
            options={columnOptions}
            placeholder={t("dataset.screening.exposurePlaceholder")}
            style={{ minWidth: 120 }}
          />
        </Form.Item>
        <Form.Item
          name="confounders"
          label={t("dataset.screening.confounders")}
          rules={[{ required: true, message: t("dataset.screening.selectConfounders") }]}
        >
          <Select
            mode="multiple"
            options={columnOptions}
            placeholder={t("dataset.screening.confounderPlaceholder")}
            style={{ minWidth: 240 }}
          />
        </Form.Item>
        <Button type="primary" loading={adjusting} onClick={() => void runAdjust()}>
          {t("dataset.screening.startAdjustment")}
        </Button>
      </Form>
      {adjustResult && (
        <>
          <Typography.Paragraph type="secondary">
            {t("dataset.screening.adjustedSummary", {
              count: adjustResult.n_used,
              confounders: formatList(adjustResult.confounders, i18n.language),
            })}
          </Typography.Paragraph>
          <Table
            rowKey="kind"
            size="small"
            pagination={false}
            style={{ marginBottom: 8 }}
            dataSource={[
              {
                kind: "unadjusted",
                label: t("dataset.screening.models.unadjusted"),
                ...adjustResult.unadjusted,
              },
              {
                kind: "adjusted",
                label: t("dataset.screening.models.adjusted"),
                ...adjustResult.adjusted,
              },
            ] as {
              kind: string;
              label: string;
              effect_label: string;
              effect: number;
              ci_lower: number;
              ci_upper: number;
              p_value: number;
            }[]}
            columns={[
              { title: t("dataset.screening.table.model"), dataIndex: "label", width: 90 },
              { title: t("dataset.screening.table.effect"), dataIndex: "effect_label", width: 80 },
              {
                title: t("dataset.screening.table.estimate"),
                dataIndex: "effect",
                render: (v: number) => v,
              },
              {
                title: "95%CI",
                render: (
                  _: unknown,
                  r: { ci_lower: number; ci_upper: number },
                ) => `${r.ci_lower} ~ ${r.ci_upper}`,
              },
              {
                title: t("dataset.screening.table.pValue"),
                dataIndex: "p_value",
                render: fmtP,
              },
            ]}
          />
          <Alert type="info" showIcon message={adjustResult.note} />
        </>
      )}

      <Typography.Title level={5}>{t("dataset.screening.leakageTitle")}</Typography.Title>
      <Form form={experimentForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label={t("dataset.screening.taskType")}
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select style={{ width: 120 }} options={taskOptions} />
        </Form.Item>
        {outcomeFields(experimentForm)}
        <Button type="primary" loading={experimenting} onClick={() => void runExperiment()}>
          {t("dataset.screening.startLeakage")}
        </Button>
      </Form>
      {experimentResult && (
        <>
          <Table
            rowKey="set_key"
            size="small"
            pagination={false}
            style={{ marginBottom: 8 }}
            dataSource={experimentResult.sets}
            columns={[
              { title: t("dataset.screening.leakage.variableSet"), dataIndex: "label" },
              {
                title: t("dataset.screening.leakage.variableCount"),
                dataIndex: "n_features",
                width: 70,
              },
              ...(experimentResult.task_type === "regression"
                ? [
                    {
                      title: "RMSE",
                      render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                        r.metrics?.rmse != null ? r.metrics.rmse.toFixed(4) : (r.note ?? "—"),
                    },
                    {
                      title: "R²",
                      render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                        r.metrics?.r2 != null ? r.metrics.r2.toFixed(4) : "—",
                    },
                  ]
                : experimentResult.task_type === "survival"
                  ? [
                      {
                        title: "C-index",
                        render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                          r.metrics?.c_index != null
                            ? r.metrics.c_index.toFixed(4)
                            : (r.note ?? "—"),
                      },
                    ]
                  : [
                      {
                        title: "AUC",
                        render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                          r.metrics?.auc != null ? r.metrics.auc.toFixed(4) : (r.note ?? "—"),
                      },
                      {
                        title: "PR-AUC",
                        render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                          r.metrics?.pr_auc != null ? r.metrics.pr_auc.toFixed(4) : "—",
                      },
                      {
                        title: t("dataset.screening.leakage.calibrationSlope"),
                        render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                          r.metrics?.calibration_slope != null
                            ? r.metrics.calibration_slope.toFixed(4)
                            : "—",
                      },
                    ]),
              {
                title: t("dataset.screening.leakage.removedVariables"),
                dataIndex: "removed",
                render: (v: string[]) =>
                  v.length > 0 ? (
                    <Typography.Text type="secondary">
                      {formatList(v, i18n.language)}
                    </Typography.Text>
                  ) : (
                    "—"
                  ),
              },
            ]}
          />
          {/* Legacy control-flow check; T9.4 may replace it with a stable result code if useful. */}
          <Alert
            type={experimentResult.interpretation.includes("很可能由泄漏驱动") ? "error" : "info"}
            showIcon
            message={experimentResult.interpretation}
          />
        </>
      )}
    </Card>
  );
}
