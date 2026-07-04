import { useEffect, useState, useCallback, type FormEvent } from "react";
import { api } from "../../api/client";
import type { components } from "@hrms/shared-types";
import "./Invitations.css";

type InvitationCreate = components["schemas"]["InvitationCreate"];

interface InvitationItem {
  id: string;
  email: string;
  role: string;
  expires_at: string;
  used_at: string | null;
  created_at: string;
}

export function Invitations() {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("employee");
  const [invitations, setInvitations] = useState<InvitationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [submitLoading, setSubmitLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [generatedLink, setGeneratedLink] = useState<string | null>(null);

  const fetchInvitations = useCallback(async () => {
    setLoading(true);
    try {
      const response = await api.get<InvitationItem[]>("/invitations");
      setInvitations(response.data || []);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load invitations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchInvitations();
  }, [fetchInvitations]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);
    setGeneratedLink(null);

    if (!email) {
      setError("Email is required.");
      return;
    }

    setSubmitLoading(true);
    try {
      const payload: InvitationCreate = {
        email,
        role,
      };

      const response = await api.post<any>("/invitations", payload);

      setSuccess("Invitation created successfully!");
      setGeneratedLink(response.data.invitation_link);
      setEmail("");
      setRole("employee");
      // Refresh the table
      await fetchInvitations();
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail[0]?.msg
            : "Failed to create invitation. Please try again."
      );
    } finally {
      setSubmitLoading(false);
    }
  };

  const deriveStatus = (usedAt: string | null, expiresAt: string) => {
    if (usedAt) return "used";
    const expiration = new Date(expiresAt).getTime();
    if (expiration < Date.now()) return "expired";
    return "pending";
  };

  const formatDateTime = (isoString: string) => {
    if (!isoString) return "";
    const dateObj = new Date(isoString);
    const yyyy = dateObj.getFullYear();
    const mm = String(dateObj.getMonth() + 1).padStart(2, "0");
    const dd = String(dateObj.getDate()).padStart(2, "0");
    const hh = String(dateObj.getHours()).padStart(2, "0");
    const min = String(dateObj.getMinutes()).padStart(2, "0");
    return `${yyyy}-${mm}-${dd} ${hh}:${min}`;
  };

  return (
    <div className="invitation-container">
      <h1>Invitation Management</h1>

      <div className="invitation-grid">
        {/* Form Card */}
        <div className="card">
          <h2 className="form-title">Issue Invitation</h2>

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
              <label htmlFor="email">Email Address</label>
              <input
                id="email"
                type="email"
                className="input-control"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="candidate@company.com"
                required
                disabled={submitLoading}
              />
            </div>

            <div className="form-group">
              <label htmlFor="role">Role</label>
              <select
                id="role"
                className="input-control"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                disabled={submitLoading}
              >
                <option value="employee">Employee</option>
                <option value="admin">Administrator</option>
              </select>
            </div>

            <button
              type="submit"
              className="btn-primary"
              disabled={submitLoading || !email}
            >
              {submitLoading ? "Generating..." : "Create Invitation"}
            </button>
          </form>

          {generatedLink && (
            <div className="link-box">
              <strong>Registration Link:</strong>
              <div style={{ marginTop: "4px" }}>{generatedLink}</div>
            </div>
          )}
        </div>

        {/* History Table Card */}
        <div className="card">
          <h2 className="list-title">Issued Invitations</h2>

          {loading && invitations.length === 0 ? (
            <p>Loading invitations...</p>
          ) : invitations.length === 0 ? (
            <p>No invitations found.</p>
          ) : (
            <div className="table-wrapper">
              <table className="invitation-table">
                <thead>
                  <tr>
                    <th>Email / Role</th>
                    <th>Status</th>
                    <th>Expires</th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.map((invite) => {
                    const status = deriveStatus(invite.used_at, invite.expires_at);
                    return (
                      <tr key={invite.id} data-testid="invitation-row">
                        <td>
                          <div
                            style={{
                              fontWeight: 500,
                              fontSize: "14px",
                              color: "var(--text-h)",
                            }}
                          >
                            {invite.email}
                          </div>
                          <div
                            style={{
                              fontSize: "12px",
                              color: "var(--text)",
                              textTransform: "capitalize",
                            }}
                          >
                            {invite.role}
                          </div>
                        </td>
                        <td>
                          <span
                            className={`badge ${status}`}
                            data-testid="invitation-status"
                          >
                            {status}
                          </span>
                        </td>
                        <td style={{ fontSize: "13px" }}>
                          {formatDateTime(invite.expires_at)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
