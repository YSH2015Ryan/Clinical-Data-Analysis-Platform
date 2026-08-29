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
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  createRun,
  detectTask,
  getDataset,
  getResearchTemplates,
  listDatasetVersions,
  listDatasets,
  listModels,
  recommendPreprocess,
  type ApiError,
  type ColumnProfile,
  type DatasetDetail,
  type ModelPlugin,
  type PreprocessConfig,
  type ResearchTemplateSuggestion,
  type TaskDetectionResult,
  type TaskType,
} from "../api";
import PreprocessPanel from "./PreprocessPanel";

const TASK_LABEL: Record<TaskType, string> = {
  survival: "生存分析",
  classification: "分类 / 风险预测",
  regression: "回归 / 预后",
};

const STEP_TITLES = ["选择数据集", "预处理配置", "任务类型确认", "选择模型", "确认并提交"];

export default function AnalysisWizardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

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
  const [taskType, setTaskType] = useState<TaskType | null>(null);
  // Step 4
  const [models, setModels] = useState<ModelPlugin[] | null>(null);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  // Step 5
  const [submitting, setSubmitting] = useState(false);

  // Step 1：项目内数据集（仅 VALIDATED 可选）
  useEffect(() => {
    if (!projectId) return;
    listDatasets(projectId)
      .then((page) => setDatasets(page.items))
      .catch((e) => message.error((e as ApiError).message || "数据集加载失败"));
  }, [projectId]);

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
  const applyTemplate = (t: ResearchTemplateSuggestion) => {
    setTaskType(t.task_type);
    setSelectedModels(t.models);
    message.success(`已应用「${t.name}」模板：任务类型与推荐模型已预填，后续步骤可调整`);
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
      .then((cfg) => setRecommended(cfg))
      .catch((e) => message.error((e as ApiError).message || "推荐配置生成失败"));
  }, [step, datasetId, recommended]);

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
        else message.error(err.message || "识别失败");
      });
  }, [step, datasetId, detection, detectFailed]);

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
      .catch((e) => message.error((e as ApiError).message || "模型列表加载失败"));
  }, [step, taskType]);

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
    () =>
      taskType === "survival" &&
      detection != null &&
      !(
        (detection.candidates.time_col?.length ?? 0) > 0 &&
        (detection.candidates.event_col?.length ?? 0) > 0
      ),
    [taskType, detection],
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
    const need =
      taskType === "survival" ? [target.time_col, target.event_col] : [target.label_col];
    const missing = need.filter((c): c is string => !!c && !columns.includes(c));
    if (missing.length > 0) {
      return `结局相关列 ${missing.join("、")} 在数据集中不存在，请返回步骤 2 核对结局定义。`;
    }
    if (!profile || !target.label_col) return null;
    const p = profile.find((c) => c.name === target.label_col);
    if (!p) return null;
    if (taskType === "regression" && ["text", "datetime", "id"].includes(p.inferred_type)) {
      return `回归任务的结局列「${target.label_col}」必须是数值，当前列为${p.inferred_type === "text" ? "文字类别" : p.inferred_type === "datetime" ? "日期" : "标识"}类型。如果研究问题是「是否/属于哪类」的判断，请改用「分类 / 风险预测」。`;
    }
    if (taskType === "classification" && p.unique < 2) {
      return `结局列「${target.label_col}」只有一个有效取值，分类任务需要至少两个类别，请核对结局定义。`;
    }
    return null;
  }, [config, taskType, columns, profile]);

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
    if (!datasetId || !config || !taskType || selectedModels.length === 0 || submitBlock) return;
    setSubmitting(true);
    try {
      const versions = await listDatasetVersions(datasetId);
      const latest = versions[0]; // 服务端按 version_no 降序
      if (!latest) throw new Error("数据集无可用版本");
      const run = await createRun({
        dataset_version_id: latest.id,
        task_type: taskType,
        preprocess_config: config,
        selected_models: selectedModels,
      });
      message.success("分析已提交");
      navigate(`/runs/${run.id}`);
    } catch (e) {
      const err = e as ApiError;
      message.error(err.message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const datasetName = datasets?.find((d) => d.id === datasetId)?.name ?? datasetId ?? "—";

  const stepContent = [
    // Step 1 数据集
    <Card key="s1" title="选择已校验数据集">
      <Select
        style={{ width: 420 }}
        placeholder="选择数据集（仅 VALIDATED 可分析）"
        loading={datasets === null}
        value={datasetId ?? undefined}
        options={(datasets ?? [])
          .filter((d) => d.status === "VALIDATED")
          .map((d) => ({
            value: d.id,
            label: `${d.name}（${d.preview?.total_rows ?? "?"} 行）`,
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
          <Typography.Text strong>科研流程模板（可选）：</Typography.Text>
          <Space direction="vertical" style={{ width: "100%", marginTop: 8 }}>
            {templates.map((t) => (
              <Alert
                key={t.key}
                type={t.applicable ? "info" : "warning"}
                showIcon
                message={
                  <Space wrap>
                    <span>{t.name}</span>
                    <Tag color={t.applicable ? "green" : "default"}>
                      {t.applicable ? "适用" : "不适用"}
                    </Tag>
                    <Tag>{TASK_LABEL[t.task_type]}</Tag>
                    {t.sample_size.map((a, i) => (
                      <Tag key={i} color={a.meets ? "green" : "orange"}>
                        {a.rule}
                        {a.value != null ? `（当前 ${a.value}）` : ""}
                      </Tag>
                    ))}
                  </Space>
                }
                description={
                  <>
                    <div>{t.reasons.join("；")}</div>
                    {t.sample_size.map((a, i) => (
                      <div key={i} style={{ color: "rgba(0,0,0,0.55)" }}>
                        {a.text}
                      </div>
                    ))}
                  </>
                }
                action={
                  t.applicable ? (
                    <Button size="small" type="primary" onClick={() => applyTemplate(t)}>
                      使用此模板
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
          message="项目内暂无已校验数据集，请先上传并通过质量校验"
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
    <Card key="s3" title="任务类型识别">
      {detectFailed && (
        <Alert
          type="warning"
          showIcon
          message="自动识别失败，请手动选择任务类型"
          description={detectFailed}
          style={{ marginBottom: 12 }}
        />
      )}
      {!detection && !detectFailed && <Spin tip="识别中…" />}
      {detection && (
        <Space direction="vertical" style={{ width: "100%", marginBottom: 16 }}>
          <Space size="large">
            <Statistic
              title="推荐任务"
              value={detection.recommended_task ? TASK_LABEL[detection.recommended_task] : "—"}
            />
            <Statistic title="置信度" value={`${Math.round(detection.confidence * 100)}%`} />
          </Space>
          <Typography.Paragraph style={{ marginBottom: 4 }}>
            <Typography.Text strong>推荐理由：</Typography.Text>
            {detection.reason}
          </Typography.Paragraph>
          <Space wrap>
            {Object.entries(detection.candidates).map(([kind, cands]) =>
              (cands ?? []).slice(0, 3).map((c) => (
                <Tag key={`${kind}-${c.column}`}>
                  {kind}: {c.column} ({Math.round(c.confidence * 100)}%)
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
          message="当前数据没有随访时间 / 结局事件列，无法进行生存分析"
          description="生存分析需要每位患者的随访时长（如 os_months）与事件标记（如 death）。数据准备 v1 产出的宽表只含二分类 label，请改用「分类 / 风险预测」。"
        />
      )}
      <Space>
        <span>任务类型{detection ? "（可覆盖推荐）" : "（手动选择）"}</span>
        <Select<TaskType>
          style={{ width: 200 }}
          placeholder="选择任务类型"
          value={taskType ?? undefined}
          options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
            value: t,
            label: TASK_LABEL[t],
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
    <Card key="s4" title={`可用模型（${taskType ? TASK_LABEL[taskType] : ""}）`}>
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
                  title: "选择",
                  width: 60,
                  render: (_: unknown, m: ModelPlugin) => <Checkbox value={m.key} />,
                },
                { title: "模型", dataIndex: "name" },
                ...(withRole
                  ? [
                      {
                        title: "角色",
                        width: 150,
                        render: (_: unknown, m: ModelPlugin) =>
                          m.role ? <Tag color="geekblue">{m.role}</Tag> : "—",
                      },
                    ]
                  : []),
                { title: "标识", dataIndex: "key" },
                { title: "版本", dataIndex: "version", width: 100 },
              ] as const;
            return (
              <>
                <Typography.Text strong>
                  标准套餐（{standard.length} 个，已默认勾选：基线 + 强模型 + 可解释模型）
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
                        label: `高级选项（${advanced.length} 个，按需展开勾选）`,
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
    <Card key="s5" title="参数摘要">
      {submitBlock && (
        <Alert
          type="error"
          showIcon
          style={{ marginBottom: 16 }}
          message="当前配置无法完成分析"
          description={submitBlock}
        />
      )}
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="数据集">{datasetName}</Descriptions.Item>
        <Descriptions.Item label="任务类型">
          {taskType ? TASK_LABEL[taskType] : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="结局定义">
          <Typography.Text code>{JSON.stringify(config?.target ?? {})}</Typography.Text>
        </Descriptions.Item>
        <Descriptions.Item label="预处理步骤">
          {config?.steps.map((s, i) => <Tag key={i}>{s.type}</Tag>)}
        </Descriptions.Item>
        <Descriptions.Item label="交叉验证">
          {config
            ? `${config.validation.strategy} × ${config.validation.n_splits}（seed=${config.validation.seed}）`
            : "—"}
        </Descriptions.Item>
        <Descriptions.Item label="模型">
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
          新建分析
        </Typography.Title>
        <Button onClick={() => navigate(projectId ? `/projects/${projectId}` : "/projects")}>
          取消
        </Button>
      </Space>
      <Steps current={step} items={STEP_TITLES.map((title) => ({ title }))} size="small" />
      <div style={{ margin: "24px 0" }}>{stepContent[step]}</div>
      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        {step > 0 && <Button onClick={() => setStep((s) => s - 1)}>上一步</Button>}
        {step < STEP_TITLES.length - 1 && (
          <Button type="primary" disabled={!canNext} onClick={next}>
            下一步
          </Button>
        )}
        {step === STEP_TITLES.length - 1 && (
          <Button
            type="primary"
            loading={submitting}
            disabled={!!submitBlock}
            onClick={() => void submit()}
          >
            提交分析
          </Button>
        )}
      </Space>
    </div>
  );
}
