/** 数据准备向导 4 步页（docs/05 §8；docs/11 §2；P0-1e）。
 *
 * 机器做苦力，医生做选择题：
 * 1 选表 — 化验长表 + 诊断表（同项目、VALIDATED）；
 * 2 决策 — 进入即自动扫描预览：列识别/诊断词条/药敏统计；用户勾选结局词条，
 *    其余决策点用引擎建议默认值填充，可调；
 * 3 确认 — 全参数摘要 → 提交（202）→ 2s 轮询任务直至 COMPLETED/FAILED；
 * 4 结果 — 每阶段行数审计摘要 + 直达宽表数据集/新建分析。
 */

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Descriptions,
  Form,
  InputNumber,
  Radio,
  Result,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import LanguageSwitcher from "../components/LanguageSwitcher";
import {
  getPreparationJob,
  listDatasets,
  preparationApply,
  preparationPreview,
  type ApiError,
  type DatasetDetail,
  type PreparationDecisions,
  type PreparationJob,
  type PreparationPreview,
} from "../api";

const STEP_TITLE_KEYS = [
  "preparation.wizard.steps.selectTables",
  "preparation.wizard.steps.decisions",
  "preparation.wizard.steps.confirm",
  "preparation.wizard.steps.result",
] as const;

const DEFAULT_DECISIONS: PreparationDecisions = {
  outcome_terms: [],
  outcome_scope: "any",
  index_diagnosis: "first",
  window_days: 30,
  value_strategy: "latest",
  value_column: "归一化值",
  exclude_susceptibility: true,
  clip_quantile: 0.99,
  top_n_items: 200,
};

/** summary 键 → 本地化说明键（与 engines/preparation.py 输出一一对应）。 */
const SUMMARY_LABEL_KEYS: Record<string, string> = {
  lab_rows_in: "preparation.summary.labRowsIn",
  diag_rows_in: "preparation.summary.diagnosisRowsIn",
  patients: "preparation.summary.patients",
  label_positive: "preparation.summary.positivePatients",
  susceptibility_removed: "preparation.summary.susceptibilityRemoved",
  lab_rows_value_ok: "preparation.summary.validValueRows",
  lab_rows_bad_date_dropped: "preparation.summary.missingLabDateRowsRemoved",
  clipped_rows: "preparation.summary.clippedRows",
  features: "preparation.summary.retainedFeatures",
  leakage_removed: "preparation.summary.leakageRemoved",
  outside_window_removed: "preparation.summary.outsideWindowRemoved",
  wide_rows: "preparation.summary.wideRows",
  wide_cols: "preparation.summary.wideColumns",
};

/** 后端提交值保持不变；仅为已知取值列提供本地化展示名。 */
const VALUE_COLUMN_LABEL_KEYS: Record<string, string> = {
  归一化值: "preparation.wizard.valueColumns.normalized",
  结果: "preparation.wizard.valueColumns.result",
};

export default function PreparationWizardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const [step, setStep] = useState(0);
  // Step 1
  const [datasets, setDatasets] = useState<DatasetDetail[] | null>(null);
  const [labId, setLabId] = useState<string | null>(null);
  const [diagId, setDiagId] = useState<string | null>(null);
  // Step 2
  const [preview, setPreview] = useState<PreparationPreview | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [decisions, setDecisions] = useState<PreparationDecisions>(DEFAULT_DECISIONS);
  // Step 3/4
  const [submitting, setSubmitting] = useState(false);
  const [job, setJob] = useState<PreparationJob | null>(null);

  useEffect(() => {
    if (!projectId) return;
    listDatasets(projectId)
      .then((page) => setDatasets(page.items))
      .catch((e) => message.error((e as ApiError).message || t("preparation.wizard.messages.loadDatasetsFailed")));
  }, [projectId, t]);

  // 进入 Step 2：自动扫描预览，并用建议默认值回填决策
  useEffect(() => {
    if (step !== 1 || !labId || !diagId || preview || previewError) return;
    preparationPreview(labId, diagId)
      .then((prev) => {
        setPreview(prev);
        setDecisions((d) => ({ ...d, ...prev.suggested, outcome_terms: d.outcome_terms }));
      })
      .catch((e) => setPreviewError((e as ApiError).message || t("preparation.wizard.messages.previewFailed")));
  }, [step, labId, diagId, preview, previewError, t]);

  // 提交后轮询任务（2s），终态停止
  useEffect(() => {
    if (!job || job.status === "COMPLETED" || job.status === "FAILED") return;
    const timer = setInterval(() => {
      getPreparationJob(job.id)
        .then(setJob)
        .catch(() => undefined);
    }, 2000);
    return () => clearInterval(timer);
  }, [job]);

  // 原始长表通常因缺结局列而校验 FAILED —— 这正是数据准备要解决的问题，故可选
  const selectable = useMemo(
    () => (datasets ?? []).filter((d) => d.status === "VALIDATED" || d.status === "FAILED"),
    [datasets],
  );
  const datasetOptions = selectable.map((d) => ({
    value: d.id,
    label: t("preparation.wizard.datasetOption", {
      name: d.name,
      rows: d.preview?.total_rows ?? "?",
    }),
  }));

  const canNext = useMemo(() => {
    switch (step) {
      case 0:
        return labId != null && diagId != null && labId !== diagId;
      case 1:
        return preview != null && decisions.outcome_terms.length > 0;
      default:
        return true;
    }
  }, [step, labId, diagId, preview, decisions.outcome_terms]);

  const submit = async () => {
    if (!labId || !diagId) return;
    setSubmitting(true);
    try {
      const created = await preparationApply(labId, diagId, decisions);
      setJob(created);
      setStep(3);
    } catch (e) {
      message.error((e as ApiError).message || t("preparation.wizard.messages.submitFailed"));
    } finally {
      setSubmitting(false);
    }
  };

  const set = <K extends keyof PreparationDecisions>(key: K, value: PreparationDecisions[K]) =>
    setDecisions((d) => ({ ...d, [key]: value }));

  const nameOf = (id: string | null) => datasets?.find((d) => d.id === id)?.name ?? "—";
  const valueColumnLabel = (column: string) => {
    const labelKey = VALUE_COLUMN_LABEL_KEYS[column];
    return labelKey ? t(labelKey) : column;
  };
  const summaryLabel = (key: string) => {
    const labelKey = SUMMARY_LABEL_KEYS[key];
    return labelKey ? t(labelKey) : key;
  };
  const outcomeScopeSummary =
    decisions.outcome_scope === "any"
      ? t("preparation.wizard.options.scopeAnySummary")
      : t("preparation.wizard.options.scopeIndexSummary");
  const indexDiagnosisSummary =
    decisions.index_diagnosis === "first"
      ? t("preparation.wizard.options.firstSummary")
      : t("preparation.wizard.options.lastSummary");
  const valueStrategySummary =
    decisions.value_strategy === "latest"
      ? t("preparation.wizard.options.latest")
      : t("preparation.wizard.options.mean");
  const cleaningSummaryKey =
    decisions.exclude_susceptibility && decisions.clip_quantile > 0
      ? "preparation.wizard.confirm.cleaningBoth"
      : decisions.exclude_susceptibility
        ? "preparation.wizard.confirm.cleaningSusceptibilityOnly"
        : decisions.clip_quantile > 0
          ? "preparation.wizard.confirm.cleaningClippingOnly"
          : "preparation.wizard.confirm.cleaningNone";

  const stepContent = [
    // Step 1 选表
    <Card key="s1" title={t("preparation.wizard.selectTables.title")}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <div>
          <Typography.Text strong>{t("preparation.wizard.selectTables.labTable")}</Typography.Text>
          <Select
            style={{ width: "100%", marginTop: 8 }}
            placeholder={t("preparation.wizard.selectTables.labPlaceholder")}
            loading={datasets === null}
            value={labId ?? undefined}
            options={datasetOptions}
            onChange={(v) => {
              setLabId(v);
              setPreview(null);
              setPreviewError(null);
            }}
          />
        </div>
        <div>
          <Typography.Text strong>
            {t("preparation.wizard.selectTables.diagnosisTable")}
          </Typography.Text>
          <Select
            style={{ width: "100%", marginTop: 8 }}
            placeholder={t("preparation.wizard.selectTables.diagnosisPlaceholder")}
            loading={datasets === null}
            value={diagId ?? undefined}
            options={datasetOptions}
            onChange={(v) => {
              setDiagId(v);
              setPreview(null);
              setPreviewError(null);
            }}
          />
        </div>
        {datasets !== null && selectable.length < 2 && (
          <Alert
            type="warning"
            showIcon
            message={t("preparation.wizard.selectTables.insufficientDatasets")}
          />
        )}
      </Space>
    </Card>,
    // Step 2 决策
    <Card key="s2" title={t("preparation.wizard.decisions.title")}>
      {!preview && !previewError && <Spin tip={t("preparation.wizard.decisions.scanning")} />}
      {previewError && (
        <Alert
          type="error"
          showIcon
          message={t("preparation.wizard.decisions.previewFailedTitle")}
          description={previewError}
        />
      )}
      {preview && (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Space size="large" wrap>
            <Statistic
              title={t("preparation.wizard.decisions.patientsIntersection")}
              value={preview.patients_intersection}
            />
            <Statistic title={t("preparation.wizard.decisions.labRows")} value={preview.lab_rows} />
            <Statistic
              title={t("preparation.wizard.decisions.diagnosisRows")}
              value={preview.diag_rows}
            />
            <Statistic
              title={t("preparation.wizard.decisions.susceptibilityRows")}
              value={preview.susceptibility_rows}
            />
          </Space>
          <div>
            <Typography.Title level={5}>
              {t("preparation.wizard.decisions.outcomeTitle")}
            </Typography.Title>
            <Checkbox.Group
              style={{ width: "100%" }}
              value={decisions.outcome_terms}
              onChange={(v) => set("outcome_terms", v as string[])}
            >
              <Table
                rowKey="term"
                size="small"
                dataSource={preview.diagnosis_terms}
                pagination={{ pageSize: 8, size: "small" }}
                columns={[
                  {
                    title: t("preparation.wizard.decisions.columns.select"),
                    width: 60,
                    render: (_, term) => <Checkbox value={term.term} />,
                  },
                  { title: t("preparation.wizard.decisions.columns.term"), dataIndex: "term" },
                  {
                    title: t("preparation.wizard.decisions.columns.count"),
                    dataIndex: "count",
                    width: 100,
                  },
                ]}
              />
            </Checkbox.Group>
          </div>
          <Form layout="vertical">
            <Form.Item label={t("preparation.wizard.decisions.outcomeScope")}>
              <Radio.Group
                value={decisions.outcome_scope}
                onChange={(e) => set("outcome_scope", e.target.value)}
                options={[
                  { value: "any", label: t("preparation.wizard.options.outcomeScopeAny") },
                  { value: "index", label: t("preparation.wizard.options.outcomeScopeIndex") },
                ]}
              />
            </Form.Item>
            <Form.Item label={t("preparation.wizard.decisions.indexDiagnosis")}>
              <Radio.Group
                value={decisions.index_diagnosis}
                onChange={(e) => set("index_diagnosis", e.target.value)}
                options={[
                  { value: "first", label: t("preparation.wizard.options.indexFirst") },
                  { value: "last", label: t("preparation.wizard.options.indexLast") },
                ]}
              />
            </Form.Item>
            <Space size="large" wrap>
              <Form.Item label={t("preparation.wizard.decisions.windowDays")}>
                <InputNumber
                  min={0}
                  value={decisions.window_days}
                  onChange={(v) => set("window_days", v ?? 0)}
                />
              </Form.Item>
              <Form.Item label={t("preparation.wizard.decisions.valueStrategy")}>
                <Radio.Group
                  value={decisions.value_strategy}
                  onChange={(e) => set("value_strategy", e.target.value)}
                  options={[
                    { value: "latest", label: t("preparation.wizard.options.latest") },
                    { value: "mean", label: t("preparation.wizard.options.mean") },
                  ]}
                />
              </Form.Item>
              <Form.Item label={t("preparation.wizard.decisions.valueColumn")}>
                <Select
                  style={{ width: 160 }}
                  value={decisions.value_column}
                  options={[preview.lab_columns.value, "归一化值", "结果"]
                    .filter((c): c is string => c != null)
                    .filter((c, i, arr) => arr.indexOf(c) === i)
                    .map((column) => ({ value: column, label: valueColumnLabel(column) }))}
                  onChange={(v) => set("value_column", v)}
                />
              </Form.Item>
              <Form.Item label={t("preparation.wizard.decisions.excludeSusceptibility")}>
                <Switch
                  checked={decisions.exclude_susceptibility}
                  onChange={(v) => set("exclude_susceptibility", v)}
                />
              </Form.Item>
              <Form.Item label={t("preparation.wizard.decisions.clipQuantile")}>
                <InputNumber
                  min={0}
                  max={0.999}
                  step={0.01}
                  value={decisions.clip_quantile}
                  onChange={(v) => set("clip_quantile", v ?? 0)}
                />
              </Form.Item>
              <Form.Item label={t("preparation.wizard.decisions.topNItems")}>
                <InputNumber
                  min={1}
                  value={decisions.top_n_items}
                  onChange={(v) => set("top_n_items", v ?? 200)}
                />
              </Form.Item>
            </Space>
          </Form>
        </Space>
      )}
    </Card>,
    // Step 3 确认
    <Card key="s3" title={t("preparation.wizard.confirm.title")}>
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label={t("preparation.wizard.confirm.labTable")}>
          {nameOf(labId)}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.diagnosisTable")}>
          {nameOf(diagId)}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.outcomeTerms")}>
          {decisions.outcome_terms.map((t) => (
            <Tag key={t} color="red">
              {t}
            </Tag>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.scope")}>
          {outcomeScopeSummary}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.indexDiagnosis")}>
          {indexDiagnosisSummary}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.timeWindow")}>
          {decisions.window_days === 0
            ? t("preparation.wizard.confirm.windowUnlimited")
            : t("preparation.wizard.confirm.windowDays", { days: decisions.window_days })}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.valueStrategy")}>
          {t("preparation.wizard.confirm.valueStrategySummary", {
            strategy: valueStrategySummary,
            column: valueColumnLabel(decisions.value_column),
          })}
        </Descriptions.Item>
        <Descriptions.Item label={t("preparation.wizard.confirm.cleaning")}>
          {t(cleaningSummaryKey, {
            quantile: decisions.clip_quantile,
            topN: decisions.top_n_items,
          })}
        </Descriptions.Item>
      </Descriptions>
    </Card>,
    // Step 4 结果
    <Card key="s4">
      {!job || (job.status !== "COMPLETED" && job.status !== "FAILED") ? (
        <Result
          icon={<Spin size="large" />}
          title={t("preparation.wizard.result.processingTitle")}
          subTitle={t("preparation.wizard.result.processingSubtitle")}
        />
      ) : job.status === "FAILED" ? (
        <Result
          status="error"
          title={t("preparation.wizard.result.failedTitle")}
          subTitle={job.error ?? t("preparation.wizard.result.unknownError")}
        />
      ) : (
        <Result
          status="success"
          title={t("preparation.wizard.result.successTitle")}
          subTitle={
            <Space size="large" wrap style={{ justifyContent: "center", marginTop: 8 }}>
              <Statistic
                title={t("preparation.wizard.result.patients")}
                value={job.summary?.patients ?? 0}
              />
              <Statistic
                title={t("preparation.wizard.result.positiveOutcomes")}
                value={job.summary?.label_positive ?? 0}
              />
              <Statistic
                title={t("preparation.wizard.result.features")}
                value={job.summary?.features ?? 0}
              />
              <Statistic
                title={t("preparation.wizard.result.leakageRemoved")}
                value={job.summary?.leakage_removed ?? 0}
              />
            </Space>
          }
          extra={[
            <Button
              type="primary"
              key="analyze"
              onClick={() =>
                navigate(`/projects/${projectId}/analysis/new?dataset=${job.result_dataset_id}`)
              }
            >
              {t("preparation.wizard.result.newAnalysis")}
            </Button>,
            <Button key="dataset" onClick={() => navigate(`/datasets/${job.result_dataset_id}`)}>
              {t("preparation.wizard.result.viewDataset")}
            </Button>,
          ]}
        />
      )}
      {job?.status === "COMPLETED" && job.summary && (
        <Table
          style={{ marginTop: 16 }}
          size="small"
          pagination={false}
          dataSource={Object.entries(job.summary).map(([k, v]) => ({ key: k, name: k, value: v }))}
          columns={[
            {
              title: t("preparation.wizard.result.auditItem"),
              dataIndex: "name",
              render: (key: string) => summaryLabel(key),
            },
            { title: t("preparation.wizard.result.value"), dataIndex: "value", width: 140 },
          ]}
        />
      )}
    </Card>,
  ];

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("preparation.wizard.title")}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          <Button onClick={() => navigate(projectId ? `/projects/${projectId}` : "/projects")}>
            {t("preparation.wizard.cancel")}
          </Button>
        </Space>
      </Space>
      <Steps current={step} items={STEP_TITLE_KEYS.map((key) => ({ title: t(key) }))} size="small" />
      <div style={{ margin: "24px 0" }}>{stepContent[step]}</div>
      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        {step > 0 && step < 3 && (
          <Button onClick={() => setStep((s) => s - 1)}>{t("preparation.wizard.previous")}</Button>
        )}
        {step < STEP_TITLE_KEYS.length - 2 && (
          <Button type="primary" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            {t("preparation.wizard.next")}
          </Button>
        )}
        {step === STEP_TITLE_KEYS.length - 2 && (
          <Button type="primary" loading={submitting} onClick={() => void submit()}>
            {t("preparation.wizard.submit")}
          </Button>
        )}
      </Space>
    </div>
  );
}
