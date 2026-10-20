import { ConfigProvider } from "antd";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { applyLocale, getAntdLocale, normalizeLocale } from "./i18n/locale";
import { getRole, getToken, restoreSession } from "./api";
import AdminLLMSettingsPage from "./pages/AdminLLMSettingsPage";
import AdminPluginsPage from "./pages/AdminPluginsPage";
import AnalysisWizardPage from "./pages/AnalysisWizardPage";
import ComparisonPage from "./pages/ComparisonPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import LoginPage from "./pages/LoginPage";
import PreparationWizardPage from "./pages/PreparationWizardPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectsPage from "./pages/ProjectsPage";
import ReportsPage from "./pages/ReportsPage";
import RunMonitorPage from "./pages/RunMonitorPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  const [state, setState] = useState<"checking" | "ready" | "missing">(
    getToken() ? "ready" : "checking",
  );
  useEffect(() => {
    if (state !== "checking") return;
    void restoreSession().then((ok) => setState(ok ? "ready" : "missing"));
  }, [state]);
  if (state === "checking") return null;
  return state === "ready" ? children : <Navigate to="/login" replace />;
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  return <RequireAuth><AdminOnly>{children}</AdminOnly></RequireAuth>;
}

function AdminOnly({ children }: { children: JSX.Element }) {
  return getRole() === "admin" ? children : <Navigate to="/projects" replace />;
}

export default function App() {
  const { i18n } = useTranslation();
  const locale = normalizeLocale(i18n.resolvedLanguage ?? i18n.language);

  useEffect(() => {
    applyLocale(locale, i18n.t("common.app.title"));
  }, [i18n, locale]);

  return (
    <ConfigProvider
      locale={getAntdLocale(locale)}
      theme={{
        token: {
          // 学术编辑风（docs/11 §6）：墨黑/藏青/纸白/hairline，克制的圆角
          colorPrimary: "#1f4e79",
          colorInfo: "#1f4e79",
          colorLink: "#1f4e79",
          borderRadius: 4,
          colorBgLayout: "#faf9f6",
          colorBorderSecondary: "#e3e0d8",
          colorTextBase: "#1a1a1a",
          fontFamily:
            "-apple-system, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
        },
        components: {
          Card: { boxShadowTertiary: "none" },
          Button: { fontWeight: 500 },
        },
      }}
    >
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route
            path="/projects"
            element={
              <RequireAuth>
                <ProjectsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/projects/:id"
            element={
              <RequireAuth>
                <ProjectDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/datasets/:id"
            element={
              <RequireAuth>
                <DatasetDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:id"
            element={
              <RequireAuth>
                <RunMonitorPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:id/comparison"
            element={
              <RequireAuth>
                <ComparisonPage />
              </RequireAuth>
            }
          />
          <Route
            path="/runs/:id/reports"
            element={
              <RequireAuth>
                <ReportsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/projects/:id/preparation/new"
            element={
              <RequireAuth>
                <PreparationWizardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/projects/:id/analysis/new"
            element={
              <RequireAuth>
                <AnalysisWizardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/plugins"
            element={
              <RequireAdmin>
                <AdminPluginsPage />
              </RequireAdmin>
            }
          />
          <Route
            path="/admin/ai-settings"
            element={
              <RequireAdmin>
                <AdminLLMSettingsPage />
              </RequireAdmin>
            }
          />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
