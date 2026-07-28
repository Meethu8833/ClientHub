import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppShell } from "./components/layout/AppShell";
import { ToastProvider } from "./components/ui/Toast";
import { AuthProvider } from "./features/auth/AuthProvider";
import { LoginPage } from "./features/auth/LoginPage";
import { ProtectedRoute } from "./features/auth/ProtectedRoute";
import { ClientDetailPage } from "./features/clients/pages/ClientDetailPage";
import { ClientListPage } from "./features/clients/pages/ClientListPage";
import { DashboardPage } from "./features/dashboard/pages/DashboardPage";

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

export default function App() {
  return (
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
                  {/* Future: /projects, /tasks… slot in right here. */}
                </Route>
              </Route>

              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ToastProvider>
    </QueryClientProvider>
  );
}
