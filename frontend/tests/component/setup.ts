import { afterEach, expect, vi } from "vitest";
import { cleanup } from "@testing-library/react";

afterEach(cleanup);

expect.extend({
  toBeInTheDocument(received: Element | null) {
    const pass = Boolean(
      received && document.documentElement.contains(received)
    );
    return {
      pass,
      message: () =>
        `expected element ${pass ? "not " : ""}to be in the document`,
    };
  },
  toHaveAttribute(received: Element, name: string, value?: string) {
    const actual = received.getAttribute(name);
    const pass =
      value === undefined ? received.hasAttribute(name) : actual === value;
    return {
      pass,
      message: () =>
        `expected ${name}=${String(actual)} ${pass ? "not " : ""}to equal ${String(value)}`,
    };
  },
  toHaveTextContent(received: Element, value: string) {
    const actual = received.textContent ?? "";
    const pass = actual.includes(value);
    return {
      pass,
      message: () =>
        `expected ${JSON.stringify(actual)} ${pass ? "not " : ""}to contain ${JSON.stringify(value)}`,
    };
  },
});

declare module "vitest" {
  interface Assertion<T> {
    toBeInTheDocument(): void;
    toHaveAttribute(name: string, value?: string): void;
    toHaveTextContent(value: string): void;
  }
}

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverMock,
});

Object.defineProperty(navigator, "clipboard", {
  configurable: true,
  value: { writeText: vi.fn().mockResolvedValue(undefined) },
});

window.HTMLElement.prototype.scrollIntoView = vi.fn();

const getComputedStyle = window.getComputedStyle.bind(window);
window.getComputedStyle = ((element: Element) =>
  getComputedStyle(element)) as typeof window.getComputedStyle;
