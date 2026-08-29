/** 单因素筛选 + 亚组分析卡片（T6.10；数据集详情页「科研助手」）。
 *
 * 单因素筛选：选择任务类型与结局列 → 逐特征关联检验表（按 p 升序，入选标绿），
 * 入选特征供多因素建模参考；亚组分析：选择暴露与亚组变量 → 分层效应（OR/HR/β
 * + 95%CI）+ 交互作用 p。所有数值由后端真实计算。
 */

import { Button, Card, Form, InputNumber, Select, Space, Table, Tag, Typography, message } from "antd";
import { useState } from "react";
import {
  subgroupAnalysis,
  univariateScreen,
  type ApiError,
  type SubgroupAnalysisResult,
  type TaskType,
  type UnivariateScreenResult,
} from "../api";

const TASK_LABEL: Record<TaskType, string> = {
  survival: "生存分析",
  classification: "分类",
  regression: "回归",
};

export default function ScreeningCard({
  datasetId,
  columns,
}: {
  datasetId: string;
  columns: string[];
}) {
  const [screenForm] = Form.useForm();
  const [subgroupForm] = Form.useForm();
  const [screening, setScreening] = useState(false);
  const [screenResult, setScreenResult] = useState<UnivariateScreenResult | null>(null);
  const [subgrouping, setSubgrouping] = useState(false);
  const [subgroupResult, setSubgroupResult] = useState<SubgroupAnalysisResult | null>(null);

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
        <Button type="primary" loading={screening} onClick={() => void runScreen()}>
          开始筛选
        </Button>
      </Form>
      {screenResult && (
        <>
          <Typography.Paragraph type="secondary">
            入选特征（p &lt; {screenResult.alpha}）：
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
                title: "p 值",
                dataIndex: "p_value",
                render: (v: number) => (v < 0.001 ? "<0.001" : v.toFixed(4)),
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
        <Button type="primary" loading={subgrouping} onClick={() => void runSubgroup()}>
          开始分析
        </Button>
      </Form>
      {subgroupResult &&
        subgroupResult.subgroups.map((sub) => (
          <div key={sub.variable} style={{ marginBottom: 16 }}>
            <Typography.Text strong>
              {sub.variable} 亚组
              {sub.interaction_p != null &&
                `（交互 p = ${
                  sub.interaction_p < 0.001 ? "<0.001" : sub.interaction_p.toFixed(4)
                }${sub.interaction_p < 0.05 ? "，存在效应修饰" : "，未见显著效应修饰"}）`}
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
    </Card>
  );
}
