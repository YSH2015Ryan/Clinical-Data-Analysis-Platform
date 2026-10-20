/** RunProgressBoard（docs/11 §2.3/§3）：总进度条 + 每模型状态芯片（失败原因 tooltip）。 */

import { Progress, Space, Tag, Tooltip } from "antd";
import { useTranslation } from "react-i18next";
import type { ModelTaskStatus, RunProgress, RunStatus } from "../api";

const MODEL_STATUS_COLOR: Record<ModelTaskStatus, string> = {
  PENDING: "default",
  RUNNING: "processing",
  SUCCESS: "success",
  FAILED: "error",
  SKIPPED: "warning",
};

export function RunStatusTag({ status }: { status: RunStatus }) {
  const { t } = useTranslation();
  const color =
    status === "COMPLETED"
      ? "success"
      : status === "FAILED"
        ? "error"
        : status === "CANCELED"
          ? "warning"
          : "processing";
  return <Tag color={color}>{t(`run.status.${status}`)}</Tag>;
}

export default function RunProgressBoard({ progress }: { progress: RunProgress }) {
  const { t } = useTranslation();
  const failed = progress.status === "FAILED";
  return (
    <div>
      <Progress
        percent={progress.percent}
        status={failed ? "exception" : progress.percent === 100 ? "success" : "active"}
      />
      <Space wrap size={[8, 8]}>
        {Object.entries(progress.models).map(([key, status]) => {
          const error = progress.errors[key];
          const tag = <Tag color={MODEL_STATUS_COLOR[status]}>{`${key}: ${t(`run.modelStatus.${status}`)}`}</Tag>;
          // 失败原因 tooltip（docs/11 §2.3）
          return status === "FAILED" && error ? (
            <Tooltip key={key} title={error}>
              {tag}
            </Tooltip>
          ) : (
            <span key={key}>{tag}</span>
          );
        })}
      </Space>
      {progress.current_step && (
        <div style={{ marginTop: 8, color: "#888" }}>
          {t("run.currentStep", { step: progress.current_step })}
        </div>
      )}
    </div>
  );
}
