import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, beforeEach } from "vitest";
import React, { type ReactNode } from "react";
import { ThemeProvider, useTheme } from "../ThemeContext";

function createWrapper() {
  return function Wrapper({ children }: { children: ReactNode }) {
    return <ThemeProvider>{children}</ThemeProvider>;
  };
}

describe("ThemeContext", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.removeAttribute("class");
    document.documentElement.removeAttribute("style");
  });

  it("defaults to light theme when no explicit preference exists", async () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.theme).toBe("light");
      expect(localStorage.getItem("zenstory-theme")).toBe("light");
      expect(document.documentElement.classList.contains("light")).toBe(true);
    });
  });

  it("leaves surface and text colors to the stylesheet in both themes", async () => {
    const { result } = renderHook(() => useTheme(), { wrapper: createWrapper() });
    for (const theme of ["light", "dark"] as const) {
      act(() => result.current.setTheme(theme));
      await waitFor(() => expect(document.documentElement).toHaveClass(theme));
      for (const token of ["--bg-primary", "--bg-secondary", "--text-secondary", "--border-color"]) {
        expect(document.documentElement.style.getPropertyValue(token)).toBe("");
      }
    }
  });

  it("respects explicit saved theme preference", async () => {
    localStorage.setItem("zenstory-theme", "dark");

    const { result } = renderHook(() => useTheme(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.theme).toBe("dark");
      expect(localStorage.getItem("zenstory-theme")).toBe("dark");
      expect(document.documentElement.classList.contains("dark")).toBe(true);
    });
  });

  it("falls back to default accent color when localStorage value is unsupported", async () => {
    localStorage.setItem("zenstory-accent-color", "#invalid");

    const { result } = renderHook(() => useTheme(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(result.current.accentColor).toBe("#4a9eff");
    });
  });

  it("applies and persists the purple accent color", async () => {
    const { result } = renderHook(() => useTheme(), {
      wrapper: createWrapper(),
    });

    act(() => {
      result.current.setAccentColor("#8b5cf6");
    });

    await waitFor(() => {
      expect(result.current.accentColor).toBe("#8b5cf6");
      expect(localStorage.getItem("zenstory-accent-color")).toBe("#8b5cf6");
      expect(document.documentElement.style.getPropertyValue("--accent-primary")).toBe("262 83% 43%");
    });
  });
});
