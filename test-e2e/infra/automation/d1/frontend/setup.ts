import "@testing-library/jest-dom/vitest";
import { beforeEach, vi } from "vitest";

// Historical generated tests used Jest's global name. Vitest implements the
// same mock API; expose the alias so those tests share one deterministic
// runner instead of importing node:test or requiring Jest.
Object.assign(globalThis, { jest: vi });

function installBrowserMocks() {
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    writable: true,
    value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
    }),
  });
}

installBrowserMocks();
beforeEach(installBrowserMocks);

class TestResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.assign(globalThis, { ResizeObserver: TestResizeObserver });
