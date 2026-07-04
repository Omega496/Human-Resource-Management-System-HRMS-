import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Invitations } from "./Invitations";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

describe("Invitations Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const futureExpiration = new Date();
  futureExpiration.setHours(futureExpiration.getHours() + 24);

  const pastExpiration = new Date();
  pastExpiration.setHours(pastExpiration.getHours() - 2);

  const mockInvitationsList = {
    data: [
      {
        id: "inv-1",
        email: "pending@example.com",
        role: "employee",
        expires_at: futureExpiration.toISOString(),
        used_at: null,
        created_at: new Date().toISOString(),
      },
      {
        id: "inv-2",
        email: "used@example.com",
        role: "admin",
        expires_at: futureExpiration.toISOString(),
        used_at: new Date().toISOString(),
        created_at: new Date().toISOString(),
      },
      {
        id: "inv-3",
        email: "expired@example.com",
        role: "employee",
        expires_at: pastExpiration.toISOString(),
        used_at: null,
        created_at: new Date().toISOString(),
      },
    ],
  };

  it("loads invitations and derives the correct status on client-side", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockInvitationsList);

    render(<Invitations />);

    await waitFor(() => {
      const rows = screen.getAllByTestId("invitation-row");
      expect(rows).toHaveLength(3);
    });

    const statuses = screen.getAllByTestId("invitation-status");
    expect(statuses[0]).toHaveTextContent("pending");
    expect(statuses[1]).toHaveTextContent("used");
    expect(statuses[2]).toHaveTextContent("expired");
  });

  it("submits the form to issue a new invitation", async () => {
    vi.mocked(api.get).mockResolvedValue(mockInvitationsList);
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        invitation_link: "https://example.com/accept-invitation?token=token123",
        raw_token: "token123",
        email: "new@example.com",
        role: "employee",
      },
    });

    render(<Invitations />);

    await waitFor(() => {
      expect(screen.getAllByTestId("invitation-row")).toHaveLength(3);
    });

    const emailInput = screen.getByLabelText(/email address/i);
    const roleSelect = screen.getByLabelText(/role/i);
    const submitBtn = screen.getByRole("button", { name: /create invitation/i });

    fireEvent.change(emailInput, { target: { value: "new@example.com" } });
    fireEvent.change(roleSelect, { target: { value: "employee" } });
    fireEvent.click(submitBtn);

    expect(api.post).toHaveBeenCalledWith("/invitations", {
      email: "new@example.com",
      role: "employee",
    });

    await waitFor(() => {
      expect(screen.getByText(/invitation created successfully!/i)).toBeInTheDocument();
      expect(screen.getByText("https://example.com/accept-invitation?token=token123")).toBeInTheDocument();
    });
  });
});
