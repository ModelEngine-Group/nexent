# Inputs

Use ui Input directly for native fields. Use common InputField for shared adornments, clearing, character counting and composition-aware Enter behavior. It forwards the native input value, change event, ID and ref so retained Ant Design Form.Item field registration still works. Use `showCount`, optional `countLimit` and `countStrategy`; native `maxLength` remains independent from display-only counting.

Use common SearchInput for search fields. It composes InputField with a decorative 16px search icon, semantic muted color, 32px default height and clearing enabled by default (disable with `allowClear={false}`). It preserves native input events, refs and composition-aware Enter behavior. Callers supply localized placeholder/accessibility labels and own the value, filtering, debounce and requests. The surrounding page owns width, responsive layout, filters and action buttons; do not encode a half-page width in SearchInput.

Use common Textarea when multiple callers need bounded automatic height (`minRows`/`maxRows`) or counting (`showCount`/`countLimit`). Use ui Textarea directly for a plain native textarea. Common PasswordInput owns visibility toggling and passes native input props through InputField. These controls must not import Ant Design or reproduce its static Input subcomponent API.

HighFidelityTextArea stays in the agents domain: oversized saved content can shrink or remain unchanged without being silently truncated. This domain rule does not belong in the shared Textarea.

StandardInput was only a re-export and has been removed. Do not introduce a second name for the same control.
