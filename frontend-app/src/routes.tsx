import { lazy, Suspense } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RouteFallback } from "./components/RouteFallback";

// Every page is a separate chunk: the login screen stays small and students
// never download teacher/admin code.
const AppShellLayout = lazy(() => import("./components/AppShell").then((m) => ({ default: m.AppShellLayout })));
const LoginPage = lazy(() => import("./pages/login"));
const RegisterPage = lazy(() => import("./pages/register"));
const AccessDeniedPage = lazy(() => import("./pages/access-denied"));
const HomePage = lazy(() => import("./pages/home"));
const DashboardPage = lazy(() => import("./pages/dashboard"));
const MyAssignmentsPage = lazy(() => import("./pages/my-assignments"));
const AssignmentDetailPage = lazy(() => import("./pages/assignment-detail"));
const TeacherPage = lazy(() => import("./pages/teacher"));
const TeacherSubmissionsPage = lazy(() => import("./pages/teacher-submissions"));
const AdminPage = lazy(() => import("./pages/admin"));
const AdminStatsPage = lazy(() => import("./pages/admin-stats"));

export function AppRoutes() {
  const location = useLocation();

  return (
    // Pages inside the shell have their own boundary (AppShell); this one
    // catches public pages and the shell itself.
    <ErrorBoundary fullPage resetKey={location.pathname}>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login.html" element={<Navigate to="/login" replace />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/register.html" element={<Navigate to="/register" replace />} />
          <Route path="/access-denied" element={<AccessDeniedPage />} />
          <Route path="/access-denied.html" element={<Navigate to="/access-denied" replace />} />

          {/* Protected routes, wrapped by the AppShell */}
          <Route element={<AppShellLayout />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/index.html" element={<Navigate to="/" replace />} />
            <Route path="/labs" element={<DashboardPage />} />
            <Route path="/my-assignments" element={<MyAssignmentsPage />} />
            <Route path="/assignments/:aid" element={<AssignmentDetailPage />} />
          </Route>

          <Route element={<AppShellLayout requireRole={["teacher", "admin"]} />}>
            <Route path="/teacher" element={<TeacherPage />} />
            <Route path="/teacher.html" element={<Navigate to="/teacher" replace />} />
            <Route
              path="/teacher/classrooms/:cid/assignments/:aid/submissions"
              element={<TeacherSubmissionsPage />}
            />
          </Route>

          <Route element={<AppShellLayout requireRole={["admin"]} />}>
            <Route path="/admin" element={<AdminPage />} />
            <Route path="/admin.html" element={<Navigate to="/admin" replace />} />
            <Route path="/admin-stats" element={<AdminStatsPage />} />
            <Route path="/admin-stats.html" element={<Navigate to="/admin-stats" replace />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </ErrorBoundary>
  );
}
