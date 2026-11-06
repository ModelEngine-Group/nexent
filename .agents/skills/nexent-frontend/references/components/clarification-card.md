# Clarification card

`frontend/components/interaction/clarification-card.tsx` renders ordinary chat and NL2Agent clarification controls. It owns transient text, selected IDs, other text, submitting/error state and the local successful-submission flag. It performs no requests itself; its caller supplies `onSubmit` and localized labels.

`initialAnswers` and `submitted` initialize a persisted snapshot on mount. A caller loading a different message, unit or submitted snapshot must use a corresponding React key to remount the card. `ClarificationMessageCard` includes these identities in its key. Do not reset unsent input merely because streamed form props receive a new object identity.

Submitted/read-only cards show the original controls disabled. Submitted cards use `submittedLabel`; history alone does not imply submission. A rejected `onSubmit` keeps answers and displays its error, permitting retry. Successful submission locks the current card. Existing NL2Agent callers may omit both optional snapshot props and retain their established behavior.

Input labels use fieldset/legend and accessible labels. The caller localizes title, description, other label, button labels and footer hints. Reuse the existing card shell and input layout; persisted responses do not introduce visual overrides.
