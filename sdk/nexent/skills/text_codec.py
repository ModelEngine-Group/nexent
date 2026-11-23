"""Strict text decoding shared by skill uploads, previews and the loader."""

from charset_normalizer import from_bytes


class DecodedSkillFile(str):
    """String content carrying the source character encoding."""

    encoding: str

    def __new__(cls, content: str, encoding: str):
        value = super().__new__(cls, content)
        value.encoding = encoding
        return value


def decode_skill_text(raw: bytes) -> DecodedSkillFile:
    """Decode text bytes without silently replacing undecodable characters."""
    if raw.startswith(b"\xef\xbb\xbf"):
        return DecodedSkillFile(raw.decode("utf-8-sig"), "utf-8-sig")
    if raw.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return DecodedSkillFile(raw.decode("utf-32"), "utf-32")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return DecodedSkillFile(raw.decode("utf-16"), "utf-16")
    if raw and raw.count(b"\x00") / len(raw) > 0.2:
        even_nuls = raw[0::2].count(0)
        odd_nuls = raw[1::2].count(0)
        if odd_nuls > len(raw) / 4:
            return DecodedSkillFile(raw.decode("utf-16-le"), "utf-16-le")
        if even_nuls > len(raw) / 4:
            return DecodedSkillFile(raw.decode("utf-16-be"), "utf-16-be")

    try:
        return DecodedSkillFile(raw.decode("utf-8"), "utf-8")
    except UnicodeDecodeError:
        pass

    for encoding in ("gb18030", "big5"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if any("\u3400" <= char <= "\u9fff" for char in decoded):
            return DecodedSkillFile(decoded, encoding)

    match = from_bytes(raw).best()
    if match is None or match.encoding is None or match.chaos > 0.3:
        raise UnicodeDecodeError("unknown", raw, 0, len(raw), "Unable to detect a reliable text encoding")
    return DecodedSkillFile(str(match), match.encoding.lower())
