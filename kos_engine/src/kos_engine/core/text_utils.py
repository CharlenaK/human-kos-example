"""Text normalization and CJK/English FTS5 query construction.

Standalone copy aligned with L1 kos_fts tokenization (`porter unicode61 remove_diacritics 2`
plus pre-tokenized CJK n-grams in `cjk_tokens`), with zero dependency on `kos_build`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

_WS_RE = re.compile(r"\s+")
_CJK_RUN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")
_NON_ALNUM_CJK_RE = re.compile(r"[^\w\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]+")

_BASIC_T2S = str.maketrans(
    {
        "學": "学",
        "歷": "历",
        "經": "经",
        "濟": "济",
        "計": "计",
        "機": "机",
        "軟": "软",
        "體": "体",
        "網": "网",
        "絡": "络",
        "資": "资",
        "庫": "库",
        "語": "语",
        "藝": "艺",
        "術": "术",
        "醫": "医",
        "藥": "药",
        "顯": "显",
        "廣": "广",
        "漢": "汉",
        "譯": "译",
        "傳": "传",
        "統": "统",
        "圖": "图",
        "譜": "谱",
        "論": "论",
        "證": "证",
        "實": "实",
        "驗": "验",
        "職": "职",
        "業": "业",
        "類": "类",
        "別": "别",
        "開": "开",
        "發": "发",
        "測": "测",
        "試": "试",
        "調": "调",
    }
)

_CJK_FUNC_CHARS = set("的和与了在是我你他它中对把将用从做怎何么呢吗吧啊哪谁其及并或而于以之为着过被让向给")


def normalize_text(text: str) -> str:
    s = unicodedata.normalize("NFKC", text or "").strip().lower()
    s = s.translate(_BASIC_T2S)
    return _WS_RE.sub(" ", s)


def contains_cjk(text: str) -> bool:
    return bool(text and _CJK_RUN_RE.search(text))


def extract_cjk_terms(text: str, max_terms: int = 8) -> List[str]:
    norm = unicodedata.normalize("NFKC", text or "").strip().translate(_BASIC_T2S)
    terms: List[str] = []
    seen = set()
    for raw_run in _CJK_RUN_RE.findall(norm):
        sub_runs: List[str] = []
        buf: List[str] = []
        for ch in raw_run:
            if ch in _CJK_FUNC_CHARS:
                if buf:
                    sub_runs.append("".join(buf))
                    buf = []
            else:
                buf.append(ch)
        if buf:
            sub_runs.append("".join(buf))

        for run in sub_runs:
            n = len(run)
            if n == 0:
                continue
            if n <= 4:
                if run not in seen:
                    seen.add(run)
                    terms.append(run)
                if n >= 3:
                    for i in range(n - 1):
                        bg = run[i : i + 2]
                        if bg not in seen:
                            seen.add(bg)
                            terms.append(bg)
            else:
                for i in range(0, n - 1, 2):
                    bg = run[i : i + 2]
                    if bg not in seen:
                        seen.add(bg)
                        terms.append(bg)
                if n % 2 == 1:
                    bg = run[n - 2 : n]
                    if bg not in seen:
                        seen.add(bg)
                        terms.append(bg)
    return terms[:max_terms]


def build_fts5_query(user_query: str, facet_type: str | None = None, max_terms: int = 12) -> str:
    """Convert a raw Chinese/English prompt into a safe FTS5 MATCH expression."""
    norm = unicodedata.normalize("NFKC", user_query or "").strip().translate(_BASIC_T2S)
    terms: List[str] = []
    seen = set()

    for cjk in extract_cjk_terms(norm, max_terms=max_terms):
        safe = cjk.replace('"', "")
        if safe and safe not in seen:
            seen.add(safe)
            terms.append(f'"{safe}"')

    ascii_part = _CJK_RUN_RE.sub(" ", norm)
    for tok in _NON_ALNUM_CJK_RE.split(ascii_part):
        tok = tok.strip().lower().replace('"', "")
        if len(tok) >= 2 and tok not in seen:
            seen.add(tok)
            terms.append(f'"{tok}"')

    if not terms:
        return ""
    body = " OR ".join(terms[:max_terms])
    if facet_type:
        return f'facet_type : "{facet_type}" AND ({body})'
    return body
