/** 分析向导 5 步页（docs/11 §2.2；docs/18 T8.2；验收 G1：≤6 点击到报告）。
 *
 * 默认值策略（ blueprint §2.2 ）：
 * 1 数据集 — 支持 ?dataset= 预选（数据集页「开始分析」直达）；
 * 2 预处理 — 进入即自动「推荐配置」填充，可改可校验；
 * 3 任务类型 — 进入即自动识别，推荐项默认选中，可覆盖；确认后按候选列回填 target；
 * 4 模型 — 按任务类型过滤（GET /models），默认全选；
 * 5 确认 — 全参数摘要 → 提交（POST /analysis-runs）→ 跳运行监控。
 */

import {
  Alert,
  Button,
  Card,
  Checkbox,
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
  listDatasetVersions,
  listDatasets,
  listModels,
  recommendPreprocess,
  type ApiError,
  type DatasetDetail,
  type ModelPlugin,
  type PreprocessConfig,
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
  // Step 2
  const [columns, setColumns] = useState<string[]>([]);
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

  // 进入 Step 2：取列名 + 自动推荐配置（默认值策略：推荐配置已填充）
  useEffect(() => {
    if (step !== 1 || !datasetId || recommended) return;
    getDataset(datasetId)
      .then((ds) => setColumns(ds.preview?.columns ?? []))
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

  // 进入 Step 4：按任务类型拉取可用模型，默认全选
  useEffect(() => {
    if (step !== 3 || !taskType) return;
    listModels(taskType)
      .then((items) => {
        setModels(items);
        setSelectedModels((prev) => {
          const valid = prev.filter((k) => items.some((m) => m.key === k));
          return valid.length > 0 ? valid : items.map((m) => m.key);
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

  const canNext = useMemo(() => {
    switch (step) {
      case 0:
        return datasetId != null;
      case 1:
        return config != null;
      case 2:
        return taskType != null;
      case 3:
        return selectedModels.length > 0;
      default:
        return true;
    }
  }, [step, datasetId, config, taskType, selectedModels]);

  const next = () => {
    if (step === 2) applyDetectionToConfig();
    setStep((s) => s + 1);
  };

  const submit = async () => {
    if (!datasetId || !config || !taskType || selectedModels.length === 0) return;
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
          setDetection(null);
          setDetectFailed(null);
          setTaskType(null);
          setModels(null);
          setSelectedModels([]);
        }}
      />
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
          onChange={(v) => setTaskType(v)}
        />
      </Space>
    </Card>,
    // Step 4 模型
    <Card key="s4" title={`可用模型（${taskType ? TASK_LABEL[taskType] : ""}）`}>
      {models === null ? (
        <Spin />
      ) : (
        <Checkbox.Group
          style={{ width: "100%" }}
          value={selectedModels}
          onChange={(v) => setSelectedModels(v as string[])}
        >
          <Table<ModelPlugin>
            rowKey="key"
            size="small"
            dataSource={models}
            pagination={false}
            columns={[
              {
                title: "选择",
                width: 60,
                render: (_, m) => <Checkbox value={m.key} />,
              },
              { title: "模型", dataIndex: "name" },
              { title: "标识", dataIndex: "key" },
              { title: "版本", dataIndex: "version", width: 100 },
            ]}
          />
        </Checkbox.Group>
      )}
    </Card>,
    // Step 5 确认
    <Card key="s5" title="参数摘要">
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
          <Button type="primary" loading={submitting} onClick={() => void submit()}>
            提交分析
          </Button>
        )}
      </Space>
    </div>
  );
}
