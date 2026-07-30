import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { AuthProvider } from "./features/auth/AuthProvider";
import { LoginPage } from "./features/auth/LoginPage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { RoleRoute } from "./features/auth/RoleRoute";
import { ClientDetailPage } from "./features/clients/pages/ClientDetailPage";
import { ClientListPage } from "./features/clients/pages/ClientListPage";
import { DashboardPage } from "./features/dashboard/pages/DashboardPage";
import { ProjectDetailPage } from "./features/projects/pages/ProjectDetailPage";
import { ProjectListPage } from "./features/projects/pages/ProjectListPage";
import { TaskListPage } from "./features/projects/pages/TaskListPage";
import { ThemeProvider } from "./features/theme/ThemeProvider";
import { UserListPage } from "./features/users/pages/UserListPage";
import { ROLES } from "./lib/constants";

// One client for the whole app — it owns the server-state cache.
// Created outside the component so re-renders never rebuild (and wipe) it.
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1, // one retry on failure; our axios layer already handles 401s
      refetchOnWindowFocus: false, // less surprising while developing
      staleTime: 30_000, // data is "fresh" for 30 s — no duplicate fetches
    },
  },
});

// ThemeProvider is outermost: it only writes a class onto <html>, and
// everything below it (including toasts and modals rendered in portals) must
// be able to read the theme.
export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <AuthProvider>
            <BrowserRouter>
              <Routes>
                <Route path="/login" element={<LoginPage />} />

                {/* Everything below requires a session (ProtectedRoute) and
                    renders inside the sidebar/topbar frame (AppShell). */}
                <Route element={<ProtectedRoute />}>
                  <Route element={<AppShell />}>
                    <Route path="/" element={<DashboardPage />} />
                    <Route path="/clients" element={<ClientListPage />} />
                    <Route path="/clients/:id" element={<ClientDetailPage />} />

                    <Route path="/projects" element={<ProjectListPage />} />
                    <Route path="/projects/:id" element={<ProjectDetailPage />} />
                    {/* Tasks belong to the projects app; /tasks is the
                        cross-project view of them, not a separate feature. */}
                    <Route path="/tasks" element={<TaskListPage />} />

                    {/* Admin-only section. The gate is a layout route so
                        every future /admin/* page inherits it — and the
                        server enforces IsAdmin on the endpoints regardless. */}
                    <Route element={<RoleRoute roles={[ROLES.ADMIN]} />}>
                      <Route path="/admin/users" element={<UserListPage />} />
                    </Route>
                    {/* Future: /tickets, /quotations… slot in right here. */}
                  </Route>
                </Route>

                <Route path="*" element={<Navigate to="/" replace />} />
              </Routes>
            </BrowserRouter>
          </AuthProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
