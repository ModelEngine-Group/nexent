"""Windows-safe PDF diagnostic (no `unstructured` import, which segfaults here).

Reproduces the text-extraction step that unstructured's `strategy="fast"` runs
internally (pdfminer.six) and prints the REAL exception with full traceback.
unstructured swallows this exception (logger.debug only) and returns an empty
element list, which is why a text-based PDF yields zero chunks with no error.
"""
import io
import traceback

from pypdf import PdfReader
from pdfminer.high_level import extract_text

PDF_PATH = "./3.pdf"

data = open(PDF_PATH, "rb").read()
print(f"file size: {len(data) / 1024 / 1024:.2f} MB")

# --- pypdf: encryption + basic text probe ------------------------------------
reader = PdfReader(io.BytesIO(data))
print(f"pypdf pages: {len(reader.pages)}")
print(f"pypdf is_encrypted: {reader.is_encrypted}")
if reader.is_encrypted:
    try:
        rc = reader.decrypt("")
        print(f"pypdf decrypt('') -> {rc}  (0=fail, 1=user pw, 2=owner pw)")
    except Exception as exc:
        print(f"pypdf decrypt('') raised: {exc!r}")

# pypdf's own text extraction (independent of pdfminer)
pypdf_text = ""
try:
    sample = "\n".join((reader.pages[i].extract_text() or "") for i in range(min(3, len(reader.pages))))
    pypdf_text = sample.strip()
    print(f"pypdf extract_text (first 3 pages) chars: {len(pypdf_text)}")
    if pypdf_text:
        print("  pypdf sample:", repr(pypdf_text[:120]))
except Exception as exc:
    print(f"pypdf extract_text raised: {exc!r}")

# --- pdfminer: the ACTUAL library unstructured's fast path uses --------------
# This is the call whose exception unstructured swallows at
# unstructured/partition/pdf.py:315-317 (logger.debug(e) + info message).
print("\n--- pdfminer.high_level.extract_text ---")
try:
    text = extract_text(io.BytesIO(data))
    print(f"pdfminer extracted chars: {len(text)}")
    if text.strip():
        print("  pdfminer sample:", repr(text[:120]))
    else:
        print("  pdfminer returned EMPTY text (no exception)")
except Exception as exc:
    print(f"!!! pdfminer RAISED: {exc!r}")
    print("----- traceback -----")
    traceback.print_exc()
    print("----------------------")
    print("=> This is the exception unstructured swallows. PDF may be encrypted,")
    print("   copy-protected, or structurally unsupported by pdfminer.six.")
