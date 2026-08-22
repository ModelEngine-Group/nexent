export async function copyToClipboard(text: string): Promise<void> {
  // Normalize line breaks: trim blank lines at the start/end and collapse >2 line breaks
  const normalizedText = text
    .replace(/^\n+|\n+$/g, '')
    .replace(/\n{3,}/g, '\n\n');

  // Prefer modern Clipboard API when available & permitted
  if (typeof navigator !== 'undefined' && navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(normalizedText);
      return;
    } catch (error) {
      // Continue to fallback approach if Clipboard API is unavailable or permission is denied
    }
  }

  // Fallback: use a hidden textarea + execCommand
  return new Promise<void>((resolve, reject) => {
    try {
      const textArea = document.createElement('textarea');
      textArea.value = normalizedText;
      textArea.style.position = 'fixed';
      textArea.style.left = '-9999px';
      textArea.style.top = '0';
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();

      const successful = document.execCommand('copy');
      document.body.removeChild(textArea);

      if (successful) {
        resolve();
      } else {
        reject(new Error('execCommand failed'));
      }
    } catch (err) {
      reject(err instanceof Error ? err : new Error(String(err)));
    }
  });
}