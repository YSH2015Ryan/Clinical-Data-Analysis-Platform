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
import { useNavigate, useParams } from "react-router-dom";
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

const STEP_TITLES = ["选择数据表", "结局与取值决策", "确认并提交", "准备结果"];

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

/** summary 键 → 中文说明（与 engines/preparation.py 输出一一对应）。 */
const SUMMARY_LABEL: Record<string, string> = {
  lab_rows_in: "化验原始行数",
  diag_rows_in: "诊断原始行数",
  patients: "纳入患者数",
  label_positive: "结局阳性患者数",
  susceptibility_removed: "剔除药敏行",
  lab_rows_value_ok: "有效取值行",
  lab_rows_bad_date_dropped: "化验日期缺失剔除行",
  clipped_rows: "极端值截断行",
  features: "保留检验项目数",
  leakage_removed: "防泄漏剔除（诊断后化验）",
  outside_window_removed: "时间窗外剔除行",
  wide_rows: "宽表行数",
  wide_cols: "宽表列数",
};

export default function PreparationWizardPage() {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();

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
      .catch((e) => message.error((e as ApiError).message || "数据集加载失败"));
  }, [projectId]);

  // 进入 Step 2：自动扫描预览，并用建议默认值回填决策
  useEffect(() => {
    if (step !== 1 || !labId || !diagId || preview || previewError) return;
    preparationPreview(labId, diagId)
      .then((prev) => {
        setPreview(prev);
        setDecisions((d) => ({ ...d, ...prev.suggested, outcome_terms: d.outcome_terms }));
      })
      .catch((e) => setPreviewError((e as ApiError).message || "扫描失败"));
  }, [step, labId, diagId, preview, previewError]);

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
    label: `${d.name}（${d.preview?.total_rows ?? "?"} 行）`,
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
      message.error((e as ApiError).message || "提交失败");
    } finally {
      setSubmitting(false);
    }
  };

  const set = <K extends keyof PreparationDecisions>(key: K, value: PreparationDecisions[K]) =>
    setDecisions((d) => ({ ...d, [key]: value }));

  const nameOf = (id: string | null) => datasets?.find((d) => d.id === id)?.name ?? "—";

  const stepContent = [
    // Step 1 选表
    <Card key="s1" title="选择要组装的两张表">
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        <div>
          <Typography.Text strong>化验表（长表：一行一条化验）</Typography.Text>
          <Select
            style={{ width: "100%", marginTop: 8 }}
            placeholder="如：化验.csv"
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
          <Typography.Text strong>诊断表（含诊断/诊断日期/年龄/性别）</Typography.Text>
          <Select
            style={{ width: "100%", marginTop: 8 }}
            placeholder="如：诊断.csv"
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
            message="项目内可用数据集不足两张，请先上传化验表与诊断表"
          />
        )}
      </Space>
    </Card>,
    // Step 2 决策
    <Card key="s2" title="扫描结果与决策（机器已填好默认值，按需调整）">
      {!preview && !previewError && <Spin tip="正在扫描两张表…" />}
      {previewError && <Alert type="error" showIcon message="扫描失败" description={previewError} />}
      {preview && (
        <Space direction="vertical" size="large" style={{ width: "100%" }}>
          <Space size="large" wrap>
            <Statistic title="患者交集" value={preview.patients_intersection} />
            <Statistic title="化验行数" value={preview.lab_rows} />
            <Statistic title="诊断行数" value={preview.diag_rows} />
            <Statistic title="疑似药敏行（将剔除）" value={preview.susceptibility_rows} />
          </Space>
          <div>
            <Typography.Title level={5}>
              ① 结局定义：勾选要研究的诊断词条（任一命中即记为阳性）
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
                  { title: "选择", width: 60, render: (_, t) => <Checkbox value={t.term} /> },
                  { title: "诊断词条", dataIndex: "term" },
                  { title: "出现次数", dataIndex: "count", width: 100 },
                ]}
              />
            </Checkbox.Group>
          </div>
          <Form layout="vertical">
            <Form.Item label="② 结局判定范围">
              <Radio.Group
                value={decisions.outcome_scope}
                onChange={(e) => set("outcome_scope", e.target.value)}
                options={[
                  { value: "any", label: "任一诊断记录命中即阳性" },
                  { value: "index", label: "仅索引诊断命中才阳性" },
                ]}
              />
            </Form.Item>
            <Form.Item label="③ 索引诊断（化验时间的锚点，防泄漏：只保留它之前的化验）">
              <Radio.Group
                value={decisions.index_diagnosis}
                onChange={(e) => set("index_diagnosis", e.target.value)}
                options={[
                  { value: "first", label: "首次诊断" },
                  { value: "last", label: "末次诊断" },
                ]}
              />
            </Form.Item>
            <Space size="large" wrap>
              <Form.Item label="④ 诊断前时间窗（天，0=不限）">
                <InputNumber
                  min={0}
                  value={decisions.window_days}
                  onChange={(v) => set("window_days", v ?? 0)}
                />
              </Form.Item>
              <Form.Item label="⑤ 同一项目多次化验取值">
                <Radio.Group
                  value={decisions.value_strategy}
                  onChange={(e) => set("value_strategy", e.target.value)}
                  options={[
                    { value: "latest", label: "最近一次" },
                    { value: "mean", label: "均值" },
                  ]}
                />
              </Form.Item>
              <Form.Item label="取值列">
                <Select
                  style={{ width: 160 }}
                  value={decisions.value_column}
                  options={[preview.lab_columns.value, "归一化值", "结果"]
                    .filter((c): c is string => c != null)
                    .filter((c, i, arr) => arr.indexOf(c) === i)
                    .map((c) => ({ value: c, label: c }))}
                  onChange={(v) => set("value_column", v)}
                />
              </Form.Item>
              <Form.Item label="剔除药敏记录">
                <Switch
                  checked={decisions.exclude_susceptibility}
                  onChange={(v) => set("exclude_susceptibility", v)}
                />
              </Form.Item>
              <Form.Item label="极端值截断分位（0=不截断）">
                <InputNumber
                  min={0}
                  max={0.999}
                  step={0.01}
                  value={decisions.clip_quantile}
                  onChange={(v) => set("clip_quantile", v ?? 0)}
                />
              </Form.Item>
              <Form.Item label="最多保留检验项目数">
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
    <Card key="s3" title="参数摘要">
      <Descriptions bordered size="small" column={1}>
        <Descriptions.Item label="化验表">{nameOf(labId)}</Descriptions.Item>
        <Descriptions.Item label="诊断表">{nameOf(diagId)}</Descriptions.Item>
        <Descriptions.Item label="结局词条">
          {decisions.outcome_terms.map((t) => (
            <Tag key={t} color="red">
              {t}
            </Tag>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label="判定范围">
          {decisions.outcome_scope === "any" ? "任一诊断记录" : "仅索引诊断"}
        </Descriptions.Item>
        <Descriptions.Item label="索引诊断">
          {decisions.index_diagnosis === "first" ? "首次" : "末次"}
        </Descriptions.Item>
        <Descriptions.Item label="时间窗">
          {decisions.window_days === 0 ? "不限" : `诊断前 ${decisions.window_days} 天`}
        </Descriptions.Item>
        <Descriptions.Item label="取值策略">
          {decisions.value_strategy === "latest" ? "最近一次" : "均值"}（{decisions.value_column}）
        </Descriptions.Item>
        <Descriptions.Item label="清洗">
          {decisions.exclude_susceptibility ? "剔除药敏；" : ""}
          {decisions.clip_quantile > 0 ? `按 ${decisions.clip_quantile} 分位截断极端值；` : ""}
          最多 {decisions.top_n_items} 个检验项目
        </Descriptions.Item>
      </Descriptions>
    </Card>,
    // Step 4 结果
    <Card key="s4">
      {!job || (job.status !== "COMPLETED" && job.status !== "FAILED") ? (
        <Result icon={<Spin size="large" />} title="正在生成宽表…" subTitle="大表可能需要几十秒" />
      ) : job.status === "FAILED" ? (
        <Result status="error" title="数据准备失败" subTitle={job.error ?? "未知错误"} />
      ) : (
        <Result
          status="success"
          title="宽表已生成，可直接进入分析"
          subTitle={
            <Space size="large" wrap style={{ justifyContent: "center", marginTop: 8 }}>
              <Statistic title="患者数" value={job.summary?.patients ?? 0} />
              <Statistic title="结局阳性" value={job.summary?.label_positive ?? 0} />
              <Statistic title="检验项目" value={job.summary?.features ?? 0} />
              <Statistic title="防泄漏剔除行" value={job.summary?.leakage_removed ?? 0} />
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
              用这张宽表新建分析
            </Button>,
            <Button key="dataset" onClick={() => navigate(`/datasets/${job.result_dataset_id}`)}>
              查看宽表数据集
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
              title: "审计项",
              dataIndex: "name",
              render: (k: string) => SUMMARY_LABEL[k] ?? k,
            },
            { title: "数值", dataIndex: "value", width: 140 },
          ]}
        />
      )}
    </Card>,
  ];

  return (
    <div style={{ maxWidth: 1080, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          数据准备（化验 + 诊断 → 分析宽表）
        </Typography.Title>
        <Button onClick={() => navigate(projectId ? `/projects/${projectId}` : "/projects")}>
          取消
        </Button>
      </Space>
      <Steps current={step} items={STEP_TITLES.map((title) => ({ title }))} size="small" />
      <div style={{ margin: "24px 0" }}>{stepContent[step]}</div>
      <Space style={{ width: "100%", justifyContent: "flex-end" }}>
        {step > 0 && step < 3 && <Button onClick={() => setStep((s) => s - 1)}>上一步</Button>}
        {step < STEP_TITLES.length - 2 && (
          <Button type="primary" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>
            下一步
          </Button>
        )}
        {step === STEP_TITLES.length - 2 && (
          <Button type="primary" loading={submitting} onClick={() => void submit()}>
            提交并生成宽表
          </Button>
        )}
      </Space>
    </div>
  );
}
