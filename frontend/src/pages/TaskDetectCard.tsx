/** 任务识别确认卡片（docs/08 §1.2「自动推荐、人工兜底」、docs/18 T4.2）。

 * 展示推荐任务类型 + 置信度 + 推荐理由（为什么推荐）；
 * 用户可一键确认或下拉覆盖——覆盖结果随 run 快照保存（E5 创建分析运行时消费）。
 * 识别失败（422）回退手动选择。
 */

import { Alert, Button, Card, Select, Space, Statistic, Tag, Typography, message } from "antd";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  detectTask,
  type ApiError,
  type TaskDetectionResult,
  type TaskType,
} from "../api";

const TASK_TYPES: TaskType[] = ["survival", "classification", "regression"];

interface Props {
  datasetId: string;
  onConfirm?: (taskType: TaskType, detection: TaskDetectionResult | null) => void;
}

export default function TaskDetectCard({ datasetId, onConfirm }: Props) {
  const { t } = useTranslation();
  const taskTypeLabel = useCallback((value: TaskType) => t(`analysis.taskTypes.${value}`), [t]);
  const candidateKindLabel = useCallback(
    (kind: string) => {
      if (kind === "time_col" || kind === "event_col" || kind === "label_col") {
        return t(`analysis.detection.candidateKinds.${kind}`);
      }
      return kind;
    },
    [t],
  );
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
        message.error(err.message || t("analysis.errors.detectTask"));
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card
      title={t("analysis.detection.title")}
      style={{ marginBottom: 16 }}
      extra={
        <Space>
          <Button onClick={() => void onDetect()} loading={busy}>
            {detection || failed ? t("analysis.actions.redetectTask") : t("analysis.actions.detectTask")}
          </Button>
          <Button
            type="primary"
            disabled={selected == null}
            onClick={() => selected && onConfirm?.(selected, detection)}
          >
            {t("analysis.actions.confirmTask")}
          </Button>
        </Space>
      }
    >
      {failed && (
        <Alert
          type="warning"
          showIcon
          message={t("analysis.detection.failedTitle")}
          description={failed}
          style={{ marginBottom: 12 }}
        />
      )}
      {detection && (
        <Space direction="vertical" style={{ width: "100%", marginBottom: 12 }}>
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
      <Space>
        <span>
          {detection
            ? t("analysis.detection.taskSelectionOverrideRecommended")
            : t("analysis.detection.taskSelectionManual")}
        </span>
        <Select<TaskType>
          style={{ width: 200 }}
          placeholder={t("analysis.detection.selectPlaceholder")}
          value={selected ?? undefined}
          options={TASK_TYPES.map((type) => ({
            value: type,
            label: taskTypeLabel(type),
          }))}
          onChange={(v) => setSelected(v)}
        />
      </Space>
    </Card>
  );
}
