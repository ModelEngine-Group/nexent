'''D5 security regression for retrieval_highlight_terms XSS / regex escaping.

Checks the security contract of the source-card highlight and hover preview
using the shipped product sources (read-only).'''

from __future__ import annotations

import pytest

from shared.config import repo_root

CASE_ID = 'SEC-AUTO-926FF16475B223A7'
BACKSLASH = chr(92)

JS_REGEX_METACHARS = {
    BACKSLASH,
    '^',
    '$',
    '.',
    '|',
    '?',
    '*',
    '+',
    '(',
    ')',
    '[',
    ']',
    '{',
    '}',
}

EXPECTED_ALLOWED_TAGS = {
    'p',
    'br',
    'strong',
    'b',
    'em',
    'i',
    'table',
    'thead',
    'tbody',
    'tr',
    'th',
    'td',
}


def _read(rel_path: str) -> str:
    path = repo_root() / rel_path
    assert path.is_file(), 'product source missing: {0}'.format(path)
    return path.read_text(encoding='utf-8')


def _find_all(text: str, needle: str):
    start = 0
    while True:
        pos = text.find(needle, start)
        if pos == -1:
            return
        yield pos
        start = pos + 1


def _char_class_members(class_src: str) -> set[str]:
    members: set[str] = set()
    index = 0
    while index < len(class_src):
        if class_src[index] == BACKSLASH and index + 1 < len(class_src):
            members.add(class_src[index + 1])
            index += 2
        else:
            members.add(class_src[index])
            index += 1
    return members


def _escape_reg_exp_class(citation_src: str) -> str:
    start = citation_src.index('escapeRegExp')
    slash = citation_src.index('/', citation_src.index('value.replace(', start))
    close_slash = citation_src.index('/g', slash)
    literal = citation_src[slash:close_slash]
    open_bracket = literal.index('[')
    close_bracket = literal.rindex(']')
    return literal[open_bracket + 1:close_bracket]


def _extract_whitelist(cite_marker_src: str) -> set[str]:
    prefix = 'const allowedTags = new Set(['
    start = cite_marker_src.index(prefix) + len(prefix)
    end = cite_marker_src.index(']);', start)
    tags: set[str] = set()
    for token in cite_marker_src[start:end].split(','):
        name = ''.join(ch for ch in token if ch.isalnum())
        if name:
            tags.add(name)
    return tags


@pytest.mark.case_id(CASE_ID)
@pytest.mark.stage('D5')
def test_retrieval_highlight_terms_xss_and_regex_escaping() -> None:
    citation_src = _read('frontend/lib/citationHighlight.ts')
    highlighted_src = _read('frontend/components/common/highlightedSourceText.tsx')
    cite_marker_src = _read('frontend/app/[locale]/newchat/ui/cite-marker.tsx')
    sources_panel_src = _read('frontend/app/[locale]/newchat/ui/sources-panel.tsx')
    conversation_db_src = _read('backend/database/conversation_db.py')

    persisted_verbatim = False
    for pos in _find_all(conversation_db_src, 'retrieval_highlight_terms'):
        block = conversation_db_src[pos:pos + 200]
        if 'search_data' in block and 'data[' in block:
            persisted_verbatim = True
            break
    assert persisted_verbatim, 'retrieval_highlight_terms must persist verbatim from search_data'

    assert _char_class_members(_escape_reg_exp_class(citation_src)) == JS_REGEX_METACHARS
    escape_index = citation_src.index('escapeRegExp')
    escape_block = citation_src[escape_index:escape_index + 120]
    assert 'replace(' in escape_block
    assert (BACKSLASH + '$&') in escape_block

    matcher_start = highlighted_src.index('const matcher = new RegExp(')
    matcher_end = highlighted_src.index(');', matcher_start)
    matcher_block = highlighted_src[matcher_start:matcher_end]
    assert 'escapeRegExp' in matcher_block
    assert 'normalizeForHighlight' in matcher_block
    assert 'join' in matcher_block
    assert '|' in matcher_block
    assert '<mark' in highlighted_src
    assert '{part}' in highlighted_src
    assert 'dangerouslySetInnerHTML' not in highlighted_src

    assert _extract_whitelist(cite_marker_src) == EXPECTED_ALLOWED_TAGS
    assert 'if (!allowedTags.has(element.tagName.toLowerCase())) return children;' in cite_marker_src
    assert 'template.innerHTML = text' in cite_marker_src
    assert 'renderSafeHtml(child' in cite_marker_src
    assert '.attributes' not in cite_marker_src
    assert 'getAttribute' not in cite_marker_src
    assert 'setAttribute' not in cite_marker_src
    assert 'dangerouslySetInnerHTML' not in cite_marker_src

    assert 'retrievalHighlightTerms' in sources_panel_src
    assert '(item.retrievalHighlightTerms || [])' in sources_panel_src
    assert 'mergeHighlightTerms(' in sources_panel_src
    assert 'terms={highlightTerms}' in sources_panel_src
    assert 'dangerouslySetInnerHTML' not in sources_panel_src
