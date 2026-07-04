import { useState, useEffect } from "react";
import { getAccessToken, setAccessToken } from "./api/client";
import { Login } from "./features/auth/Login";
import { Invitations } from "./features/invitations/Invitations";
import { Employees } from "./features/employees/Employees";
import { Payroll } from "./features/payroll/Payroll";
import "./App.css";

type Tab = "invitations" | "employees" | "payroll";

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [activeTab, setActiveTab] = useState<Tab>("invitations");

  useEffect(() => {
    // Check if we already have an in-memory token on mount
    const token = getAccessToken();
    if (token) {
      setIsAuthenticated(true);
    }
  }, []);

  const handleLogout = () => {
    setAccessToken(null);
    setIsAuthenticated(false);
  };

  if (!isAuthenticated) {
    return <Login onLoginSuccess={() => setIsAuthenticated(true)} />;
  }

  return (
    <div className="admin-layout">
      {/* Sidebar Navigation */}
      <aside className="sidebar">
        <div className="sidebar-header">
          <h2>HRMS Admin</h2>
        </div>

        <ul className="sidebar-menu">
          <li>
            <button
              onClick={() => setActiveTab("invitations")}
              className={`sidebar-link ${activeTab === "invitations" ? "active" : ""}`}
            >
              Invitations
            </button>
          </li>
          <li>
            <button
              onClick={() => setActiveTab("employees")}
              className={`sidebar-link ${activeTab === "employees" ? "active" : ""}`}
            >
              Employees Directory
            </button>
          </li>
          <li>
            <button
              onClick={() => setActiveTab("payroll")}
              className={`sidebar-link ${activeTab === "payroll" ? "active" : ""}`}
            >
              Payroll Ledgers
            </button>
          </li>
        </ul>

        <div className="sidebar-footer">
          <button onClick={handleLogout} className="btn-logout">
            Sign Out
          </button>
        </div>
      </aside>

      {/* Main Content Pane */}
      <main className="main-content">
        {activeTab === "invitations" && <Invitations />}
        {activeTab === "employees" && <Employees />}
        {activeTab === "payroll" && <Payroll />}
      </main>
    </div>
  );
}
