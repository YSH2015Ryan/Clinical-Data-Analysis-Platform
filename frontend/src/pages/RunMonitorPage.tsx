/** 运行监控页 /runs/:id（docs/11 §2.3）：2s 轮询进度、取消、失败模型重跑。 */

import { Alert, Button, Card, Modal, Popconfirm, Space, Tag, Typography, message } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
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
import LanguageSwitcher from "../components/LanguageSwitcher";
import RunProgressBoard, { RunStatusTag } from "../components/RunProgressBoard";
import { formatNumber } from "../i18n/locale";

const TERMINAL: RunProgress["status"][] = ["COMPLETED", "FAILED", "CANCELED"];
const POLL_MS = 2000;

export default function RunMonitorPage() {
  const { id } = useParams<{ id: string }>();
  const [run, setRun] = useState<AnalysisRunDetail | null>(null);
  const [progress, setProgress] = useState<RunProgress | null>(null);
  const [acting, setActing] = useState(false);
  const [exploratoryOpen, setExploratoryOpen] = useState(false);
  const timer = useRef<number | null>(null);
  const navigate = useNavigate();
  const { i18n, t } = useTranslation();

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
          message.success(t("run.monitor.completed"));
          navigate(`/runs/${id}/comparison`, { replace: true });
        }
      }
    } catch (e) {
      if (timer.current) window.clearInterval(timer.current);
      timer.current = null;
      message.error((e as ApiError).message || t("run.monitor.progressFailed"));
    }
  }, [id, navigate, t]);

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
      message.success(t("run.monitor.canceled"));
      await tick();
    } catch (e) {
      message.error((e as ApiError).message || t("run.monitor.cancelFailed"));
    } finally {
      setActing(false);
    }
  };

  const onRerun = async (modelKey: string) => {
    if (!id) return;
    setActing(true);
    try {
      await rerunModel(id, modelKey);
      message.success(t("run.monitor.rerunQueued", { model: modelKey }));
      await tick();
      if (!timer.current) timer.current = window.setInterval(() => void tick(), POLL_MS);
    } catch (e) {
      message.error((e as ApiError).message || t("run.monitor.rerunFailed"));
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

  // §72 Critical Issue Gate：T9.4 前继续兼容旧后端中文控制流，后续改稳定 code。
  const gated = run?.status === "FAILED" && (run.error ?? "").includes("完整性门禁");
  const gateFindings = (run?.integrity?.findings ?? []).filter(
    (f) => f.severity === "blocker" || f.severity === "critical",
  );

  const onConfirmExploratory = async () => {
    if (!id) return;
    setActing(true);
    try {
      await confirmExploratory(id);
      message.success(t("run.monitor.confirmExploratory"));
      setExploratoryOpen(false);
      await tick();
      if (!timer.current) timer.current = window.setInterval(() => void tick(), POLL_MS);
    } catch (e) {
      message.error((e as ApiError).message || t("run.monitor.confirmFailed"));
    } finally {
      setActing(false);
    }
  };

  return (
    <div style={{ maxWidth: 960, margin: "24px auto", padding: "0 16px" }}>
      <Space wrap style={{ width: "100%", justifyContent: "space-between", marginBottom: 16 }}>
        <Typography.Title level={3} style={{ margin: 0 }}>
          {t("run.monitor.title")} {run && <RunStatusTag status={run.status} />}
        </Typography.Title>
        <Space wrap>
          <LanguageSwitcher />
          {progress?.status === "COMPLETED" && (
            <Button type="primary" onClick={() => navigate(`/runs/${id}/comparison`)}>
              {t("run.monitor.viewResults")}
            </Button>
          )}
          {cancellable && (
            <Popconfirm
              title={t("run.monitor.cancelConfirm")}
              onConfirm={() => void onCancel()}
            >
              <Button danger loading={acting}>
                {t("run.monitor.cancelRun")}
              </Button>
            </Popconfirm>
          )}
          <Button onClick={() => navigate(-1)}>{t("run.monitor.back")}</Button>
          <Button onClick={() => navigate("/projects")}>{t("run.monitor.backHome")}</Button>
        </Space>
      </Space>

      {run?.error && (
        <Alert
          type="error"
          message={gated ? t("run.monitor.gateTitle") : t("run.monitor.runFailed")}
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
                        {f.severity === "blocker"
                          ? t("run.monitor.blocker")
                          : t("run.monitor.critical")}
                      </Tag>
                      <strong>{f.code}</strong>: {f.message}
                      {f.recommended_action && (
                        <div style={{ color: "#666" }}>
                          {t("run.monitor.recommendedAction", { action: f.recommended_action })}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {progress && Object.keys(progress.errors).length > 0 && (
                <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
                  {Object.entries(progress.errors).map(([key, err]) => (
                    <li key={key}>
                      <strong>{key}</strong>: {err}
                    </li>
                  ))}
                </ul>
              )}
              {gated && (
                <Space style={{ marginTop: 12 }}>
                  <Button danger loading={acting} onClick={() => setExploratoryOpen(true)}>
                    {t("run.monitor.exploratoryAction")}
                  </Button>
                  <Button onClick={() => navigate(-1)}>{t("run.monitor.backToCleaning")}</Button>
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
          message={t("run.monitor.exploratoryTitle")}
          description={t("run.monitor.exploratoryDescription")}
        />
      )}

      {/* §73-74：大数据集优化模式（分层采样真实记录） */}
      {run?.integrity?.sampling?.sampled && (
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 16 }}
          message={t("run.monitor.samplingTitle")}
          description={t("run.monitor.samplingDescription", {
            original: formatNumber(run.integrity.sampling.original_rows, i18n.language),
            sampled: formatNumber(run.integrity.sampling.sampled_rows, i18n.language),
          })}
        />
      )}

      <Card>
        {progress ? <RunProgressBoard progress={progress} /> : t("run.monitor.loading")}
        {failedModels.length > 0 && (
          <Space style={{ marginTop: 16 }} wrap>
            {failedModels.map((key) => (
              <Button key={key} size="small" disabled={acting} onClick={() => void onRerun(key)}>
                {t("run.monitor.rerunModel", { model: key })}
              </Button>
            ))}
          </Space>
        )}
      </Card>

      <Modal
        open={exploratoryOpen}
        title={t("run.monitor.modal.title")}
        width={560}
        okText={t("run.monitor.modal.ok")}
        okButtonProps={{ danger: true, loading: acting }}
        cancelText={t("run.monitor.modal.cancel")}
        onOk={() => void onConfirmExploratory()}
        onCancel={() => {
          setExploratoryOpen(false);
          navigate(-1);
        }}
      >
        <p>{t("run.monitor.modal.body1")}</p>
        <p style={{ fontWeight: 600 }}>{t("run.monitor.modal.statement")}</p>
        <p>{t("run.monitor.modal.body2")}</p>
      </Modal>
    </div>
  );
}
