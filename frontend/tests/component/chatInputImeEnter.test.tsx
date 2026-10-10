import React from "react";
import { createEvent, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatInput } from "../../app/[locale]/chat/components/chatInput";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));
vi.mock("@/hooks/useConfig", () => ({
  useConfig: () => ({
    appConfig: {},
    getAppAvatarUrl: () => "",
    modelConfig: {},
  }),
}));
vi.mock("@/services/conversationService", () => ({
  conversationService: {},
}));
vi.mock("@/components/common/filePreviewDrawer", () => ({
  FilePreviewDrawer: () => null,
}));
vi.mock("@/components/common/tokenUsageIndicator", () => ({
  TokenUsageIndicator: () => null,
}));
vi.mock("../../app/[locale]/chat/components/chatAgentSelector", () => ({
  ChatAgentSelector: () => null,
}));
vi.mock("../../app/[locale]/chat/components/chatModelSelector", () => ({
  ChatModelSelector: () => null,
}));

function renderChatInput() {
  const onKeyDown = vi.fn();
  render(
    <ChatInput
      input="hello"
      isLoading={false}
      onInputChange={vi.fn()}
      onSend={vi.fn()}
      onStop={vi.fn()}
      onKeyDown={onKeyDown}
      selectedAgentId="1"
    />
  );
  return { onKeyDown, textarea: screen.getByRole("textbox") };
}

describe("ChatInput Enter key with IME composition", () => {
  it("sends on a plain Enter", () => {
    const { onKeyDown, textarea } = renderChatInput();
    fireEvent.keyDown(textarea, { key: "Enter" });
    expect(onKeyDown).toHaveBeenCalledTimes(1);
  });

  it("does not send on Shift+Enter", () => {
    const { onKeyDown, textarea } = renderChatInput();
    fireEvent.keyDown(textarea, { key: "Enter", shiftKey: true });
    expect(onKeyDown).not.toHaveBeenCalled();
  });

  it.each([
    ["isComposing", { isComposing: true }],
    // Safari fires compositionend before keydown, so only keyCode 229 is set.
    ["keyCode 229", { keyCode: 229 }],
  ])(
    "does not send or cancel the keydown when Enter confirms an IME composition (%s)",
    (_, init) => {
      const { onKeyDown, textarea } = renderChatInput();
      const event = createEvent.keyDown(textarea, {
        key: "Enter",
        cancelable: true,
        ...init,
      });
      fireEvent(textarea, event);

      expect(onKeyDown).not.toHaveBeenCalled();
      // preventDefault() would stop the browser from confirming the IME conversion.
      expect(event.defaultPrevented).toBe(false);

      // The Enter that follows the confirmation is a normal Enter and sends once.
      const sendEvent = createEvent.keyDown(textarea, {
        key: "Enter",
        cancelable: true,
      });
      fireEvent(textarea, sendEvent);

      expect(onKeyDown).toHaveBeenCalledTimes(1);
      expect(sendEvent.defaultPrevented).toBe(true);
    }
  );
});
