import { useEffect, useState, useCallback } from "react";
import { api } from "../../api/client";
import "./Payroll.css";

interface EmployeeItem {
  id: string;
  full_name: string;
  email: string;
  status: string;
}

interface PayrollLineItem {
  id: string;
  ledger_month: string;
  line_type: string;
  amount_cents: number;
  currency: string;
  status: "open" | "closed";
  adjustment_of: string | null;
  computed_from_rule_id: string | null;
  created_at: string;
}

export function Payroll() {
  const [employees, setEmployees] = useState<EmployeeItem[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState("");
  const [selectedMonth, setSelectedMonth] = useState("");
  const [lines, setLines] = useState<PayrollLineItem[]>([]);
  const [orgId, setOrgId] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Initialize month picker to current month
  useEffect(() => {
    const d = new Date();
    const mm = String(d.getMonth() + 1).padStart(2, "0");
    setSelectedMonth(`${d.getFullYear()}-${mm}`);
  }, []);

  // Fetch organization profile
  useEffect(() => {
    async function fetchProfile() {
      try {
        const response = await api.get<any>("/employees/me");
        setOrgId(response.data.organization_id);
      } catch (err) {
        console.error("Failed to load user organization info.", err);
      }
    }
    fetchProfile();
  }, []);

  // Fetch employees list
  useEffect(() => {
    async function fetchEmployees() {
      try {
        const response = await api.get<EmployeeItem[]>("/employees");
        const list = response.data || [];
        setEmployees(list);
        if (list.length > 0) {
          setSelectedEmployeeId(list[0].id);
        }
      } catch (err) {
        console.error("Failed to load employees list.", err);
      }
    }
    fetchEmployees();
  }, []);

  const fetchLedgerLines = useCallback(async () => {
    if (!selectedEmployeeId || !selectedMonth) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.get<PayrollLineItem[]>("/payroll/lines", {
        params: {
          employee_id: selectedEmployeeId,
          month: selectedMonth,
        },
      });
      setLines(response.data || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load payroll ledger lines.");
    } finally {
      setLoading(false);
    }
  }, [selectedEmployeeId, selectedMonth]);

  useEffect(() => {
    fetchLedgerLines();
  }, [fetchLedgerLines]);

  const handleCloseMonth = async () => {
    setError(null);
    setSuccess(null);

    if (!orgId) {
      setError("Organization information not loaded yet.");
      return;
    }
    if (!selectedMonth) {
      setError("Please select a month to close.");
      return;
    }

    const confirmed = window.confirm(
      `Are you sure you want to close the payroll month ${selectedMonth}?\nThis will finalize and close all open ledger lines for this month. This action is irreversible.`
    );
    if (!confirmed) {
      return;
    }

    try {
      // payload ledger_month requires YYYY-MM-DD
      const ledgerMonthDate = `${selectedMonth}-01`;
      const response = await api.post<any>("/payroll/close-month", {
        organization_id: orgId,
        ledger_month: ledgerMonthDate,
      });
      setSuccess(`Payroll month ${selectedMonth} closed successfully. ${response.data.closed_count} lines finalized.`);
      await fetchLedgerLines();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to close payroll month.");
    }
  };

  const handleAdjust = async (line: PayrollLineItem) => {
    setError(null);
    setSuccess(null);

    const reason = window.prompt("Please enter the reason for this adjustment:");
    if (reason === null) {
      // Cancelled
      return;
    }
    if (!reason.trim()) {
      setError("Adjustment reason is required.");
      return;
    }

    try {
      await api.post("/payroll/adjustments", {
        original_line_id: line.id,
        reason,
      });
      setSuccess("Adjustment line successfully recorded in the current open month.");
      await fetchLedgerLines();
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to record adjustment.");
    }
  };

  const formatAmount = (cents: number) => {
    return (cents / 100).toFixed(2);
  };

  return (
    <div className="payroll-container">
      <h1 className="payroll-title">Payroll Ledger Manager</h1>

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
        <div className="payroll-controls">
          <div className="control-group">
            <label htmlFor="employee-select">Employee</label>
            <select
              id="employee-select"
              className="input-control"
              value={selectedEmployeeId}
              onChange={(e) => setSelectedEmployeeId(e.target.value)}
            >
              {employees.map((emp) => (
                <option key={emp.id} value={emp.id}>
                  {emp.full_name} ({emp.email})
                </option>
              ))}
            </select>
          </div>

          <div className="control-group">
            <label htmlFor="month-select">Ledger Month</label>
            <input
              id="month-select"
              type="month"
              className="input-control"
              value={selectedMonth}
              onChange={(e) => setSelectedMonth(e.target.value)}
            />
          </div>

          <button
            onClick={handleCloseMonth}
            className="btn-close-month"
            data-testid="close-month-button"
          >
            Close Month
          </button>
        </div>
      </div>

      <div className="card">
        <h2>Ledger Details</h2>
        {loading && lines.length === 0 ? (
          <p>Loading ledger details...</p>
        ) : lines.length === 0 ? (
          <p>No ledger lines found for the selected employee and month.</p>
        ) : (
          <div className="table-wrapper">
            <table className="payroll-table">
              <thead>
                <tr>
                  <th>Line Type</th>
                  <th>Amount</th>
                  <th>Status</th>
                  <th>Reference</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {lines.map((line) => (
                  <tr key={line.id} data-testid="payroll-row">
                    <td style={{ textTransform: "capitalize", fontWeight: 500 }}>
                      {line.line_type}
                    </td>
                    <td>
                      {line.currency} {formatAmount(line.amount_cents)}
                    </td>
                    <td>
                      <span className={`badge ${line.status}`} data-testid="payroll-status">
                        {line.status}
                      </span>
                    </td>
                    <td style={{ fontSize: "12px", color: "var(--text)" }}>
                      {line.adjustment_of ? `Adjustment of ${line.adjustment_of.substring(0, 8)}...` : "None"}
                    </td>
                    <td>
                      {line.status === "closed" ? (
                        <button
                          onClick={() => handleAdjust(line)}
                          className="btn-adjust"
                          data-testid="adjust-button"
                        >
                          Record Adjustment
                        </button>
                      ) : (
                        <span style={{ fontSize: "13px", color: "var(--text)" }}>
                          Edit Open Line Directly
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
