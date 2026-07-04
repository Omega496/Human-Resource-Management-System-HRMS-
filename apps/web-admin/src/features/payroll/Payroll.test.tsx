import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Payroll } from "./Payroll";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

describe("Payroll Feature - confirmation and adjustment gating", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const mockProfile = {
    data: {
      id: "admin-id",
      email: "admin@company.com",
      full_name: "Admin User",
      role: "admin",
      organization_id: "org-123",
    },
  };

  const mockEmployees = {
    data: [
      {
        id: "emp-1",
        full_name: "Test Employee",
        email: "test@company.com",
        status: "active",
      },
    ],
  };

  const mockLedgerLines = {
    data: [
      {
        id: "line-open",
        ledger_month: "2026-07-01",
        line_type: "salary",
        amount_cents: 500000,
        currency: "USD",
        status: "open" as const,
        adjustment_of: null,
        computed_from_rule_id: "rule-1",
        created_at: new Date().toISOString(),
      },
      {
        id: "line-closed",
        ledger_month: "2026-07-01",
        line_type: "bonus",
        amount_cents: 100000,
        currency: "USD",
        status: "closed" as const,
        adjustment_of: null,
        computed_from_rule_id: "rule-2",
        created_at: new Date().toISOString(),
      },
    ],
  };

  it("gates month closure behind confirmation; if dismissed, does NOT trigger API call", async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === "/employees/me") return Promise.resolve(mockProfile);
      if (url === "/employees") return Promise.resolve(mockEmployees);
      if (url === "/payroll/lines") return Promise.resolve(mockLedgerLines);
      return Promise.reject(new Error("Not found"));
    });

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(false); // Dismiss

    render(<Payroll />);

    await waitFor(() => {
      expect(screen.getByTestId("close-month-button")).toBeInTheDocument();
    });

    const closeBtn = screen.getByTestId("close-month-button");
    fireEvent.click(closeBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("calls close-month API when confirmation dialog is accepted", async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === "/employees/me") return Promise.resolve(mockProfile);
      if (url === "/employees") return Promise.resolve(mockEmployees);
      if (url === "/payroll/lines") return Promise.resolve(mockLedgerLines);
      return Promise.reject(new Error("Not found"));
    });
    vi.mocked(api.post).mockResolvedValueOnce({ data: { closed_count: 1 } });

    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValueOnce(true); // Accept

    render(<Payroll />);

    await waitFor(() => {
      expect(screen.getByTestId("close-month-button")).toBeInTheDocument();
    });

    const closeBtn = screen.getByTestId("close-month-button");
    fireEvent.click(closeBtn);

    expect(confirmSpy).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith("/payroll/close-month", {
      organization_id: "org-123",
      ledger_month: expect.stringMatching(/^\d{4}-\d{2}-01$/),
    });
  });

  it("gates record adjustment behind prompt; if cancelled (null), does NOT trigger API call", async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === "/employees/me") return Promise.resolve(mockProfile);
      if (url === "/employees") return Promise.resolve(mockEmployees);
      if (url === "/payroll/lines") return Promise.resolve(mockLedgerLines);
      return Promise.reject(new Error("Not found"));
    });

    const promptSpy = vi.spyOn(window, "prompt").mockReturnValueOnce(null); // Cancel

    render(<Payroll />);

    await waitFor(() => {
      expect(screen.getByTestId("adjust-button")).toBeInTheDocument();
    });

    const adjustBtn = screen.getByTestId("adjust-button");
    fireEvent.click(adjustBtn);

    expect(promptSpy).toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  it("calls adjustments API when prompt is submitted with valid reason", async () => {
    vi.mocked(api.get).mockImplementation((url) => {
      if (url === "/employees/me") return Promise.resolve(mockProfile);
      if (url === "/employees") return Promise.resolve(mockEmployees);
      if (url === "/payroll/lines") return Promise.resolve(mockLedgerLines);
      return Promise.reject(new Error("Not found"));
    });
    vi.mocked(api.post).mockResolvedValueOnce({ data: {} });

    const promptSpy = vi.spyOn(window, "prompt").mockReturnValueOnce("Correction of overpayment"); // Submit

    render(<Payroll />);

    await waitFor(() => {
      expect(screen.getByTestId("adjust-button")).toBeInTheDocument();
    });

    const adjustBtn = screen.getByTestId("adjust-button");
    fireEvent.click(adjustBtn);

    expect(promptSpy).toHaveBeenCalled();
    expect(api.post).toHaveBeenCalledWith("/payroll/adjustments", {
      original_line_id: "line-closed",
      reason: "Correction of overpayment",
    });
  });
});
