/** 运行监控页 /runs/:id（docs/11 §2.3）：2s 轮询进度、取消、失败模型重跑。 */

import { Alert, Button, Card, Popconfirm, Space, Typography, message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  cancelRun,
  getRun,
  getRunProgress,
  rerunModel,
  type AnalysisRunDetail,
  type ApiError,
  type RunProgress,
} from "../api";
import RunProgressBoard, { RunStatusTag } from "../components/RunProgressBoard";

const TERMINAL: RunProgress["status"][] = ["COMPLETED", "FAILED", "CANCELED"];
const POLL_MS = 2000;

export default function RunMonitorPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<AnalysisRunDetail | null>(null);
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [acting, setActing] = useState(false);
  const timer = useRef<number | null>(null);
  const navigate = useNavigate();

  const tick = useCallback(async () => {
    if (!id) return;
    try {
      const p = await getRunProgress(id);
      setProgress(p);
      if (TERMINAL.includes(p.status)) {
        if (timer.current) window.clearInterval(timer.current);
        timer.current = null;
        setRun(await getRun(id));
      }
    } catch (e) {
      if (timer.current) window.clearInterval(timer.current);
      timer.current = null;
      message.error((e as ApiError).message || "进度加载失败");
    }
  }, [id]);

  useEffect(() => {
    void getRun(id!).then(setRun).catch(() => undefined);
    void tick();
    timer.current = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, [id, tick]);

  const onCancel = async () => {
    if (!id) return;
    setActing(true);
    try {
      await cancelRun(id);
      message.success("已取消");
      await tick();
    } catch (e) {
      message.error((e as ApiError).message || "取消失败");
    } finally {
      setActing(false);
    }
  };

  const onRerun = async (modelKey: string) => {
    if (!id) return;
    setActing(true);
    try {
      await rerunModel(id, modelKey);
      message.success(`已重新入队：${modelKey}`);
      await tick();
      if (!timer.current) timer.current = window.setInterval(() => void tick(), POLL_MS);
    } catch (e) {
      message.error((e as ApiError).message || "重跑失败");
    } finally {
      setActing(false);
    }
  };

  const cancellable = progress && !TERMINAL.includes(progress.status);
  const failedModels = progress
    ? Object.entries(progress.models)
        .filter(([, s]) => s === "FAILED")
        .map(([k]) => k)
    : [];

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          运行监控 {run && <RunStatusTag status={run.status} />}
        </Typography.Title>
        <Space>
          {progress?.status === "COMPLETED" && (
            <Button type="primary" onClick={() => navigate(`/runs/${id}/comparison`)}>
              查看比较结果
            </Button>
          )}
          {cancellable && (
            <Popconfirm title="确认取消该运行？" onConfirm={() => void onCancel()}>
              <Button danger loading={acting}>
                取消运行
              </Button>
            </Popconfirm>
          )}
          <Button onClick={() => navigate(-1)}>返回</Button>
          <Button onClick={() => navigate("/projects")}>返回主页</Button>
        </Space>
      </Space>

      {run?.error && (
        <Alert
          type="error"
          message="运行失败"
          style={{ marginBottom: 16 }}
          description={
            <div>
              <div>{run.error}</div>
              {progress && Object.keys(progress.errors).length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {Object.entries(progress.errors).map(([key, err]) => (
                    <li key={key}>
                      <strong>{key}</strong>：{err}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          }
        />
      )}

      <Card>
        {progress ? <RunProgressBoard progress={progress} /> : "加载中…"}
        {failedModels.length > 0 && (
          <Space style={{ marginTop: 16 }} wrap>
            {failedModels.map((key) => (
              <Button key={key} size="small" disabled={acting} onClick={() => void onRerun(key)}>
                重跑 {key}
              </Button>
            ))}
          </Space>
        )}
      </Card>
    </div>
  );
}
