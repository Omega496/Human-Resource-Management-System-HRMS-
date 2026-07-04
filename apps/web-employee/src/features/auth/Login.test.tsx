import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi, describe, it, expect, beforeEach } from "vitest";
import { Login } from "./Login";
import { api, setAccessToken } from "../../api/client";

// Mock the axios client and token helpers
vi.mock("../../api/client", () => {
  return {
    api: {
      post: vi.fn(),
    },
    setAccessToken: vi.fn(),
    getAccessToken: vi.fn(),
  };
});

describe("Login Feature", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  const renderLogin = () => {
    return render(
      <MemoryRouter initialEntries={["/login"]}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/dashboard" element={<div data-testid="dashboard">Dashboard Page</div>} />
        </Routes>
      </MemoryRouter>
    );
  };

  it("renders email and password inputs and the submit button", () => {
    renderLogin();

    expect(screen.getByLabelText(/email address/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument();
  });

  it("submits the credentials, stores the token, and redirects to the dashboard on success", async () => {
    const mockToken = "mock-access-token-123";
    vi.mocked(api.post).mockResolvedValueOnce({
      data: {
        access_token: mockToken,
        token_type: "bearer",
      },
    });

    renderLogin();

    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitBtn = screen.getByRole("button", { name: /sign in/i });

    // Submit button should be disabled initially
    expect(submitBtn).toBeDisabled();

    fireEvent.change(emailInput, { target: { value: "test@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "password123" } });

    // Should be enabled now
    expect(submitBtn).not.toBeDisabled();

    fireEvent.click(submitBtn);

    expect(api.post).toHaveBeenCalledWith("/auth/login", {
      email: "test@example.com",
      password: "password123",
    });

    await waitFor(() => {
      expect(setAccessToken).toHaveBeenCalledWith(mockToken);
      expect(screen.getByTestId("dashboard")).toBeInTheDocument();
    });
  });

  it("shows an error message when login fails", async () => {
    const errorMessage = "Invalid email or password";
    vi.mocked(api.post).mockRejectedValueOnce({
      response: {
        data: {
          detail: errorMessage,
        },
      },
    });

    renderLogin();

    const emailInput = screen.getByLabelText(/email address/i);
    const passwordInput = screen.getByLabelText(/password/i);
    const submitBtn = screen.getByRole("button", { name: /sign in/i });

    fireEvent.change(emailInput, { target: { value: "wrong@example.com" } });
    fireEvent.change(passwordInput, { target: { value: "wrongpass" } });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      const errorDiv = screen.getByRole("alert");
      expect(errorDiv).toBeInTheDocument();
      expect(errorDiv).toHaveTextContent(errorMessage);
    });
  });
});
