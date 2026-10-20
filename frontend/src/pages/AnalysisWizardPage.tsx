/** 分析向导 5 步页（docs/11 §2.2；docs/18 T8.2；验收 G1：≤6 点击到报告）。
 *
 * 默认值策略（ blueprint §2.2 ）：
 * 1 数据集 — 支持 ?dataset= 预选（数据集页「开始分析」直达）；
 * 2 预处理 — 进入即自动「推荐配置」填充，可改可校验；
 * 3 任务类型 — 进入即自动识别，推荐项默认选中，可覆盖；确认后按候选列回填 target；
 * 4 模型 — 按任务类型过滤（GET /models），T6.12 分层：默认勾选标准套餐，其余折叠为高级选项；
 * 5 确认 — 全参数摘要 → 提交（POST /analysis-runs）→ 跳运行监控。
 */

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Descriptions,
  Select,
  Space,
  Spin,
  Statistic,
  Steps,
  Table,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  createRun,
  detectTask,
  getAnalysisDraft,
  getDataset,
  getResearchTemplates,
  listDatasetVersions,
  listDatasets,
  listModels,
  recommendPreprocess,
  type AnalysisDraft,
  type ApiError,
  type ColumnProfile,
  type DatasetDetail,
  type ModelPlugin,
  type PreprocessConfig,
  type ResearchTemplateSuggestion,
  type RerunSuggestion,
  type TaskDetectionResult,
  type TaskType,
} from "../api";
import LanguageSwitcher from "../components/LanguageSwitcher";
import PreprocessPanel from "./PreprocessPanel";

const TASK_TYPES: TaskType[] = ["survival", "classification", "regression"];
const STEP_KEYS = ["selectDataset", "preprocessing", "taskType", "models", "confirm"] as const;

function mergeDetectionTarget(
  config: PreprocessConfig,
  detection: TaskDetectionResult | null,
  taskType: TaskType | null,
): PreprocessConfig {
  if (!detection || !taskType) return config;
  const top = (kind: "time_col" | "event_col" | "label_col") =>
    detection.candidates[kind]?.[0]?.column ?? null;
  const target = { ...config.target };
  if (taskType === "survival") {
    target.time_col = target.time_col || top("time_col");
    target.event_col = target.event_col || top("event_col");
  } else {
    target.label_col = target.label_col || top("label_col");
  }
  return { ...config, target };
}

/**
 * T6.13：把迭代建议落到推荐预处理配置上（drop_columns 步骤是剔除变量的具体机制）。
 * add_features 从既有 drop_columns 中移除（确保保留）；drop_features 并入/新增 drop_columns 步骤。
 */
function applyIterateSuggestion(
  cfg: PreprocessConfig,
  suggestion: RerunSuggestion,
): PreprocessConfig {
  const add = new Set(suggestion.add_features);
  const drop = new Set(suggestion.drop_features);
  if (add.size === 0 && drop.size === 0) return cfg;
  const steps = cfg.steps.map((s) => {
    if (s.type !== "drop_columns") return s;
    const cols = ((s.params?.columns as string[] | undefined) ?? []).filter((c) => !add.has(c));
    return { ...s, params: { ...s.params, columns: cols } };
  });
  if (drop.size > 0) {
    const idx = steps.findIndex((s) => s.type === "drop_columns");
    if (idx >= 0) {
      const cols = (steps[idx].params?.columns as string[] | undefined) ?? [];
      steps[idx] = {
        ...steps[idx],
        params: { ...steps[idx].params, columns: [...new Set([...cols, ...drop])] },
      };
    } else {
      steps.push({ type: "drop_columns", params: { columns: [...drop] } });
    }
  }
  return { ...cfg, steps };
}

export default function AnalysisWizardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const taskTypeLabel = useCallback((value: TaskType) => t(`analysis.taskTypes.${value}`), [t]);
  const inferredTypeLabel = useCallback(
    (value: string) => {
      if (value === "text" || value === "datetime" || value === "id") {
        return t(`analysis.inferredTypes.${value}`);
      }
      return value;
    },
    [t],
  );
  const candidateKindLabel = useCallback(
    (kind: string) => {
      if (kind === "time_col" || kind === "event_col" || kind === "label_col") {
        return t(`analysis.detection.candidateKinds.${kind}`);
      }
      return kind;
    },
    [t],
  );
  // T6.13：比较页「按建议重跑」经 location.state 传入结构化建议（仅首次装载生效）
  const location = useLocation();
  const [iterateSuggestion] = useState<RerunSuggestion | null>(
    () => (location.state as { iterate?: RerunSuggestion } | null)?.iterate ?? null,
  );

  const [step, setStep] = useState(0);
  // Step 1
  const [datasets, setDatasets] = useState<DatasetDetail[] | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(searchParams.get("dataset"));
  // T6.9 科研流程模板（Step 1 选定数据集后加载）
  const [templates, setTemplates] = useState<ResearchTemplateSuggestion[] | null>(null);
  // Step 2
  const [columns, setColumns] = useState<string[]>([]);
  const [profile, setProfile] = useState<ColumnProfile[] | null>(null);
  const [recommended, setRecommended] = useState<PreprocessConfig | null>(null);
  const [config, setConfig] = useState<PreprocessConfig | null>(null);
  // Step 3
  const [detection, setDetection] = useState<TaskDetectionResult | null>(null);
  const [detectFailed, setDetectFailed] = useState<string | null>(null);
  // P0-4：数据集页「确认任务类型」经 ?task= 预选，识别结果不再覆盖用户确认值
  const initialTask = searchParams.get("task") as TaskType | null;
  const [taskType, setTaskType] = useState<TaskType | null>(
    initialTask && ["survival", "classification", "regression"].includes(initialTask)
      ? initialTask
      : null,
  );
  // Step 4
  const [models, setModels] = useState<ModelPlugin[] | null>(null);
  const [selectedModels, setSelectedModels] = useState<string[]>(
    () => iterateSuggestion?.selected_models ?? [],
  );
  // Step 5
  const [submitting, setSubmitting] = useState(false);

  // P1-3 单页确认模式：带 ?dataset= 进入（数据集页「开始分析」/体检卡直达）时，
  // 草稿端点一次给齐默认值（任务+预处理+标准套餐模型），一页确认即提交；
  // 「逐步调整」可随时切回完整向导。
  const [fullWizard, setFullWizard] = useState(false);
  const singlePage = !!searchParams.get("dataset") && !iterateSuggestion && !fullWizard;
  const [draft, setDraft] = useState<AnalysisDraft | null>(null);
  const [draftFailed, setDraftFailed] = useState(false);

  useEffect(() => {
    if (!singlePage || !datasetId || draft || draftFailed) return;
    getAnalysisDraft(datasetId)
      .then((d) => {
        const draftTask = d.task_type ?? d.task_detection?.recommended_task ?? null;
        const mergedConfig = mergeDetectionTarget(d.preprocess_config, d.task_detection, draftTask);
        setDraft(d);
        setRecommended(mergedConfig);
        setConfig(mergedConfig);
        if (d.task_detection) setDetection(d.task_detection);
        if (draftTask) setTaskType((prev) => prev ?? draftTask);
        if (d.standard_models.length > 0) {
          setSelectedModels((prev) => (prev.length > 0 ? prev : d.standard_models));
        }
      })
      .catch(() => setDraftFailed(true)); // 识别/草稿失败 → 回退逐步向导
    getDataset(datasetId)
      .then((ds) => {
        setColumns(ds.preview?.columns ?? []);
        setProfile(ds.column_profile);
      })
      .catch(() => undefined);
  }, [singlePage, datasetId, draft, draftFailed]);

  // 单页模式：按任务类型拉模型清单（切换任务后默认勾选该任务标准套餐）
  useEffect(() => {
    if (!singlePage || !taskType || models) return;
    listModels(taskType)
      .then((items) => {
        setModels(items);
        setSelectedModels((prev) => {
          const valid = prev.filter((k) => items.some((m) => m.key === k));
          if (valid.length > 0) return valid;
          const standard = items.filter((m) => m.tier === "standard").map((m) => m.key);
          return standard.length > 0 ? standard : items.map((m) => m.key);
        });
      })
      .catch(() => setDraftFailed(true));
  }, [singlePage, taskType, models]);

  // Step 1：项目内数据集（仅 VALIDATED 可选）
  useEffect(() => {
    if (!projectId) return;
    listDatasets(projectId)
      .then((page) => setDatasets(page.items))
      .catch((e) => message.error((e as ApiError).message || t("analysis.errors.loadDatasets")));
  }, [projectId, t]);

  // T6.9：选定数据集后加载科研流程模板（适用性 + 样本量核对，失败不阻塞向导）
  useEffect(() => {
    if (!datasetId) {
      setTemplates(null);
      return;
    }
    getResearchTemplates(datasetId)
      .then((res) => setTemplates(res.templates))
      .catch(() => setTemplates(null));
  }, [datasetId]);

  /** 应用模板：预填任务类型与推荐模型（进入后续步骤可改）。 */
  const applyTemplate = (template: ResearchTemplateSuggestion) => {
    setTaskType(template.task_type);
    setSelectedModels(template.models);
    message.success(t("analysis.messages.templateApplied", { name: template.name }));
  };

  // 进入 Step 2：取列名 + 自动推荐配置（默认值策略：推荐配置已填充）
  useEffect(() => {
    if (step !== 1 || !datasetId || recommended) return;
    getDataset(datasetId)
      .then((ds) => {
        setColumns(ds.preview?.columns ?? []);
        setProfile(ds.column_profile);
      })
      .catch(() => setColumns([]));
    recommendPreprocess(datasetId)
      .then((cfg) =>
        setRecommended(iterateSuggestion ? applyIterateSuggestion(cfg, iterateSuggestion) : cfg),
      )
      .catch((e) => message.error((e as ApiError).message || t("analysis.errors.recommendPreprocess")));
  }, [step, datasetId, recommended, iterateSuggestion, t]);

  // 进入 Step 3：自动识别任务类型（推荐项默认选中）
  useEffect(() => {
    if (step !== 2 || !datasetId || detection || detectFailed) return;
    detectTask(datasetId)
      .then((result) => {
        setDetection(result);
        setTaskType((prev) => prev ?? result.recommended_task);
      })
      .catch((e) => {
        const err = e as ApiError;
        if (err.code === "TASK_DETECTION_FAILED") setDetectFailed(err.message);
        else message.error(err.message || t("analysis.errors.detectTask"));
      });
  }, [step, datasetId, detection, detectFailed, t]);

  // 进入 Step 4：按任务类型拉取可用模型，默认勾选标准套餐（T6.12 分层）
  useEffect(() => {
    if (step !== 3 || !taskType) return;
    listModels(taskType)
      .then((items) => {
        setModels(items);
        setSelectedModels((prev) => {
          const valid = prev.filter((k) => items.some((m) => m.key === k));
          if (valid.length > 0) return valid;
          const standard = items.filter((m) => m.tier === "standard").map((m) => m.key);
          return standard.length > 0 ? standard : items.map((m) => m.key);
        });
      })
      .catch((e) => message.error((e as ApiError).message || t("analysis.errors.loadModels")));
  }, [step, taskType, t]);

  /** 任务确认后按识别候选回填 target（仅补空缺，不覆盖用户手填）。 */
  const applyDetectionToConfig = useCallback(() => {
    if (!config || !taskType) return;
    const top = (kind: "time_col" | "event_col" | "label_col") =>
      detection?.candidates[kind]?.[0]?.column ?? null;
    const target = { ...config.target };
    if (taskType === "survival") {
      target.time_col = target.time_col ?? top("time_col");
      target.event_col = target.event_col ?? top("event_col");
    } else {
      target.label_col = target.label_col ?? top("label_col");
    }
    setConfig({ ...config, target });
  }, [config, taskType, detection]);

  /** 生存分析硬约束：识别不到随访时间/结局事件列时阻断下一步（否则提交必然后端 400）。 */
  const survivalBlocked = useMemo(
    () => {
      if (taskType !== "survival") return false;
      const target = config?.target;
      const hasColumns = columns.length > 0;
      const hasTarget = !!target?.time_col && !!target?.event_col;
      const targetColumnsExist =
        hasTarget && columns.includes(target.time_col!) && columns.includes(target.event_col!);
      // 检测结果/列名仍在加载时保持阻断，避免单页确认误发无效 survival 请求。
      return detection == null || !hasColumns || !targetColumnsExist;
    },
    [taskType, config, columns, detection],
  );

  /**
   * 提交前镜像硬校验（docs/06 §2，2026-08-10）：只预判数学上必然失败的情形。
   * 规则 1 列存在性 + 规则 2/3 类型粗判（基于 column_profile）；
   * 规则 4（最小类别样本数）需精确计数，以后端 400 文案为准（toast 原样展示）。
   * 画像缺失（旧数据集）时不预判，绝不误拦。
   */
  const submitBlock = useMemo(() => {
    if (!config || !taskType) return null;
    const target = config.target;
    if (taskType === "survival" && survivalBlocked) {
      return t("analysis.validation.survivalMissingTargets");
    }
    const need =
      taskType === "survival" ? [target.time_col, target.event_col] : [target.label_col];
    const missing = need.filter((c): c is string => !!c && !columns.includes(c));
    if (missing.length > 0) {
      return t("analysis.validation.targetColumnsMissing", {
        columns: missing.join(t("analysis.validation.columnListSeparator")),
      });
    }
    if (!profile || !target.label_col) return null;
    const p = profile.find((c) => c.name === target.label_col);
    if (!p) return null;
    if (taskType === "regression" && ["text", "datetime", "id"].includes(p.inferred_type)) {
      return t("analysis.validation.regressionOutcomeMustBeNumeric", {
        column: target.label_col,
        type: inferredTypeLabel(p.inferred_type),
        classificationTask: taskTypeLabel("classification"),
      });
    }
    if (taskType === "classification" && p.unique < 2) {
      return t("analysis.validation.classificationOutcomeNeedsTwoClasses", { column: target.label_col });
    }
    return null;
  }, [config, taskType, columns, profile, survivalBlocked, t, inferredTypeLabel, taskTypeLabel]);

  const canNext = useMemo(() => {
    switch (step) {
      case 0:
        return datasetId != null;
      case 1:
        return config != null;
      case 2:
        return taskType != null && !survivalBlocked;
      case 3:
        return selectedModels.length > 0;
      default:
        return true;
    }
  }, [step, datasetId, config, taskType, selectedModels, survivalBlocked]);

  const next = () => {
    if (step === 2) applyDetectionToConfig();
    setStep((s) => s + 1);
  };

  const submit = async () => {
    if (
      !datasetId ||
      !config ||
      !taskType ||
      selectedModels.length === 0 ||
      submitBlock ||
      (taskType === "survival" && survivalBlocked)
    )
      return;
    setSubmitting(true);
    try {
      const versions = await listDatasetVersions(datasetId);
      const latest = versions[0]; // 服务端按 version_no 降序
      if (!latest) throw new Error(t("analysis.errors.noDatasetVersion"));
      const run = await createRun({
        dataset_version_id: latest.id,
        task_type: taskType,
        preprocess_config: config,
        selected_models: selectedModels,
      });
      message.success(t("analysis.messages.submitted"));
      navigate(`/runs/${run.id}`);
    } catch (e) {
      const err = e as ApiError;
      message.error(err.message || t("analysis.errors.submit"));
    } finally {
      setSubmitting(false);
    }
  };

  const datasetName = datasets?.find((d) => d.id === datasetId)?.name ?? datasetId ?? t("analysis.notAvailable");

  /** 单页模式任务切换：按识别候选重填结局列 + 重拉模型清单。 */
  const onSinglePageTaskChange = (v: TaskType) => {
    setTaskType(v);
    if (config && detection) {
      const top = (kind: "time_col" | "event_col" | "label_col") =>
        detection.candidates[kind]?.[0]?.column ?? null;
      const target = { ...config.target };
      if (v === "survival") {
        target.time_col = top("time_col");
        target.event_col = top("event_col");
        target.label_col = null;
      } else {
        target.label_col = top("label_col");
        target.time_col = null;
        target.event_col = null;
      }
      let nextCfg = { ...config, target };
      if (v === "regression" && nextCfg.validation.strategy === "stratified_kfold") {
        nextCfg = { ...nextCfg, validation: { ...nextCfg.validation, strategy: "kfold" } };
      }
      setConfig(nextCfg);
    }
    setModels(null);
    setSelectedModels([]);
  };

  // P1-3 单页确认：草稿就绪后一页展示全部默认值，一次点击提交
  if (singlePage && !draftFailed && !(draft && !draft.task_type)) {
    return (
      <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
        <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
          <Typography.Title level={3} style={{ margin: 0 }}>
            {t("analysis.singlePage.title")}
          </Typography.Title>
          <Space wrap>
            <LanguageSwitcher />
            <Button onClick={() => navigate(projectId ? `/projects/${projectId}` : "/projects")}>
              {t("analysis.actions.cancel")}
            </Button>
          </Space>
        </Space>
        {!draft || models === null ? (
          <Card>
            <Spin tip={t("analysis.singlePage.loadingTip")} />
          </Card>
        ) : (
          <Card title={t("analysis.singlePage.readyTitle")}>
            {detection && (
              <Alert
                type="info"
                showIcon
                style={{ marginBottom: 16 }}
                message={t("analysis.detection.autoMessage", {
                  reason: detection.reason,
                  confidence: Math.round(detection.confidence * 100),
                })}
              />
            )}
            {survivalBlocked && (
              <Alert
                type="warning"
                showIcon
                style={{ marginBottom: 16 }}
                message={t("analysis.validation.survivalUnavailable")}
                description={t("analysis.validation.survivalGuidance")}
              />
            )}
            {submitBlock && (
              <Alert
                type="error"
                showIcon
                style={{ marginBottom: 16 }}
                message={t("analysis.validation.configurationCannotComplete")}
                description={submitBlock}
              />
            )}
            <Descriptions bordered size="small" column={1}>
              <Descriptions.Item label={t("analysis.fields.dataset")}>{datasetName}</Descriptions.Item>
              <Descriptions.Item label={t("analysis.fields.taskType")}>
                <Select<TaskType>
                  style={{ width: 220 }}
                  value={taskType ?? undefined}
                  options={TASK_TYPES.map((type) => ({
                    value: type,
                    label: taskTypeLabel(type),
                  }))}
                  onChange={onSinglePageTaskChange}
                />
              </Descriptions.Item>
              <Descriptions.Item label={t("analysis.fields.outcomeDefinition")}>
                <Typography.Text code>{JSON.stringify(config?.target ?? {})}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label={t("analysis.fields.preprocessStepsRecommended")}>
                {config?.steps.map((s, i) => <Tag key={i}>{s.type}</Tag>)}
              </Descriptions.Item>
              <Descriptions.Item label={t("analysis.fields.crossValidation")}>
                {config
                  ? t("analysis.fields.crossValidationSummary", {
                      strategy: config.validation.strategy,
                      nSplits: config.validation.n_splits,
                      seed: config.validation.seed,
                    })
                  : t("analysis.notAvailable")}
              </Descriptions.Item>
              <Descriptions.Item label={t("analysis.fields.modelsStandardEditable")}>
                <Checkbox.Group
                  value={selectedModels}
                  onChange={(v) => setSelectedModels(v as string[])}
                >
                  <Space wrap>
                    {models.map((m) => (
                      <Checkbox key={m.key} value={m.key}>
                        {m.name}
                        {m.tier === "standard" && m.role ? (
                          <Tag color="geekblue" style={{ marginLeft: 4 }}>
                            {m.role}
                          </Tag>
                        ) : null}
                      </Checkbox>
                    ))}
                  </Space>
                </Checkbox.Group>
              </Descriptions.Item>
            </Descriptions>
            <Space style={{ marginTop: 24 }}>
              <Button
                type="primary"
                size="large"
                loading={submitting}
                disabled={!!submitBlock || selectedModels.length === 0 || survivalBlocked}
                onClick={() => void submit()}
              >
                {t("analysis.actions.confirmStart")}
              </Button>
              <Button onClick={() => setFullWizard(true)}>{t("analysis.actions.guidedSetup")}</Button>
            </Space>
          </Card>
        )}
      </div>
    );
  }

  // 草稿可用但识别失败：提示后走逐步向导
  if (singlePage && !draftFailed && draft && !draft.task_type) {
    return (
      <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
        <Alert
          type="warning"
          showIcon
          message={t("analysis.singlePage.detectionUnavailableTitle")}
          description={t("analysis.singlePage.detectionUnavailableDescription")}
          action={
            <Button type="primary" onClick={() => setFullWizard(true)}>
              {t("analysis.singlePage.enterGuidedWizard")}
            </Button>
          }
        />
      </div>
    );
  }

  const stepContent = [
    // Step 1 数据集
    <Card key="s1" title={t("analysis.datasetStep.title")}>
      <Select
        style={{ width: 420 }}
        placeholder={t("analysis.datasetStep.placeholder")}
        loading={datasets === null}
        value={datasetId ?? undefined}
        options={(datasets ?? [])
          .filter((d) => d.status === "VALIDATED")
          .map((d) => ({
            value: d.id,
            label: t("analysis.datasetStep.optionLabel", {
              name: d.name,
              rowCount: d.preview?.total_rows ?? t("analysis.datasetStep.unknownRowCount"),
            }),
          }))}
        onChange={(v) => {
          setDatasetId(v);
          setRecommended(null);
          setConfig(null);
          setProfile(null);
          setDetection(null);
          setDetectFailed(null);
          setTaskType(null);
          setModels(null);
          setSelectedModels([]);
          setTemplates(null);
        }}
      />
      {templates && datasetId && (
        <div style={{ marginTop: 16 }}>
          <Typography.Text strong>{t("analysis.templates.title")}</Typography.Text>
          <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
            {templates.map((template) => (
              <Alert
                key={template.key}
                type={template.applicable ? "info" : "warning"}
                showIcon
                message={
                  <Space wrap>
                    <span>{template.name}</span>
                    <Tag color={template.applicable ? "green" : "default"}>
                      {template.applicable ? t("analysis.templates.applicable") : t("analysis.templates.notApplicable")}
                    </Tag>
                    <Tag>{taskTypeLabel(template.task_type)}</Tag>
                    {template.sample_size.map((a, i) => (
                      <Tag key={i} color={a.meets ? "green" : "orange"}>
                        {a.rule}
                        {a.value != null ? t("analysis.templates.currentValue", { value: a.value }) : ""}
                      </Tag>
                    ))}
                  </Space>
                }
                description={
                  <>
                    <div>{template.reasons.join(t("analysis.templates.reasonSeparator"))}</div>
                    {template.sample_size.map((a, i) => (
                      <div key={i} style={{ color: "rgba(0,0,0,0.55)" }}>
                        {a.text}
                      </div>
                    ))}
                  </>
                }
                action={
                  template.applicable ? (
                    <Button size="small" type="primary" onClick={() => applyTemplate(template)}>
                      {t("analysis.actions.useTemplate")}
                    </Button>
                  ) : undefined
                }
              />
            ))}
          </Space>
        </div>
      )}
      {datasets !== null && !datasets.some((d) => d.status === "VALIDATED") && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 16 }}
          message={t("analysis.datasetStep.noValidated")}
        />
      )}
    </Card>,
    // Step 2 预处理
    datasetId ? (
      <PreprocessPanel
        key={`s2-${datasetId}`}
        datasetId={datasetId}
        columns={columns}
        initialConfig={recommended}
        onChange={setConfig}
      />
    ) : (
      <Spin key="s2" />
    ),
    // Step 3 任务类型
    <Card key="s3" title={t("analysis.detection.title")}>
      {detectFailed && (
        <Alert
          type="warning"
          showIcon
          message={t("analysis.detection.failedTitle")}
          description={detectFailed}
          style={{ marginBottom: 12 }}
        />
      )}
      {!detection && !detectFailed && <Spin tip={t("analysis.detection.loading")} />}
      {detection && (
        <Space direction="vertical" style={{ width: "100%", marginBottom: 16 }}>
          <Space size="large">
            <Statistic
              title={t("analysis.detection.recommendedTask")}
              value={
                detection.recommended_task
                  ? taskTypeLabel(detection.recommended_task)
                  : t("analysis.notAvailable")
              }
            />
            <Statistic
              title={t("analysis.detection.confidence")}
              value={t("analysis.detection.confidenceValue", {
                confidence: Math.round(detection.confidence * 100),
              })}
            />
          </Space>
          <Typography.Paragraph style={{ marginBottom: 4 }}>
            <Typography.Text strong>{t("analysis.detection.reasonLabel")}</Typography.Text>{" "}
            {detection.reason}
          </Typography.Paragraph>
          <Space wrap>
            {Object.entries(detection.candidates).map(([kind, cands]) =>
              (cands ?? []).slice(0, 3).map((c) => (
                <Tag key={`${kind}-${c.column}`}>
                  {t("analysis.detection.candidateTag", {
                    kind: candidateKindLabel(kind),
                    column: c.column,
                    confidence: Math.round(c.confidence * 100),
                  })}
                </Tag>
              )),
            )}
          </Space>
        </Space>
      )}
      {survivalBlocked && (
        <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message={t("analysis.validation.survivalUnavailable")}
          description={t("analysis.validation.survivalGuidance")}
        />
      )}
      <Space>
        <span>
          {detection
            ? t("analysis.detection.taskSelectionOverrideRecommended")
            : t("analysis.detection.taskSelectionManual")}
        </span>
        <Select<TaskType>
          style={{ width: 200 }}
          placeholder={t("analysis.detection.selectPlaceholder")}
          value={taskType ?? undefined}
          options={TASK_TYPES.map((type) => ({
            value: type,
            label: taskTypeLabel(type),
          }))}
          onChange={(v) => {
            setTaskType(v);
            // 验证策略与任务一致性（docs/06 §2）：回归无类别可分层，切换时同步替换
            if (v === "regression" && config?.validation.strategy === "stratified_kfold") {
              setConfig({
                ...config,
                validation: { ...config.validation, strategy: "kfold" },
              });
            }
          }}
        />
      </Space>
    </Card>,
    // Step 4 模型（T6.12 分层：标准套餐默认勾选，其余折叠为高级选项）
    <Card
      key="s4"
      title={t("analysis.modelsStep.title", { taskType: taskType ? taskTypeLabel(taskType) : "" })}
    >
      {models === null ? (
        <Spin />
      ) : (
        <Checkbox.Group
          style={{ width: "100%" }}
          value={selectedModels}
          onChange={(v) => setSelectedModels(v as string[])}
        >
          {(() => {
            const standard = models.filter((m) => m.tier === "standard");
            const advanced = models.filter((m) => m.tier !== "standard");
            const columns = (withRole: boolean) =>
              [
                {
                  title: t("analysis.modelsStep.columns.select"),
                  width: 60,
                  render: (_: unknown, m: ModelPlugin) => <Checkbox value={m.key} />,
                },
                { title: t("analysis.modelsStep.columns.model"), dataIndex: "name" },
                ...(withRole
                  ? [
                      {
                        title: t("analysis.modelsStep.columns.role"),
                        width: 150,
                        render: (_: unknown, m: ModelPlugin) =>
                          m.role ? <Tag color="geekblue">{m.role}</Tag> : t("analysis.notAvailable"),
                      },
                    ]
                  : []),
                { title: t("analysis.modelsStep.columns.key"), dataIndex: "key" },
                { title: t("analysis.modelsStep.columns.version"), dataIndex: "version", width: 100 },
              ] as const;
            return (
              <>
                <Typography.Text strong>
                  {t("analysis.modelsStep.standardHeading", { count: standard.length })}
                </Typography.Text>
                <Table<ModelPlugin>
                  rowKey="key"
                  size="small"
                  style={{ margin: "8px 0 16px" }}
                  dataSource={standard}
                  pagination={false}
                  columns={columns(true) as never}
                />
                {advanced.length > 0 && (
                  <Collapse
                    items={[
                      {
                        key: "advanced",
                        label: t("analysis.modelsStep.advancedHeading", { count: advanced.length }),
                        children: (
                          <Table<ModelPlugin>
                            rowKey="key"
                            size="small"
                            dataSource={advanced}
                            pagination={false}
                            columns={columns(false) as never}
                          />
                        ),
                      },
                    ]}
                  />
                )}
              </>
            );
          })()}
        </Checkbox.Group>
      )}
    </Card>,
    // Step 5 确认
    <Card key="s5" title={t("analysis.summary.title")}>
      {submitBlock && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("analysis.validation.configurationCannotComplete")}
          description={submitBlock}
        />
      )}
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label={t("analysis.fields.dataset")}>{datasetName}</Descriptions.Item>
        <Descriptions.Item label={t("analysis.fields.taskType")}>
          {taskType ? taskTypeLabel(taskType) : t("analysis.notAvailable")}
        </Descriptions.Item>
        <Descriptions.Item label={t("analysis.fields.outcomeDefinition")}>
          <Typography.Text code>{JSON.stringify(config?.target ?? {})}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label={t("analysis.fields.preprocessSteps")}>
          {config?.steps.map((s, i) => <Tag key={i}>{s.type}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label={t("analysis.fields.crossValidation")}>
          {config
            ? t("analysis.fields.crossValidationSummary", {
                strategy: config.validation.strategy,
                nSplits: config.validation.n_splits,
                seed: config.validation.seed,
              })
            : t("analysis.notAvailable")}
        </Descriptions.Item>
        <Descriptions.Item label={t("analysis.fields.models")}>
          {selectedModels.map((k) => (
            <Tag key={k} color="geekblue">
              {k}
            </Tag>
          ))}
        </Descriptions.Item>
      </Descriptions>
    </Card>,
  ];

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("analysis.wizard.title")}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          <Button onClick={() => navigate(projectId ? `/projects/${projectId}` : "/projects")}>
            {t("analysis.actions.cancel")}
          </Button>
        </Space>
      </Space>
      <Steps
        current={step}
        items={STEP_KEYS.map((key) => ({ title: t(`analysis.steps.${key}`) }))}
        size="small"
      />
      {iterateSuggestion && (
        <Alert
          type="info"
          showIcon
          style={{ marginTop: 16 }}
          message={t("analysis.iteration.prefilledTitle")}
          description={t("analysis.iteration.prefilledDescription", {
            summary: iterateSuggestion.summary,
          })}
        />
      )}
      <div style={{ margin: "24px 0" }}>{stepContent[step]}</div>
      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        {step > 0 && (
          <Button onClick={() => setStep((s) => s - 1)}>{t("analysis.actions.previous")}</Button>
        )}
        {step < STEP_KEYS.length - 1 && (
          <Button type="primary" disabled={!canNext} onClick={next}>
            {t("analysis.actions.next")}
          </Button>
        )}
        {step === STEP_KEYS.length - 1 && (
          <Button
            type="primary"
            loading={submitting}
            disabled={!!submitBlock}
            onClick={() => void submit()}
          >
            {t("analysis.actions.submitAnalysis")}
          </Button>
        )}
      </Space>
    </div>
  );
}
