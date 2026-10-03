import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext.jsx";
import { ToastProvider } from "./context/ToastContext.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import RegisterPage from "./pages/RegisterPage.jsx";
import FileBrowserPage from "./pages/FileBrowserPage.jsx";
import RecycleBinPage from "./pages/RecycleBinPage.jsx";
import SharedLinkPage from "./pages/SharedLinkPage.jsx";
import DashboardPage from "./pages/DashboardPage.jsx";
import AdminPage from "./pages/AdminPage.jsx";

function ProtectedRoute({ children }) {
  const { token } = useAuth();
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      {/* Public: no auth, no ProtectedRoute -- anyone with the token URL. */}
      <Route path="/shared/:token" element={<SharedLinkPage />} />
      <Route
        path="/recycle-bin"
        element={
          <ProtectedRoute>
            <RecycleBinPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin"
        element={
          <ProtectedRoute>
            <AdminPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/dashboard"
        element={
          <ProtectedRoute>
            <DashboardPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/app"
        element={
          <ProtectedRoute>
            <FileBrowserPage />
          </ProtectedRoute>
        }
      />
      {/* Old top-level URL, kept so existing links/bookmarks still work. */}
      <Route path="/app/root" element={<Navigate to="/app" replace />} />
      <Route
        path="/app/:folderId"
        element={
          <ProtectedRoute>
            <FileBrowserPage />
          </ProtectedRoute>
        }
      />
      <Route path="*" element={<Navigate to="/app" replace />} />
    </Routes>
  );
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <AppRoutes />
      </AuthProvider>
    </ToastProvider>
  );
}
