import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { App } from "./App";

describe("App scaffolding", () => {
  it("renders the project name", () => {
    render(<App />);
    expect(screen.getByRole("heading", { name: /accounting-parser/i })).toBeInTheDocument();
  });

  it("indicates scaffolding status", () => {
    render(<App />);
    expect(screen.getByText(/scaffolding/i)).toBeInTheDocument();
  });
});
