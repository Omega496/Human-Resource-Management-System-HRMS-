import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Login } from "./Login";
import { api } from "../../api/client";

vi.mock("../../api/client", () => {
  return {
    api: {
      post: vi.fn(),
    },
    setAccessToken: vi.fn(),
  };
});

describe("Admin Login Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("renders login inputs and submits credentials successfully", async () => {
    const onLoginSuccess = vi.fn();
    vi.mocked(api.post).mockResolvedValueOnce({
      data: { access_token: "mock-jwt-token" },
    });

    render(<Login onLoginSuccess={onLoginSuccess} />);

    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitBtn = screen.getByRole("button", { name: /sign in/i });

    fireEvent.change(emailInput, { target: { value: "admin@company.com" } });
    fireEvent.change(passwordInput, { target: { value: "secret123" } });
    fireEvent.click(submitBtn);

    expect(api.post).toHaveBeenCalledWith("/auth/login", {
      email: "admin@company.com",
      password: "secret123",
    });

    await waitFor(() => {
      expect(onLoginSuccess).toHaveBeenCalled();
    });
  });

  it("displays an error message when API call fails", async () => {
    const onLoginSuccess = vi.fn();
    vi.mocked(api.post).mockRejectedValueOnce({
      response: { data: { detail: "Invalid credentials" } },
    });

    render(<Login onLoginSuccess={onLoginSuccess} />);

    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitBtn = screen.getByRole("button", { name: /sign in/i });

    fireEvent.change(emailInput, { target: { value: "admin@company.com" } });
    fireEvent.change(passwordInput, { target: { value: "wrong" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(screen.getByText("Invalid credentials")).toBeInTheDocument();
      expect(onLoginSuccess).not.toHaveBeenCalled();
    });
  });
});
