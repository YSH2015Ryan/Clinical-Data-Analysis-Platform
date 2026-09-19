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

const TASK_LABEL: Record<TaskType, string> = {
  survival: "生存分析",
  classification: "分类",
  regression: "回归",
};

/** P1-13（§30）：多重比较校正选项。 */
const CORRECTION_OPTIONS: { value: CorrectionMethod; label: string }[] = [
  { value: "bh", label: "BH(FDR) 校正" },
  { value: "bonferroni", label: "Bonferroni 校正" },
  { value: "none", label: "不校正（有假阳性风险）" },
];

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

  const columnOptions = columns.map((c) => ({ value: c, label: c }));

  const runScreen = async () => {
    const v = await screenForm.validateFields();
    setScreening(true);
    try {
      setScreenResult(await univariateScreen(datasetId, v));
    } catch (e) {
      message.error((e as ApiError).message || "筛选失败");
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
      message.error((e as ApiError).message || "亚组分析失败");
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
      message.error((e as ApiError).message || "混杂校正失败");
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
      message.error((e as ApiError).message || "泄漏实验失败");
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
              label="随访时间列"
              rules={[{ required: true, message: "选择随访时间列" }]}
            >
              <Select options={columnOptions} placeholder="time" />
            </Form.Item>
            <Form.Item
              name="event_col"
              label="事件列"
              rules={[{ required: true, message: "选择事件列" }]}
            >
              <Select options={columnOptions} placeholder="event" />
            </Form.Item>
          </>
        ) : (
          <Form.Item
            name="label_col"
            label="结局列"
            rules={[{ required: true, message: "选择结局列" }]}
          >
            <Select options={columnOptions} placeholder="label" />
          </Form.Item>
        )
      }
    </Form.Item>
  );

  return (
    <Card title="科研助手：单因素筛选与亚组分析" style={{ marginBottom: 16 }}>
      <Typography.Title level={5}>单因素筛选（p &lt; α 入选供多因素建模）</Typography.Title>
      <Form form={screenForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label="任务类型"
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select
            style={{ width: 120 }}
            options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
              value: t,
              label: TASK_LABEL[t],
            }))}
          />
        </Form.Item>
        {outcomeFields(screenForm)}
        <Form.Item name="alpha" label="α" initialValue={0.05}>
          <InputNumber min={0.0001} max={0.2} step={0.01} style={{ width: 90 }} />
        </Form.Item>
        <Form.Item name="correction" label="多重比较" initialValue="bh">
          <Select style={{ width: 190 }} options={CORRECTION_OPTIONS} />
        </Form.Item>
        <Button type="primary" loading={screening} onClick={() => void runScreen()}>
          开始筛选
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
            入选特征（{screenResult.correction_label}校正后 p &lt; {screenResult.alpha}，共{" "}
            {screenResult.n_tests} 项检验）：
            {screenResult.selected_features.length > 0
              ? screenResult.selected_features.join("、")
              : "无"}
          </Typography.Paragraph>
          <Table
            rowKey="feature"
            size="small"
            dataSource={screenResult.rows}
            pagination={false}
            style={{ marginBottom: 24 }}
            columns={[
              { title: "特征", dataIndex: "feature" },
              { title: "检验", dataIndex: "test" },
              {
                title: "效应量",
                dataIndex: "effect",
                render: (v: number | null) => v ?? "—",
              },
              {
                title: "p 值（原始）",
                dataIndex: "p_value",
                render: fmtP,
              },
              {
                title: "校正后 p 值",
                dataIndex: "p_adjusted",
                render: fmtP,
              },
              { title: "n", dataIndex: "n_used", width: 70 },
              {
                title: "入选",
                dataIndex: "selected",
                width: 70,
                render: (v: boolean) =>
                  v ? <Tag color="green">入选</Tag> : <Tag>未入选</Tag>,
              },
            ]}
          />
        </>
      )}

      <Typography.Title level={5}>亚组分析（分层效应 + 交互作用）</Typography.Title>
      <Form form={subgroupForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label="任务类型"
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select
            style={{ width: 120 }}
            options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
              value: t,
              label: TASK_LABEL[t],
            }))}
          />
        </Form.Item>
        {outcomeFields(subgroupForm)}
        <Form.Item
          name="exposure"
          label="暴露变量"
          rules={[{ required: true, message: "选择暴露变量" }]}
        >
          <Select options={columnOptions} placeholder="exposure" style={{ minWidth: 120 }} />
        </Form.Item>
        <Form.Item
          name="subgroup_vars"
          label="亚组变量"
          rules={[{ required: true, message: "选择 1 个或多个亚组变量" }]}
        >
          <Select
            mode="multiple"
            options={columnOptions}
            placeholder="分类变量（2-6 水平）"
            style={{ minWidth: 200 }}
          />
        </Form.Item>
        <Form.Item name="correction" label="多重比较" initialValue="bh">
          <Select style={{ width: 190 }} options={CORRECTION_OPTIONS} />
        </Form.Item>
        <Button type="primary" loading={subgrouping} onClick={() => void runSubgroup()}>
          开始分析
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
          交互作用显著性基于{subgroupResult.correction_label}校正后 p 值（共{" "}
          {subgroupResult.n_tests} 项检验）。
        </Typography.Paragraph>
      )}
      {subgroupResult &&
        subgroupResult.subgroups.map((sub) => (
          <div key={sub.variable} style={{ marginBottom: 16 }}>
            <Typography.Text strong>
              {sub.variable} 亚组
              {sub.interaction_p != null &&
                `（交互 p = ${fmtP(sub.interaction_p)}，校正后 p = ${fmtP(
                  sub.interaction_p_adjusted,
                )}${
                  (sub.interaction_p_adjusted ?? sub.interaction_p) < 0.05
                    ? "，存在效应修饰"
                    : "，未见显著效应修饰"
                }）`}
            </Typography.Text>
            <Table
              rowKey="level"
              size="small"
              dataSource={sub.levels}
              pagination={false}
              columns={[
                { title: "亚组", dataIndex: "level" },
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

      <Typography.Title level={5}>混杂校正关联分析（Unadjusted vs Adjusted）</Typography.Title>
      <Form form={adjustForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label="任务类型"
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select
            style={{ width: 120 }}
            options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
              value: t,
              label: TASK_LABEL[t],
            }))}
          />
        </Form.Item>
        {outcomeFields(adjustForm)}
        <Form.Item
          name="exposure"
          label="暴露变量"
          rules={[{ required: true, message: "选择暴露变量" }]}
        >
          <Select options={columnOptions} placeholder="exposure" style={{ minWidth: 120 }} />
        </Form.Item>
        <Form.Item
          name="confounders"
          label="混杂变量"
          rules={[{ required: true, message: "指定 1 个或多个候选混杂变量" }]}
        >
          <Select
            mode="multiple"
            options={columnOptions}
            placeholder="由研究者指定（系统不猜测因果结构）"
            style={{ minWidth: 240 }}
          />
        </Form.Item>
        <Button type="primary" loading={adjusting} onClick={() => void runAdjust()}>
          开始校正
        </Button>
      </Form>
      {adjustResult && (
        <>
          <Typography.Paragraph type="secondary">
            完整病例 n = {adjustResult.n_used}；校正清单：
            {adjustResult.confounders.join("、")}
          </Typography.Paragraph>
          <Table
            rowKey="kind"
            size="small"
            pagination={false}
            style={{ marginBottom: 8 }}
            dataSource={[
              { kind: "unadjusted", label: "未校正", ...adjustResult.unadjusted },
              { kind: "adjusted", label: "校正后", ...adjustResult.adjusted },
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
              { title: "模型", dataIndex: "label", width: 90 },
              { title: "效应量", dataIndex: "effect_label", width: 80 },
              {
                title: "估计值",
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
                title: "p 值",
                dataIndex: "p_value",
                render: fmtP,
              },
            ]}
          />
          <Alert type="info" showIcon message={adjustResult.note} />
        </>
      )}

      <Typography.Title level={5}>泄漏敏感性实验（A/B/C/D 变量集对比，§25）</Typography.Title>
      <Form form={experimentForm} layout="inline" style={{ marginBottom: 12 }}>
        <Form.Item
          name="task_type"
          label="任务类型"
          initialValue="classification"
          rules={[{ required: true }]}
        >
          <Select
            style={{ width: 120 }}
            options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
              value: t,
              label: TASK_LABEL[t],
            }))}
          />
        </Form.Item>
        {outcomeFields(experimentForm)}
        <Button type="primary" loading={experimenting} onClick={() => void runExperiment()}>
          开始实验
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
              { title: "变量集", dataIndex: "label" },
              { title: "变量数", dataIndex: "n_features", width: 70 },
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
                        title: "校准斜率",
                        render: (_: unknown, r: LeakageExperimentResult["sets"][number]) =>
                          r.metrics?.calibration_slope != null
                            ? r.metrics.calibration_slope.toFixed(4)
                            : "—",
                      },
                    ]),
              {
                title: "移除变量",
                dataIndex: "removed",
                render: (v: string[]) =>
                  v.length > 0 ? (
                    <Typography.Text type="secondary">{v.join("、")}</Typography.Text>
                  ) : (
                    "—"
                  ),
              },
            ]}
          />
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
