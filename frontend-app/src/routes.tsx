import { Routes, Route, Navigate } from "react-router-dom";
import LoginPage from "./pages/login";
import RegisterPage from "./pages/register";
import DashboardPage from "./pages/dashboard";
import TeacherPage from "./pages/teacher";
import AdminPage from "./pages/admin";
import AdminStatsPage from "./pages/admin-stats";
import AccessDeniedPage from "./pages/access-denied";
import { AppShellLayout } from "./components/AppShell";

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/login.html" element={<Navigate to="/login" replace />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/register.html" element={<Navigate to="/register" replace />} />
      <Route path="/access-denied" element={<AccessDeniedPage />} />
      <Route path="/access-denied.html" element={<Navigate to="/access-denied" replace />} />

      {/* Routes protégées enveloppées par AppShell */}
      <Route element={<AppShellLayout />}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/index.html" element={<Navigate to="/" replace />} />
      </Route>

      <Route element={<AppShellLayout requireRole={["teacher", "admin"]} />}>
        <Route path="/teacher" element={<TeacherPage />} />
        <Route path="/teacher.html" element={<Navigate to="/teacher" replace />} />
      </Route>

      <Route element={<AppShellLayout requireRole={["admin"]} />}>
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/admin.html" element={<Navigate to="/admin" replace />} />
        <Route path="/admin-stats" element={<AdminStatsPage />} />
        <Route path="/admin-stats.html" element={<Navigate to="/admin-stats" replace />} />
      </Route>

      {/* Redirection fallback */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
