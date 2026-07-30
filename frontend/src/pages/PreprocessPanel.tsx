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
import { useState } from "react";
import {
  DEFAULT_STEP_PARAMS,
  recommendPreprocess,
  validatePreprocess,
  type ApiError,
  type PreprocessConfig,
  type PreprocessStep,
  type StepType,
} from "../api";

const STEP_LABEL: Record<StepType, string> = {
  reshape: "长转宽",
  drop_columns: "删除列",
  missing: "缺失值",
  outlier: "异常值",
  encode: "编码",
  scale: "缩放",
  feature_select: "特征选择",
  derive: "派生列",
};

const STEP_TYPES = Object.keys(STEP_LABEL) as StepType[];

interface Props {
  datasetId: string;
  columns: string[];
  onChange?: (config: PreprocessConfig) => void;
}

const EMPTY_CONFIG: PreprocessConfig = {
  target: {},
  steps: [{ type: "missing", params: { ...DEFAULT_STEP_PARAMS.missing } }],
  validation: { strategy: "kfold", n_splits: 5, seed: 42 },
};

export default function PreprocessPanel({ datasetId, columns, onChange }: Props) {
  const [config, setConfig] = useState<PreprocessConfig>(EMPTY_CONFIG);
  const [jsonDraft, setJsonDraft] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  const update = (next: PreprocessConfig) => {
    setConfig(next);
    setErrors([]);
    onChange?.(next);
  };

  const setStep = (index: number, step: PreprocessStep) => {
    const steps = config.steps.map((s, i) => (i === index ? step : s));
    update({ ...config, steps });
  };

  const setParam = (index: number, key: string, value: unknown) => {
    const step = config.steps[index];
    setStep(index, { ...step, params: { ...step.params, [key]: value } });
  };

  const columnOptions = columns.map((c) => ({ value: c, label: c }));
  const optionalColumnOptions = [{ value: "", label: "（无）" }, ...columnOptions];

  const onRecommend = async () => {
    setBusy(true);
    try {
      const cfg = await recommendPreprocess(datasetId);
      update(cfg);
      message.success("已按列类型/语义生成推荐配置");
    } catch (e) {
      message.error((e as ApiError).message || "推荐配置生成失败");
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
      message.success("DSL 校验通过");
    } catch (e) {
      const err = e as ApiError;
      const details = err.details?.errors;
      setErrors(
        Array.isArray(details)
          ? details.map((d) => JSON.stringify(d))
          : [err.message || "校验失败"],
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
        message.error("缺少 target / steps / validation 顶层字段");
        return;
      }
      update(parsed);
      setJsonDraft(null);
      message.success("已应用到表单");
    } catch {
      message.error("JSON 解析失败，请检查语法");
    }
  };

  const paramControls = (step: PreprocessStep, index: number) => {
    const p = step.params;
    switch (step.type) {
      case "missing":
        return (
          <Space wrap>
            <span>默认策略</span>
            <Select
              style={{ width: 120 }}
              value={p.default as string}
              options={["median", "mean", "mode", "knn", "constant"].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => setParam(index, "default", v)}
            />
            <span>删除阈值</span>
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
            <span>方法</span>
            <Select
              style={{ width: 110 }}
              value={p.method as string}
              options={["iqr", "zscore"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>动作</span>
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
            <span>方法</span>
            <Select
              style={{ width: 110 }}
              value={p.method as string}
              options={["auto", "onehot", "ordinal"].map((v) => ({ value: v, label: v }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>One-Hot 基数上限</span>
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
            <span>方法</span>
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
            <span>方法</span>
            <Select
              style={{ width: 180 }}
              value={p.method as string}
              options={["variance_threshold", "correlation", "univariate", "lasso"].map((v) => ({
                value: v,
                label: v,
              }))}
              onChange={(v) => setParam(index, "method", v)}
            />
            <span>阈值</span>
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
            placeholder="选择要删除的列"
            value={(p.columns as string[]) ?? []}
            options={columnOptions}
            onChange={(v) => setParam(index, "columns", v)}
          />
        );
      case "reshape":
        return (
          <Space wrap>
            <span>主键列</span>
            <Select
              style={{ width: 160 }}
              value={(p.index as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "index", v)}
            />
            <span>名称列</span>
            <Select
              style={{ width: 160 }}
              value={(p.columns as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "columns", v)}
            />
            <span>值列</span>
            <Select
              style={{ width: 160 }}
              value={(p.values as string) || undefined}
              options={columnOptions}
              onChange={(v) => setParam(index, "values", v)}
            />
            <span>聚合</span>
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
                  placeholder="新列名"
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
                  placeholder="表达式，如 os_months / 12"
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
                  删除
                </Button>
              </Space>
            ))}
            <Button
              size="small"
              onClick={() => setParam(index, "expressions", [...exprs, { name: "", expr: "" }])}
            >
              添加表达式
            </Button>
          </Space>
        );
      }
    }
  };

  const formView = (
    <Space direction="vertical" style={{ width: "100%" }} size="middle">
      <Card size="small" title="结局定义（target）">
        <Space wrap>
          <span>随访时间列</span>
          <Select
            style={{ width: 170 }}
            value={config.target.time_col ?? ""}
            options={optionalColumnOptions}
            onChange={(v) =>
              update({ ...config, target: { ...config.target, time_col: v || null } })
            }
          />
          <span>事件列</span>
          <Select
            style={{ width: 170 }}
            value={config.target.event_col ?? ""}
            options={optionalColumnOptions}
            onChange={(v) =>
              update({ ...config, target: { ...config.target, event_col: v || null } })
            }
          />
          <span>标签列</span>
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
        title="预处理步骤（steps，按顺序执行）"
        extra={
          <Space>
            <Select<StepType>
              placeholder="添加步骤"
              style={{ width: 130 }}
              value={undefined}
              options={STEP_TYPES.map((t) => ({ value: t, label: STEP_LABEL[t] }))}
              onChange={(t) =>
                update({
                  ...config,
                  steps: [
                    ...config.steps,
                    { type: t, params: { ...DEFAULT_STEP_PARAMS[t] } },
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
                <span>{STEP_LABEL[step.type]}</span>
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
                移除
              </Button>
            ),
            children: paramControls(step, i),
          }))}
        />
      </Card>

      <Card size="small" title="交叉验证（validation）">
        <Space wrap>
          <span>策略</span>
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
          <span>折数</span>
          <InputNumber
            min={2}
            max={10}
            value={config.validation.n_splits}
            onChange={(v) =>
              update({ ...config, validation: { ...config.validation, n_splits: v ?? 5 } })
            }
          />
          <span>随机种子</span>
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
      title="预处理配置"
      style={{ marginBottom: 16 }}
      extra={
        <Space>
          <Button onClick={() => void onRecommend()} loading={busy}>
            推荐配置
          </Button>
          <Button type="primary" onClick={() => void onValidate()} loading={busy}>
            校验
          </Button>
        </Space>
      }
    >
      {errors.length > 0 && (
        <Alert
          type="error"
          showIcon
          message="DSL 校验失败"
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
          { key: "form", label: "表单", children: formView },
          {
            key: "json",
            label: "DSL JSON",
            children: (
              <Space direction="vertical" style={{ width: "100%" }}>
                <Input.TextArea
                  rows={18}
                  value={jsonDraft ?? JSON.stringify(config, null, 2)}
                  onChange={(e) => setJsonDraft(e.target.value)}
                />
                <Space>
                  <Button onClick={() => setJsonDraft(null)}>还原为表单内容</Button>
                  <Button type="primary" onClick={applyJson} disabled={jsonDraft == null}>
                    应用到表单
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
