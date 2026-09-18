/** 运行监控页 /runs/:id（docs/11 §2.3）：2s 轮询进度、取消、失败模型重跑。 */

import { Alert, Button, Card, Modal, Popconfirm, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  cancelRun,
  confirmExploratory,
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
        // P1-4：运行完成自动进入比较结果页（报告已由后端自动生成）
        if (p.status === "COMPLETED") {
          message.success("分析完成，报告已自动生成");
          navigate(`/runs/${id}/comparison`, { replace: true });
        }
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

  // §72 Critical Issue Gate：门禁拦截的失败运行 → 三选一（查看问题/继续探索性分析/返回数据清洗）
  const gated = run?.status === "FAILED" && (run.error ?? "").includes("完整性门禁");
  const gateFindings = (run?.integrity?.findings ?? []).filter(
    (f) => f.severity === "blocker" || f.severity === "critical",
  );

  const onConfirmExploratory = () => {
    if (!id) return;
    Modal.confirm({
      title: "继续探索性分析？",
      width: 560,
      content: (
        <div>
          <p>检测到重大数据或方法学问题。继续后本次运行将以探索性模式执行，报告强制标记 RED，并声明：</p>
          <p style={{ fontWeight: 600 }}>
            Results should not be interpreted as unbiased predictive performance.
          </p>
          <p>结果仅供方法学筛查参考，不得作为确认性结论。</p>
        </div>
      ),
      okText: "继续探索性分析",
      okButtonProps: { danger: true },
      cancelText: "返回数据清洗",
      onCancel: () => navigate(-1),
      onOk: async () => {
        setActing(true);
        try {
          await confirmExploratory(id);
          message.success("已进入探索性模式，重新入队");
          await tick();
          if (!timer.current) timer.current = window.setInterval(() => void tick(), POLL_MS);
        } catch (e) {
          message.error((e as ApiError).message || "确认失败");
        } finally {
          setActing(false);
        }
      },
    });
  };

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
          message={gated ? "方法学完整性门禁拦截（§72）" : "运行失败"}
          style={{ marginBottom: 16 }}
          description={
            <div>
              <div>{run.error}</div>
              {/* §72：门禁发现逐条列出（查看问题），含修复建议 */}
              {gated && gateFindings.length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {gateFindings.map((f) => (
                    <li key={f.code} style={{ marginBottom: 4 }}>
                      <Tag color={f.severity === "blocker" ? "red" : "volcano"}>
                        {f.severity === "blocker" ? "阻断" : "严重"}
                      </Tag>
                      <strong>{f.code}</strong>：{f.message}
                      {f.recommended_action && (
                        <div style={{ color: "#666" }}>建议：{f.recommended_action}</div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {progress && Object.keys(progress.errors).length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {Object.entries(progress.errors).map(([key, err]) => (
                    <li key={key}>
                      <strong>{key}</strong>：{err}
                    </li>
                  ))}
                </ul>
              )}
              {gated && (
                <Space style={{ marginTop: 12 }}>
                  <Button danger loading={acting} onClick={onConfirmExploratory}>
                    继续探索性分析
                  </Button>
                  <Button onClick={() => navigate(-1)}>返回数据清洗</Button>
                </Space>
              )}
            </div>
          }
        />
      )}

      {/* §72：探索性模式运行中的醒目提示 */}
      {run?.exploratory_mode && run.status !== "FAILED" && (
        <Alert
          type="error"
          style={{ marginBottom: 16 }}
          message="探索性分析模式（§72）"
          description="本次运行是在存在 critical 级方法学问题的情况下经确认继续的探索性分析。Results should not be interpreted as unbiased predictive performance."
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
