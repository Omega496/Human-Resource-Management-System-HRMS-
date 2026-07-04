import { useEffect, useState, useCallback } from "react";
import { api } from "../../api/client";
import "./Attendance.css";

interface ClockEventResponse {
  id: string;
  event_type: "clock_in" | "clock_out";
  recorded_at_utc: string;
  recorded_at_local: string;
  client_reported_at: string | null;
}

interface HistoryResponse {
  events: ClockEventResponse[];
}

export function Attendance() {
  const [events, setEvents] = useState<ClockEventResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const fourteenDaysAgo = new Date();
      fourteenDaysAgo.setDate(fourteenDaysAgo.getDate() - 14);
      // Ensure the timestamp has the correct format
      const fromDate = fourteenDaysAgo.toISOString();

      const response = await api.get<HistoryResponse>("/attendance/history", {
        params: { from_date: fromDate },
      });
      // Sort history descending by default to show most recent first
      const sortedEvents = [...(response.data.events || [])].sort(
        (a, b) =>
          new Date(b.recorded_at_utc).getTime() - new Date(a.recorded_at_utc).getTime()
      );
      setEvents(sortedEvents);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load attendance history.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // Determine current status from the most recent event
  const lastEvent = events[0]; // because it's sorted descending
  const isClockedIn = lastEvent && lastEvent.event_type === "clock_in";

  const handleClockToggle = async () => {
    setActionLoading(true);
    setError(null);
    const endpoint = isClockedIn ? "/attendance/clock-out" : "/attendance/clock-in";
    try {
      await api.post(endpoint, {
        client_reported_at: new Date().toISOString(),
      });
      // Refresh history to reflect the updated status
      await fetchHistory();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail[0]?.msg
            : "Failed to perform clock action. Please try again."
      );
    } finally {
      setActionLoading(false);
    }
  };

  const formatDateTime = (isoString: string) => {
    if (!isoString) return "";
    const parts = isoString.split("T");
    if (parts.length < 2) return isoString;
    const date = parts[0];
    const time = parts[1].substring(0, 8); // Keep HH:MM:SS
    return `${date} ${time}`;
  };

  return (
    <div className="attendance-container">
      <h1>Attendance Dashboard</h1>

      {error && (
        <div className="error-banner-att" role="alert" id="error-message-att">
          {error}
        </div>
      )}

      <div className="attendance-grid">
        {/* Status Card */}
        <div className="card status-card">
          <div className="status-indicator">
            <span
              className={`indicator-dot ${isClockedIn ? "active" : "inactive"}`}
              data-testid="status-indicator"
            />
            <span data-testid="status-text">
              {loading ? "Loading..." : isClockedIn ? "Clocked In" : "Clocked Out"}
            </span>
          </div>

          <button
            onClick={handleClockToggle}
            disabled={loading || actionLoading}
            className={`btn-clock ${isClockedIn ? "out" : "in"}`}
            data-testid="clock-button"
          >
            {actionLoading ? "Processing..." : isClockedIn ? "Clock Out" : "Clock In"}
          </button>
        </div>

        {/* History Card */}
        <div className="card history-card">
          <h2 className="history-title">Last 14 Days History</h2>
          {loading && events.length === 0 ? (
            <p>Loading history...</p>
          ) : events.length === 0 ? (
            <p>No attendance records for the last 14 days.</p>
          ) : (
            <div className="table-wrapper">
              <table className="history-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Time (Local Timezone)</th>
                    <th>Reported Time</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => (
                    <tr key={event.id} data-testid="history-row">
                      <td>
                        <span
                          className={`badge ${event.event_type === "clock_in" ? "in" : "out"}`}
                        >
                          {event.event_type === "clock_in" ? "Clock In" : "Clock Out"}
                        </span>
                      </td>
                      <td>{formatDateTime(event.recorded_at_local)}</td>
                      <td>
                        {event.client_reported_at
                          ? formatDateTime(event.client_reported_at)
                          : "N/A"}
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
