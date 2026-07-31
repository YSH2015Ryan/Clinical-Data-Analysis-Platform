/** RunProgressBoard（docs/11 §2.3/§3）：总进度条 + 每模型状态芯片（失败原因 tooltip）。 */

import { Progress, Space, Tag, Tooltip } from "antd";
import type { ModelTaskStatus, RunProgress, RunStatus } from "../api";

const RUN_STATUS_TEXT: Record<RunStatus, string> = {
  PENDING: "排队中",
  PREPROCESSING: "预处理",
  MODELING: "建模中",
  COMPARING: "模型比较",
  COMPLETED: "已完成",
  FAILED: "失败",
  CANCELED: "已取消",
};

const MODEL_STATUS_META: Record<ModelTaskStatus, { color: string; text: string }> = {
  PENDING: { color: "default", text: "排队" },
  RUNNING: { color: "processing", text: "运行中" },
  SUCCESS: { color: "success", text: "成功" },
  FAILED: { color: "error", text: "失败" },
  SKIPPED: { color: "warning", text: "已跳过" },
};

export function RunStatusTag({ status }: { status: RunStatus }) {
  const color =
    status === "COMPLETED"
      ? "success"
      : status === "FAILED"
        ? "error"
        : status === "CANCELED"
          ? "warning"
          : "processing";
  return <Tag color={color}>{RUN_STATUS_TEXT[status]}</Tag>;
}

export default function RunProgressBoard({ progress }: { progress: RunProgress }) {
  const failed = progress.status === "FAILED";
  return (
    <div>
      <Progress
        percent={progress.percent}
        status={failed ? "exception" : progress.percent === 100 ? "success" : "active"}
      />
      <Space wrap size={[8, 8]}>
        {Object.entries(progress.models).map(([key, status]) => {
          const meta = MODEL_STATUS_META[status];
          const error = progress.errors[key];
          const tag = <Tag color={meta.color}>{`${key}：${meta.text}`}</Tag>;
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
        <div style={{ marginTop: 8, color: "#888" }}>当前步骤：{progress.current_step}</div>
      )}
    </div>
  );
}
