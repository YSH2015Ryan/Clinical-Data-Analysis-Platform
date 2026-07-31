/** 任务识别确认卡片（docs/08 §1.2「自动推荐、人工兜底」、docs/18 T4.2）。

 * 展示推荐任务类型 + 置信度 + 推荐理由（为什么推荐）；
 * 用户可一键确认或下拉覆盖——覆盖结果随 run 快照保存（E5 创建分析运行时消费）。
 * 识别失败（422）回退手动选择。
 */

import { Alert, Button, Card, Select, Space, Statistic, Tag, Typography, message } from "antd";
import { useState } from "react";
import {
  detectTask,
  type ApiError,
  type TaskDetectionResult,
  type TaskType,
} from "../api";

const TASK_LABEL: Record<TaskType, string> = {
  survival: "生存分析",
  classification: "分类 / 风险预测",
  regression: "回归 / 预后",
};

interface Props {
  datasetId: string;
  onConfirm?: (taskType: TaskType, detection: TaskDetectionResult | null) => void;
}

export default function TaskDetectCard({ datasetId, onConfirm }: Props) {
  const [detection, setDetection] = useState<TaskDetectionResult | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const [selected, setSelected] = useState<TaskType | null>(null);
  const [busy, setBusy] = useState(false);

  const onDetect = async () => {
    setBusy(true);
    try {
      const result = await detectTask(datasetId);
      setDetection(result);
      setFailed(null);
      setSelected(result.recommended_task);
    } catch (e) {
      const err = e as ApiError;
      if (err.code === "TASK_DETECTION_FAILED") {
        setDetection(null);
        setFailed(err.message);
      } else {
        message.error(err.message || "识别失败");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title="任务类型识别"
      style={{ marginBottom: 16 }}
      extra={
        <Space>
          <Button onClick={() => void onDetect()} loading={busy}>
            {detection || failed ? "重新识别" : "识别任务类型"}
          </Button>
          <Button
            type="primary"
            disabled={selected == null}
            onClick={() => selected && onConfirm?.(selected, detection)}
          >
            确认任务类型
          </Button>
        </Space>
      }
    >
      {failed && (
        <Alert
          type="warning"
          showIcon
          message="自动识别失败，请手动选择任务类型"
          description={failed}
          style={{ marginBottom: 12 }}
        />
      )}
      {detection && (
        <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
          <Space size="large">
            <Statistic
              title="推荐任务"
              value={detection.recommended_task ? TASK_LABEL[detection.recommended_task] : "—"}
            />
            <Statistic
              title="置信度"
              value={`${Math.round(detection.confidence * 100)}%`}
            />
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
          value={selected ?? undefined}
          options={(Object.keys(TASK_LABEL) as TaskType[]).map((t) => ({
            value: t,
            label: TASK_LABEL[t],
          }))}
          onChange={(v) => setSelected(v)}
        />
      </Space>
    </Card>
  );
}
