"""Stable object keys shared by preview creation and source cleanup."""

import hashlib


def build_preview_pdf_object_key(object_name: str, *, temporary: bool = False) -> str:
    """Keep cached and in-progress previews in the existing MinIO namespaces."""
    stem = object_name.rsplit(".", 1)[0] if "." in object_name else object_name
    suffix = hashlib.md5(object_name.encode()).hexdigest()[:8]
    directory = "converting" if temporary else "converted"
    extension = "pdf.tmp" if temporary else "pdf"
    return f"preview/{directory}/{stem}_{suffix}.{extension}"
