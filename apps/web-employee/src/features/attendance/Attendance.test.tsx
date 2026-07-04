import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Attendance } from "./Attendance";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

describe("Attendance Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const mockHistoryClockedOut = {
    data: {
      events: [
        {
          id: "1",
          event_type: "clock_out" as const,
          recorded_at_utc: "2026-07-04T09:00:00Z",
          recorded_at_local: "2026-07-04T14:30:00",
          client_reported_at: "2026-07-04T14:30:00Z",
        },
        {
          id: "2",
          event_type: "clock_in" as const,
          recorded_at_utc: "2026-07-04T05:00:00Z",
          recorded_at_local: "2026-07-04T10:30:00",
          client_reported_at: "2026-07-04T10:30:00Z",
        },
      ],
    },
  };

  const mockHistoryClockedIn = {
    data: {
      events: [
        {
          id: "3",
          event_type: "clock_in" as const,
          recorded_at_utc: "2026-07-04T10:00:00Z",
          recorded_at_local: "2026-07-04T15:30:00",
          client_reported_at: "2026-07-04T15:30:00Z",
        },
      ],
    },
  };

  it("loads and displays the current clocked-out status and history", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockHistoryClockedOut);

    render(<Attendance />);

    // Shows loading initially
    expect(screen.getByTestId("status-text")).toHaveTextContent(/loading/i);

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked Out");
      expect(screen.getByTestId("clock-button")).toHaveTextContent("Clock In");
      expect(screen.getByTestId("status-indicator")).toHaveClass("inactive");
    });

    const rows = screen.getAllByTestId("history-row");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("Clock Out");
    expect(rows[0]).toHaveTextContent("2026-07-04 14:30:00");
    expect(rows[1]).toHaveTextContent("Clock In");
    expect(rows[1]).toHaveTextContent("2026-07-04 10:30:00");
  });

  it("loads and displays the current clocked-in status and history", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockHistoryClockedIn);

    render(<Attendance />);

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked In");
      expect(screen.getByTestId("clock-button")).toHaveTextContent("Clock Out");
      expect(screen.getByTestId("status-indicator")).toHaveClass("active");
    });

    const rows = screen.getAllByTestId("history-row");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Clock In");
  });

  it("performs a clock-in action when clicked in clocked-out state", async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(mockHistoryClockedOut) // mount
      .mockResolvedValueOnce(mockHistoryClockedIn); // refetch after clock-in

    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });

    render(<Attendance />);

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked Out");
    });

    const clockButton = screen.getByTestId("clock-button");
    fireEvent.click(clockButton);

    expect(api.post).toHaveBeenCalledWith("/attendance/clock-in", expect.any(Object));

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked In");
    });
  });

  it("performs a clock-out action when clicked in clocked-in state", async () => {
    vi.mocked(api.get)
      .mockResolvedValueOnce(mockHistoryClockedIn) // mount
      .mockResolvedValueOnce(mockHistoryClockedOut); // refetch after clock-out

    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });

    render(<Attendance />);

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked In");
    });

    const clockButton = screen.getByTestId("clock-button");
    fireEvent.click(clockButton);

    expect(api.post).toHaveBeenCalledWith("/attendance/clock-out", expect.any(Object));

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked Out");
    });
  });

  it("displays an error banner when clock event toggle fails", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockHistoryClockedOut);
    const errorMessage = "Cannot clock in. You are already clocked in.";
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: errorMessage,
        },
      },
    });

    render(<Attendance />);

    await waitFor(() => {
      expect(screen.getByTestId("status-text")).toHaveTextContent("Clocked Out");
    });

    const clockButton = screen.getByTestId("clock-button");
    fireEvent.click(clockButton);

    await waitFor(() => {
      const errorDiv = screen.getByRole("alert");
      expect(errorDiv).toBeInTheDocument();
      expect(errorDiv).toHaveTextContent(errorMessage);
    });
  });
});
