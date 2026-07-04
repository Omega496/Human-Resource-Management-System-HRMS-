import { Routes, Route, NavLink, useNavigate, Navigate } from "react-router-dom";
import { Login } from "./features/auth/Login";
import { Attendance } from "./features/attendance/Attendance";
import { Leave } from "./features/leave/Leave";
import { getAccessToken, setAccessToken, api } from "./api/client";
import "./App.css";

interface ProtectedLayoutProps {
  children: React.ReactNode;
}

function ProtectedLayout({ children }: ProtectedLayoutProps) {
  const token = getAccessToken();
  const navigate = useNavigate();

  if (!token) {
    return <Navigate to="/login" replace />;
  }

  const handleLogout = async () => {
    try {
      await api.post("/auth/logout");
    } catch (err) {
      console.error("Failed to call logout endpoint:", err);
    } finally {
      setAccessToken(null);
      navigate("/login");
    }
  };

  return (
    <div className="app-wrapper">
      <header className="app-header">
        <div className="header-logo">HRMS Employee Portal</div>
        <nav className="header-nav">
          <NavLink
            to="/dashboard"
            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/leave"
            className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}
          >
            Leave Requests
          </NavLink>
        </nav>
        <button onClick={handleLogout} className="btn-logout">
          Logout
        </button>
      </header>
      <main className="app-main">{children}</main>
    </div>
  );
}

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/dashboard"
        element={
          <ProtectedLayout>
            <Attendance />
          </ProtectedLayout>
        }
      />
      <Route
        path="/leave"
        element={
          <ProtectedLayout>
            <Leave />
          </ProtectedLayout>
        }
      />
      {/* Default Redirect */}
      <Route path="*" element={<Navigate to="/dashboard" replace />} />
    </Routes>
  );
}

export default App;
