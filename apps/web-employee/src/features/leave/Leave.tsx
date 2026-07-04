import { useEffect, useState, useCallback, type FormEvent } from "react";
import { api } from "../../api/client";
import type { components } from "@hrms/shared-types";
import "./Leave.css";

type LeaveRequestCreate = components["schemas"]["LeaveRequestCreate"];

interface LeaveRequestItem {
  id: string;
  employee_id: string;
  start_time: string;
  end_time: string;
  status: "pending" | "approved" | "rejected";
}

export function Leave() {
  const [startTime, setStartTime] = useState("");
  const [endTime, setEndTime] = useState("");
  const [requests, setRequests] = useState<LeaveRequestItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const fetchRequests = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<LeaveRequestItem[]>("/leave-requests");
      setRequests(response.data || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load leave requests.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRequests();
  }, [fetchRequests]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    if (!startTime || !endTime) {
      setError("Please select both start and end date/time.");
      return;
    }

    const start = new Date(startTime);
    const end = new Date(endTime);

    if (end <= start) {
      setError("End time must be after start time.");
      return;
    }

    setSubmitLoading(true);
    try {
      const payload: LeaveRequestCreate = {
        start_time: start.toISOString(),
        end_time: end.toISOString(),
      };

      await api.post("/leave-requests", payload);

      setSuccess("Leave request submitted successfully!");
      setStartTime("");
      setEndTime("");
      // Refresh requests list
      await fetchRequests();
    } catch (err: any) {
      if (err.response?.status === 409) {
        // Specifically show the conflict message
        setError(err.response.data?.detail || "Overlapping leave request already exists.");
      } else {
        const detail = err.response?.data?.detail;
        setError(
          typeof detail === "string"
            ? detail
            : Array.isArray(detail)
              ? detail[0]?.msg
              : "Failed to submit leave request. Please try again."
        );
      }
    } finally {
      setSubmitLoading(false);
    }
  };

  const formatDateTime = (isoString: string) => {
    if (!isoString) return "";
    const dateObj = new Date(isoString);
    // Format to a readable string (e.g. YYYY-MM-DD HH:MM)
    const yyyy = dateObj.getFullYear();
    const mm = String(dateObj.getMonth() + 1).padStart(2, "0");
    const dd = String(dateObj.getDate()).padStart(2, "0");
    const hh = String(dateObj.getHours()).padStart(2, "0");
    const min = String(dateObj.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  };

  return (
    <div className="leave-container">
      <h1>Leave Requests</h1>

      <div className="leave-grid">
        {/* Form Card */}
        <div className="card">
          <h2 className="form-title">Request Leave</h2>

          {error && (
            <div className="error-banner" role="alert" id="error-message">
              {error}
            </div>
          )}

          {success && (
            <div className="success-banner" role="alert" id="success-message">
              {success}
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate>
            <div className="form-group">
              <label htmlFor="start_time">Start Date & Time</label>
              <input
                id="start_time"
                type="datetime-local"
                className="input-control"
                value={startTime}
                onChange={(e) => setStartTime(e.target.value)}
                required
                disabled={submitLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="end_time">End Date & Time</label>
              <input
                id="end_time"
                type="datetime-local"
                className="input-control"
                value={endTime}
                onChange={(e) => setEndTime(e.target.value)}
                required
                disabled={submitLoading}
              />
            </div>

            <button
              type="submit"
              className="btn-primary"
              disabled={submitLoading || !startTime || !endTime}
            >
              {submitLoading ? "Submitting..." : "Submit Request"}
            </button>
          </form>
        </div>

        {/* History List Card */}
        <div className="card">
          <h2 className="list-title">My Leave History</h2>

          {loading && requests.length === 0 ? (
            <p>Loading history...</p>
          ) : requests.length === 0 ? (
            <p>No leave requests found.</p>
          ) : (
            <div className="table-wrapper">
              <table className="leave-table">
                <thead>
                  <tr>
                    <th>Period</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {requests.map((req) => (
                    <tr key={req.id} data-testid="leave-row">
                      <td>
                        <div style={{ fontWeight: 500, fontSize: "14px", color: "var(--text-h)" }}>
                          {formatDateTime(req.start_time)}
                        </div>
                        <div style={{ fontSize: "12px", color: "var(--text)" }}>
                          to {formatDateTime(req.end_time)}
                        </div>
                      </td>
                      <td>
                        <span className={`badge ${req.status}`} data-testid="leave-status">
                          {req.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
