import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { getRole, getToken } from "./api";
import AdminPluginsPage from "./pages/AdminPluginsPage";
import ComparisonPage from "./pages/ComparisonPage";
import DatasetDetailPage from "./pages/DatasetDetailPage";
import LoginPage from "./pages/LoginPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import ProjectsPage from "./pages/ProjectsPage";
import ReportsPage from "./pages/ReportsPage";
import RunMonitorPage from "./pages/RunMonitorPage";

function RequireAuth({ children }: { children: JSX.Element }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  if (!getToken()) return <Navigate to="/login" replace />;
  return getRole() === "admin" ? children : <Navigate to="/projects" replace />;
}

export default function App() {
  return (
    <ConfigProvider locale={zhCN}>
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
            path="/admin/plugins"
            element={
              <RequireAdmin>
                <AdminPluginsPage />
              </RequireAdmin>
            }
          />
          <Route path="*" element={<Navigate to="/projects" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  );
}
