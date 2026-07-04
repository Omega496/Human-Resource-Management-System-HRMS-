import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Employees } from "./Employees";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

describe("Employees Feature - Irreversible Actions confirmation gating", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const mockEmployees = {
    data: [
      {
        id: "emp-active",
        email: "active@company.com",
        full_name: "Active Employee",
        timezone: "UTC",
        role: "employee",
        status: "active" as const,
        deleted_at: null,
      },
      {
        id: "emp-terminated",
        email: "terminated@company.com",
        full_name: "Terminated Employee",
        timezone: "UTC",
        role: "employee",
        status: "terminated" as const,
        deleted_at: "2026-07-04T09:00:00Z",
      },
    ],
  };

  it("gates termination behind a confirmation dialog; if dismissed, does NOT trigger API call", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockEmployees);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false); // Dismiss

    render(<Employees />);

    await waitFor(() => {
      expect(screen.getAllByTestId("employee-row")).toHaveLength(2);
    });

    const terminateBtn = screen.getByTestId("terminate-button");
    fireEvent.click(terminateBtn);

    expect(confirmSpy).toHaveBeenCalledWith("Are you sure you want to terminate Active Employee?");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("triggers termination API call when confirmation dialog is accepted", async () => {
    vi.mocked(api.get).mockResolvedValue(mockEmployees);
    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(true); // Accept

    render(<Employees />);

    await waitFor(() => {
      expect(screen.getAllByTestId("employee-row")).toHaveLength(2);
    });

    const terminateBtn = screen.getByTestId("terminate-button");
    fireEvent.click(terminateBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith("/employees/emp-active/terminate");
  });

  it("gates right-to-be-forgotten request behind a confirmation dialog; if dismissed, does NOT trigger API call", async () => {
    vi.mocked(api.get).mockResolvedValueOnce(mockEmployees);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false); // Dismiss

    render(<Employees />);

    await waitFor(() => {
      expect(screen.getAllByTestId("employee-row")).toHaveLength(2);
    });

    const forgetBtn = screen.getByTestId("forget-button");
    fireEvent.click(forgetBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("triggers right-to-be-forgotten API call when confirmation dialog is accepted", async () => {
    vi.mocked(api.get).mockResolvedValue(mockEmployees);
    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(true); // Accept

    render(<Employees />);

    await waitFor(() => {
      expect(screen.getAllByTestId("employee-row")).toHaveLength(2);
    });

    const forgetBtn = screen.getByTestId("forget-button");
    fireEvent.click(forgetBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith("/offboarding/emp-terminated/forget");
  });
});
