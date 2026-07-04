import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Leave } from "./Leave";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

describe("Leave Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const mockLeaveHistory = {
    data: [
      {
        id: "req-1",
        employee_id: "emp-123",
        start_time: "2026-07-06T09:00:00Z",
        end_time: "2026-07-08T18:00:00Z",
        status: "approved" as const,
      },
      {
        id: "req-2",
        employee_id: "emp-123",
        start_time: "2026-07-10T09:00:00Z",
        end_time: "2026-07-12T18:00:00Z",
        status: "pending" as const,
      },
    ],
  };

  it("loads and displays the list of past and pending requests with status badges", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockLeaveHistory);

    render(<Leave />);

    await waitFor(() => {
      const rows = screen.getAllByTestId("leave-row");
      expect(rows).toHaveLength(2);
    });

    const badges = screen.getAllByTestId("leave-status");
    expect(badges[0]).toHaveTextContent("approved");
    expect(badges[0]).toHaveClass("approved");
    expect(badges[1]).toHaveTextContent("pending");
    expect(badges[1]).toHaveClass("pending");
  });

  it("submits a new leave request successfully, clears form inputs, and updates history", async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(mockLeaveHistory) // initial load
      .mockResolvedValueOnce({
        data: [
          ...mockLeaveHistory.data,
          {
            id: "req-3",
            employee_id: "emp-123",
            start_time: "2026-07-15T09:00:00Z",
            end_time: "2026-07-17T18:00:00Z",
            status: "pending" as const,
          },
        ],
      }); // refetch

    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });

    render(<Leave />);

    await waitFor(() => {
      expect(screen.getAllByTestId("leave-row")).toHaveLength(2);
    });

    const startInput = screen.getByLabelText(/start date & time/i);
    const endInput = screen.getByLabelText(/end date & time/i);
    const submitButton = screen.getByRole("button", { name: /submit request/i });

    fireEvent.change(startInput, { target: { value: "2026-07-15T09:00" } });
    fireEvent.change(endInput, { target: { value: "2026-07-17T18:00" } });
    fireEvent.click(submitButton);

    const expectedStart = new Date("2026-07-15T09:00").toISOString();
    const expectedEnd = new Date("2026-07-17T18:00").toISOString();

    expect(api.post).toHaveBeenCalledWith("/leave-requests", {
      start_time: expectedStart,
      end_time: expectedEnd,
    });

    await waitFor(() => {
      expect(screen.getByText(/leave request submitted successfully!/i)).toBeInTheDocument();
      expect(startInput).toHaveValue("");
      expect(endInput).toHaveValue("");
      expect(screen.getAllByTestId("leave-row")).toHaveLength(3);
    });
  });

  it("handles a 409 conflict response showing the specific conflict message", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockLeaveHistory);
    const conflictMessage = "Overlapping leave request already exists: 2026-07-06T09:00:00 to 2026-07-08T18:00:00 (status: approved)";
    
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: conflictMessage,
        },
      },
    });

    render(<Leave />);

    await waitFor(() => {
      expect(screen.getAllByTestId("leave-row")).toHaveLength(2);
    });

    const startInput = screen.getByLabelText(/start date & time/i);
    const endInput = screen.getByLabelText(/end date & time/i);
    const submitButton = screen.getByRole("button", { name: /submit request/i });

    fireEvent.change(startInput, { target: { value: "2026-07-07T09:00" } });
    fireEvent.change(endInput, { target: { value: "2026-07-08T18:00" } });
    fireEvent.click(submitButton);

    await waitFor(() => {
      const errorDiv = screen.getByRole("alert");
      expect(errorDiv).toBeInTheDocument();
      expect(errorDiv).toHaveTextContent(conflictMessage);
    });
  });
});
