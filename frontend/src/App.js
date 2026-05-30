import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import "@/App.css";
import "@/index.css";
import { AuthProvider, useAuth } from "@/lib/auth";
import { Toaster } from "@/components/ui/sonner";
import Login from "@/pages/Login";
import Register from "@/pages/Register";
import Dashboard from "@/pages/Dashboard";
import StrategyBuilder from "@/pages/StrategyBuilder";
import Backtest from "@/pages/Backtest";
import PaperExecution from "@/pages/PaperExecution";
import TrapDetection from "@/pages/TrapDetection";
import Journal from "@/pages/Journal";
import AuditLog from "@/pages/AuditLog";
import Admin from "@/pages/Admin";
import Brokers from "@/pages/Brokers";
import Settings from "@/pages/Settings";

function ProtectedRoute({ children }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-[var(--bg-page)] text-zinc-400">
        <div className="overline animate-pulse">Initialising cockpit…</div>
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

function PublicOnly({ children }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (user) return <Navigate to="/" replace />;
  return children;
}

function App() {
  useEffect(() => {
    document.documentElement.classList.add("dark");
    document.title = "AlgoForge — AI Trading Cockpit";
  }, []);

  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<PublicOnly><Login /></PublicOnly>} />
          <Route path="/register" element={<PublicOnly><Register /></PublicOnly>} />
          <Route path="/" element={<ProtectedRoute><Dashboard /></ProtectedRoute>} />
          <Route path="/strategies" element={<ProtectedRoute><StrategyBuilder /></ProtectedRoute>} />
          <Route path="/backtest" element={<ProtectedRoute><Backtest /></ProtectedRoute>} />
          <Route path="/paper" element={<ProtectedRoute><PaperExecution /></ProtectedRoute>} />
          <Route path="/trap" element={<ProtectedRoute><TrapDetection /></ProtectedRoute>} />
          <Route path="/journal" element={<ProtectedRoute><Journal /></ProtectedRoute>} />
          <Route path="/audit" element={<ProtectedRoute><AuditLog /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute><Admin /></ProtectedRoute>} />
          <Route path="/brokers" element={<ProtectedRoute><Brokers /></ProtectedRoute>} />
          <Route path="/settings" element={<ProtectedRoute><Settings /></ProtectedRoute>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <Toaster position="bottom-right" richColors closeButton duration={5000} />
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
