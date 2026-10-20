/** 预处理配置面板（docs/06 §2、docs/18 T3.6）。

 * 表单 ↔ DSL JSON 双向同步：表单编辑即更新 config；JSON 标签页可手改后「应用到表单」。
 * 「推荐配置」一键填充（T3.5 生成器）；「校验」调 preprocess/validate（非法 DSL 400 展示错误明细）。
 */

import {
  Alert,
  Button,
  Card,
  Collapse,
  Input,
  InputNumber,
  Select,
  Space,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  DEFAULT_STEP_PARAMS,
  recommendPreprocess,
  validatePreprocess,
  type ApiError,
  type PreprocessConfig,
  type PreprocessStep,
  type StepType,
} from "../api";

const STEP_LABEL_KEYS: Record<StepType, string> = {
  reshape: "preparation.panel.stepLabels.reshape",
  drop_columns: "preparation.panel.stepLabels.dropColumns",
  missing: "preparation.panel.stepLabels.missing",
  outlier: "preparation.panel.stepLabels.outlier",
  encode: "preparation.panel.stepLabels.encode",
  scale: "preparation.panel.stepLabels.scale",
  feature_select: "preparation.panel.stepLabels.featureSelect",
  derive: "preparation.panel.stepLabels.derive",
};

const STEP_TYPES = Object.keys(STEP_LABEL_KEYS) as StepType[];

interface Props {
  datasetId: string;
  columns: string[];
  onChange?: (config: PreprocessConfig) => void;
  /** 外部注入的初始配置（如推荐配置）；变化时整体替换当前表单。 */
  initialConfig?: PreprocessConfig | null;
}

const EMPTY_CONFIG: PreprocessConfig = {
  target: {},
  steps: [{ type: "missing", params: { ...DEFAULT_STEP_PARAMS.missing } }],
  validation: { strategy: "kfold", n_splits: 5, seed: 42 },
};

export default function PreprocessPanel({ datasetId, columns, onChange, initialConfig }: Props) {
  const { t } = useTranslation();
  const [config, setConfig] = useState<PreprocessConfig>(initialConfig ?? EMPTY_CONFIG);
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const update = (next: PreprocessConfig) => {
    setConfig(next);
    setErrors([]);
    onChange?.(next);
  };

  // 推荐配置等外部注入到达后整体替换（向导场景：进入步骤即自动推荐）
  useEffect(() => {
    if (initialConfig) update(initialConfig);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialConfig]);

  const setStep = (index: number, step: PreprocessStep) => {
    const steps = config.steps.map((s, i) => (i === index ? step : s));
    update({ ...config, steps });
  };

  const setParam = (index: number, key: string, value: unknown) => {
    const step = config.steps[index];
    setStep(index, { ...step, params: { ...step.params, [key]: value } });
  };

  const columnOptions = columns.map((c) => ({ value: c, label: c }));
  const optionalColumnOptions = [
    { value: "", label: t("preparation.panel.none") },
    ...columnOptions,
  ];

  const onRecommend = async () => {
    setBusy(true);
    try {
      const cfg = await recommendPreprocess(datasetId);
      update(cfg);
      message.success(t("preparation.panel.messages.recommendSuccess"));
    } catch (e) {
      message.error((e as ApiError).message || t("preparation.panel.messages.recommendFailed"));
    } finally {
      setBusy(false);
    }
  };

  const onValidate = async () => {
    setBusy(true);
    try {
      const resp = await validatePreprocess(datasetId, config);
      update(resp.normalized);
      setErrors([]);
      message.success(t("preparation.panel.messages.validateSuccess"));
    } catch (e) {
      const err = e as ApiError;
      const details = err.details?.errors;
      setErrors(
        Array.isArray(details)
          ? details.map((d) => JSON.stringify(d))
          : [err.message || t("preparation.panel.messages.validateFailed")],
      );
    } finally {
      setBusy(false);
    }
  };

  const applyJson = () => {
    if (jsonDraft == null) return;
    try {
      const parsed = JSON.parse(jsonDraft) as PreprocessConfig;
      if (!parsed.target || !Array.isArray(parsed.steps) || !parsed.validation) {
        message.error(t("preparation.panel.messages.missingTopLevelFields"));
        return;
      }
      update(parsed);
      setJsonDraft(null);
      message.success(t("preparation.panel.messages.applySuccess"));
    } catch {
      message.error(t("preparation.panel.messages.jsonParseFailed"));
    }
  };

  const paramControls = (step: PreprocessStep, index: number) => {
    const p = step.params;
    switch (step.type) {
      case "missing":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.defaultStrategy")}</span>
            <Select
              style={{ width: 120 }}
              value={p.default as string}
              options={["median", "mean", "mode", "knn", "constant"].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => setParam(index, "default", v)}
            />
            <span>{t("preparation.panel.params.dropThreshold")}</span>
            <InputNumber
              min={0}
              max={1}
              step={0.1}
              value={p.drop_threshold as number}
              onChange={(v) => setParam(index, "drop_threshold", v ?? 0.5)}
            />
          </Space>
        );
      case "outlier":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.method")}</span>
            <Select
              style={{ width: 110 }}
              value={p.method as string}
              options={["iqr", "zscore"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>{t("preparation.panel.params.action")}</span>
            <Select
              style={{ width: 90 }}
              value={p.action as string}
              options={["clip", "drop"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "action", v)}
            />
          </Space>
        );
      case "encode":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.method")}</span>
            <Select
              style={{ width: 110 }}
              value={p.method as string}
              options={["auto", "onehot", "ordinal"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>{t("preparation.panel.params.oneHotMaxCardinality")}</span>
            <InputNumber
              min={2}
              max={100}
              value={p.onehot_max_cardinality as number}
              onChange={(v) => setParam(index, "onehot_max_cardinality", v ?? 10)}
            />
          </Space>
        );
      case "scale":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.method")}</span>
            <Select
              style={{ width: 120 }}
              value={p.method as string}
              options={["standard", "minmax", "robust"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "method", v)}
            />
          </Space>
        );
      case "feature_select":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.method")}</span>
            <Select
              style={{ width: 180 }}
              value={p.method as string}
              options={["variance_threshold", "correlation", "univariate", "lasso"].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>{t("preparation.panel.params.threshold")}</span>
            <InputNumber
              min={0}
              step={0.05}
              value={p.threshold as number}
              onChange={(v) => setParam(index, "threshold", v ?? 0)}
            />
          </Space>
        );
      case "drop_columns":
        return (
          <Select
            mode="multiple"
            style={{ minWidth: 280 }}
            placeholder={t("preparation.panel.params.dropColumnsPlaceholder")}
            value={(p.columns as string[]) ?? []}
            options={columnOptions}
            onChange={(v) => setParam(index, "columns", v)}
          />
        );
      case "reshape":
        return (
          <Space wrap>
            <span>{t("preparation.panel.params.indexColumn")}</span>
            <Select
              style={{ width: 160 }}
              value={(p.index as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "index", v)}
            />
            <span>{t("preparation.panel.params.nameColumn")}</span>
            <Select
              style={{ width: 160 }}
              value={(p.columns as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "columns", v)}
            />
            <span>{t("preparation.panel.params.valueColumn")}</span>
            <Select
              style={{ width: 160 }}
              value={(p.values as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "values", v)}
            />
            <span>{t("preparation.panel.params.aggregation")}</span>
            <Select
              style={{ width: 90 }}
              value={p.agg as string}
              options={["first", "mean", "sum", "max", "min", "count"].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => setParam(index, "agg", v)}
            />
          </Space>
        );
      case "derive": {
        const exprs = (p.expressions as { name: string; expr: string }[]) ?? [];
        return (
          <Space direction="vertical" style={{ width: "100%" }}>
            {exprs.map((ex, ei) => (
              <Space key={ei} wrap>
                <Input
                  placeholder={t("preparation.panel.params.newColumnPlaceholder")}
                  style={{ width: 160 }}
                  value={ex.name}
                  onChange={(e) => {
                    const next = exprs.map((x, i) =>
                      i === ei ? { ...x, name: e.target.value } : x,
                    );
                    setParam(index, "expressions", next);
                  }}
                />
                <Input
                  placeholder={t("preparation.panel.params.expressionPlaceholder")}
                  style={{ width: 320 }}
                  value={ex.expr}
                  onChange={(e) => {
                    const next = exprs.map((x, i) =>
                      i === ei ? { ...x, expr: e.target.value } : x,
                    );
                    setParam(index, "expressions", next);
                  }}
                />
                <Button
                  size="small"
                  danger
                  disabled={exprs.length <= 1}
                  onClick={() =>
                    setParam(
                      index,
                      "expressions",
                      exprs.filter((_, i) => i !== ei),
                    )
                  }
                >
                  {t("preparation.panel.params.delete")}
                </Button>
              </Space>
            ))}
            <Button
              size="small"
              onClick={() => setParam(index, "expressions", [...exprs, { name: "", expr: "" }])}
            >
              {t("preparation.panel.params.addExpression")}
            </Button>
          </Space>
        );
      }
    }
  };

  const formView = (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card size="small" title={t("preparation.panel.target.title")}>
        <Space wrap>
          <span>{t("preparation.panel.target.timeColumn")}</span>
          <Select
            style={{ width: 170 }}
            value={config.target.time_col ?? ""}
            options={optionalColumnOptions}
            onChange={(v) =>
              update({ ...config, target: { ...config.target, time_col: v || null } })
            }
          />
          <span>{t("preparation.panel.target.eventColumn")}</span>
          <Select
            style={{ width: 170 }}
            value={config.target.event_col ?? ""}
            options={optionalColumnOptions}
            onChange={(v) =>
              update({ ...config, target: { ...config.target, event_col: v || null } })
            }
          />
          <span>{t("preparation.panel.target.labelColumn")}</span>
          <Select
            style={{ width: 170 }}
            value={config.target.label_col ?? ""}
            options={optionalColumnOptions}
            onChange={(v) =>
              update({ ...config, target: { ...config.target, label_col: v || null } })
            }
          />
        </Space>
      </Card>

      <Card
        size="small"
        title={t("preparation.panel.steps.title")}
        extra={
          <Space>
            <Select<StepType>
              placeholder={t("preparation.panel.steps.addStep")}
              style={{ width: 130 }}
              value={undefined}
              options={STEP_TYPES.map((stepType) => ({
                value: stepType,
                label: t(STEP_LABEL_KEYS[stepType]),
              }))}
              onChange={(stepType) =>
                update({
                  ...config,
                  steps: [
                    ...config.steps,
                    { type: stepType, params: { ...DEFAULT_STEP_PARAMS[stepType] } },
                  ],
                })
              }
            />
          </Space>
        }
      >
        <Collapse
          items={config.steps.map((step, i) => ({
            key: String(i),
            label: (
              <Space>
                <Tag>{i + 1}</Tag>
                <span>{t(STEP_LABEL_KEYS[step.type])}</span>
                <Typography.Text code>{step.type}</Typography.Text>
              </Space>
            ),
            extra: (
              <Button
                size="small"
                danger
                disabled={config.steps.length <= 1}
                onClick={(e) => {
                  e.stopPropagation();
                  update({ ...config, steps: config.steps.filter((_, j) => j !== i) });
                }}
              >
                {t("preparation.panel.steps.remove")}
              </Button>
            ),
            children: paramControls(step, i),
          }))}
        />
      </Card>

      <Card size="small" title={t("preparation.panel.validation.title")}>
        <Space wrap>
          <span>{t("preparation.panel.validation.strategy")}</span>
          <Select
            style={{ width: 170 }}
            value={config.validation.strategy}
            options={[
              { value: "stratified_kfold", label: "stratified_kfold" },
              { value: "kfold", label: "kfold" },
            ]}
            onChange={(v) =>
              update({ ...config, validation: { ...config.validation, strategy: v } })
            }
          />
          <span>{t("preparation.panel.validation.splits")}</span>
          <InputNumber
            min={2}
            max={10}
            value={config.validation.n_splits}
            onChange={(v) =>
              update({ ...config, validation: { ...config.validation, n_splits: v ?? 5 } })
            }
          />
          <span>{t("preparation.panel.validation.seed")}</span>
          <InputNumber
            min={0}
            value={config.validation.seed}
            onChange={(v) =>
              update({ ...config, validation: { ...config.validation, seed: v ?? 42 } })
            }
          />
        </Space>
      </Card>
    </Space>
  );

  return (
    <Card
      title={t("preparation.panel.title")}
      style={{ marginBottom: 16 }}
      extra={
        <Space>
          <Button onClick={() => void onRecommend()} loading={busy}>
            {t("preparation.panel.recommend")}
          </Button>
          <Button type="primary" onClick={() => void onValidate()} loading={busy}>
            {t("preparation.panel.validate")}
          </Button>
        </Space>
      }
    >
      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          message={t("preparation.panel.validationFailedTitle")}
          description={
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {errors.slice(0, 5).map((e, i) => (
                <li key={i}>{e}</li>
              ))}
            </ul>
          }
          style={{ marginBottom: 12 }}
        />
      )}
      <Tabs
        items={[
          { key: "form", label: t("preparation.panel.tabs.form"), children: formView },
          {
            key: "json",
            label: t("preparation.panel.tabs.json"),
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Input.TextArea
                  rows={18}
                  value={jsonDraft ?? JSON.stringify(config, null, 2)}
                  onChange={(e) => setJsonDraft(e.target.value)}
                />
                <Space>
                  <Button onClick={() => setJsonDraft(null)}>
                    {t("preparation.panel.resetToForm")}
                  </Button>
                  <Button type="primary" onClick={applyJson} disabled={jsonDraft == null}>
                    {t("preparation.panel.applyToForm")}
                  </Button>
                </Space>
              </Space>
            ),
          },
        ]}
      />
    </Card>
  );
}
