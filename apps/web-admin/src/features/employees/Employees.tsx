import { useEffect, useState, useCallback } from "react";
import { api } from "../../api/client";
import "./Employees.css";

interface EmployeeItem {
  id: string;
  email: string;
  full_name: string;
  timezone: string;
  role: string;
  status: "active" | "terminated" | "pseudonymized";
  deleted_at: string | null;
}

export function Employees() {
  const [employees, setEmployees] = useState<EmployeeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchEmployees = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<EmployeeItem[]>("/employees");
      setEmployees(response.data || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load employees list.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchEmployees();
  }, [fetchEmployees]);

  const handleTerminate = async (employee: EmployeeItem) => {
    setError(null);
    setSuccess(null);

    const confirmed = window.confirm(
      `Are you sure you want to terminate ${employee.full_name}?`
    );
    if (!confirmed) {
      return;
    }

    try {
      await api.post(`/employees/${employee.id}/terminate`);
      setSuccess(`Employee ${employee.full_name} has been terminated.`);
      await fetchEmployees();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to terminate employee.");
    }
  };

  const handleForget = async (employee: EmployeeItem) => {
    setError(null);
    setSuccess(null);

    const confirmed = window.confirm(
      `WARNING: The Right-to-be-Forgotten request is irreversible.\nThis will anonymize and permanently delete all personal data for ${employee.full_name} per GDPR requirements.\n\nProceed?`
    );
    if (!confirmed) {
      return;
    }

    try {
      await api.post(`/offboarding/${employee.id}/forget`);
      setSuccess(
        `Right-to-be-forgotten request processed for ${employee.full_name}. Data pseudonymized.`
      );
      await fetchEmployees();
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          "Failed to process right-to-be-forgotten request."
      );
    }
  };

  return (
    <div className="employees-container">
      <h1 className="employees-title">Employees Directory</h1>

      {error && (
        <div className="error-banner" role="alert">
          {error}
        </div>
      )}

      {success && (
        <div className="success-banner" role="alert">
          {success}
        </div>
      )}

      <div className="card">
        {loading && employees.length === 0 ? (
          <p>Loading directory...</p>
        ) : employees.length === 0 ? (
          <p>No employee records found.</p>
        ) : (
          <div className="table-wrapper">
            <table className="employees-table">
              <thead>
                <tr>
                  <th>Name / Email</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {employees.map((emp) => (
                  <tr key={emp.id} data-testid="employee-row">
                    <td>
                      <div
                        style={{
                          fontWeight: 500,
                          fontSize: "14px",
                          color: "var(--text-h)",
                        }}
                      >
                        {emp.full_name}
                      </div>
                      <div style={{ fontSize: "12px", color: "var(--text)" }}>
                        {emp.email}
                      </div>
                    </td>
                    <td style={{ textTransform: "capitalize" }}>{emp.role}</td>
                    <td>
                      <span className={`badge ${emp.status}`} data-testid="employee-status">
                        {emp.status}
                      </span>
                    </td>
                    <td>
                      {emp.status === "active" && (
                        <button
                          onClick={() => handleTerminate(emp)}
                          className="btn-terminate"
                          data-testid="terminate-button"
                        >
                          Terminate
                        </button>
                      )}
                      {emp.status === "terminated" && (
                        <button
                          onClick={() => handleForget(emp)}
                          className="btn-forget"
                          data-testid="forget-button"
                        >
                          Process Forget Request
                        </button>
                      )}
                      {emp.status === "pseudonymized" && (
                        <span style={{ fontSize: "13px", color: "var(--text)" }}>
                          No Actions (Pseudonymized)
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
