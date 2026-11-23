"""Design System Token Generator and Static Guard for Human KOS Phase 3.

Single source of truth: docs/design-rules/tokens.dtcg.json
Generated CSS target:   kos_engine/web/src/styles/tokens.css

Usage:
    python docs/design-rules/tokens_guard.py --generate
    python docs/design-rules/tokens_guard.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

ROOT = Path(__file__).resolve().parent.parent.parent
TOKENS_JSON = Path(__file__).resolve().parent / "tokens.dtcg.json"
DEFAULT_SCAN_DIR = ROOT / "kos_engine" / "web" / "src"

_HEX_RE = re.compile(r"#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b")
_RGBA_RE = re.compile(r"\brgba?\s*\(", re.IGNORECASE)
_RADIUS_RE = re.compile(r"border-radius\s*:\s*([^;]+);", re.IGNORECASE)
_PX_VAL_RE = re.compile(r"(\d+(?:\.\d+)?)px")
_ZINDEX_RE = re.compile(r"z-index\s*:\s*(\d+)\s*;", re.IGNORECASE)
_INTRINSIC_MARKER = "design: intrinsic-geometry"


@dataclass(frozen=True)
class GuardViolation:
    path: str
    line: int
    rule: str
    detail: str


def load_tokens(tokens_path: Path = TOKENS_JSON) -> dict:
    return json.loads(tokens_path.read_text(encoding="utf-8"))


def validate_token_source(data: dict) -> List[GuardViolation]:
    violations: List[GuardViolation] = []
    light_keys = set(data["color"]["light"].keys())
    dark_keys = set(data["color"]["dark"].keys())
    if light_keys != dark_keys:
        missing_dark = sorted(light_keys - dark_keys)
        missing_light = sorted(dark_keys - light_keys)
        violations.append(
            GuardViolation(
                path=str(TOKENS_JSON.relative_to(ROOT)),
                line=1,
                rule="dual-mode-parity",
                detail=f"Light/Dark token keys mismatch: missing_dark={missing_dark}, missing_light={missing_light}",
            )
        )
    elev_light = set(data["elevation"]["light"].keys())
    elev_dark = set(data["elevation"]["dark"].keys())
    if elev_light != elev_dark:
        violations.append(
            GuardViolation(
                path=str(TOKENS_JSON.relative_to(ROOT)),
                line=1,
                rule="dual-mode-elevation-parity",
                detail="Light/Dark elevation token keys mismatch",
            )
        )
    return violations


def render_tokens_css(data: dict) -> str:
    lines: List[str] = [
        "/* AUTO-GENERATED FROM docs/design-rules/tokens.dtcg.json — DO NOT EDIT MANUALLY. */",
        "/* Run: python docs/design-rules/tokens_guard.py --generate */",
        "",
        ":root {",
        f"  --kos-font-ui: {data['typography']['font-ui']};",
        f"  --kos-font-code: {data['typography']['font-code']};",
    ]
    for sz in data["typography"]["sizes-px"]:
        lines.append(f"  --kos-text-{sz}: {sz}px;")
    for key, val in data["radius"].items():
        if key == "allowed-px":
            continue
        lines.append(f"  --kos-radius-{key}: {val};")
    for key, val in data["zIndex"].items():
        lines.append(f"  --kos-z-{key}: {val};")
    for key, val in data["motion"].items():
        lines.append(f"  --kos-motion-{key}: {val};")
    lines.append("")
    lines.append("  /* Light mode defaults */")
    for key, val in data["color"]["light"].items():
        lines.append(f"  --kos-{key}: {val};")
    for key, val in data["elevation"]["light"].items():
        lines.append(f"  --kos-{key}: {val};")
    lines.append("}")
    lines.append("")
    lines.append(':root[data-theme="dark"] {')
    for key, val in data["color"]["dark"].items():
        lines.append(f"  --kos-{key}: {val};")
    for key, val in data["elevation"]["dark"].items():
        lines.append(f"  --kos-{key}: {val};")
    lines.append("}")
    lines.append("")
    lines.append("@media (prefers-color-scheme: dark) {")
    lines.append('  :root:not([data-theme="light"]) {')
    for key, val in data["color"]["dark"].items():
        lines.append(f"    --kos-{key}: {val};")
    for key, val in data["elevation"]["dark"].items():
        lines.append(f"    --kos-{key}: {val};")
    lines.append("  }")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def generate_css(tokens_path: Path = TOKENS_JSON) -> Path:
    data = load_tokens(tokens_path)
    issues = validate_token_source(data)
    if issues:
        raise ValueError(f"Invalid token source: {issues}")
    target = ROOT / data["meta"]["generated_css_target"]
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_tokens_css(data), encoding="utf-8", newline="\n")
    return target


def scan_files(paths: Iterable[Path], allowed_radii_px: Sequence[int]) -> List[GuardViolation]:
    allowed_set = set(allowed_radii_px)
    violations: List[GuardViolation] = []
    for path in sorted(paths):
        if path.name == "tokens.css":
            continue
        if path.suffix.lower() not in {".css", ".ts", ".tsx", ".js", ".jsx", ".html"}:
            continue
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        for idx, line in enumerate(lines, start=1):
            prev_line = lines[idx - 2] if idx >= 2 else ""
            if _INTRINSIC_MARKER in line or _INTRINSIC_MARKER in prev_line:
                continue
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
                continue
            for m in _HEX_RE.finditer(line):
                violations.append(
                    GuardViolation(rel, idx, "no-raw-hex", f"Hardcoded hex color '{m.group(0)}' — use a --kos-* token")
                )
            if _RGBA_RE.search(line):
                violations.append(
                    GuardViolation(rel, idx, "no-raw-rgb", "Hardcoded rgb()/rgba() color — use a --kos-* token")
                )
            for m in _RADIUS_RE.finditer(line):
                expr = m.group(1).strip()
                if "var(--kos-radius-" in expr or expr in {"0", "50%"}:
                    continue
                for px_match in _PX_VAL_RE.finditer(expr):
                    val = float(px_match.group(1))
                    if int(val) != val or int(val) not in allowed_set:
                        violations.append(
                            GuardViolation(
                                rel,
                                idx,
                                "radius-whitelist",
                                f"Border radius '{px_match.group(0)}' outside governed scale {sorted(allowed_set)}",
                            )
                        )
            for m in _ZINDEX_RE.finditer(line):
                violations.append(
                    GuardViolation(
                        rel,
                        idx,
                        "zindex-token",
                        f"Raw numeric z-index '{m.group(1)}' — use var(--kos-z-*)",
                    )
                )
    return violations


def run_check(scan_dir: Path = DEFAULT_SCAN_DIR, tokens_path: Path = TOKENS_JSON) -> List[GuardViolation]:
    data = load_tokens(tokens_path)
    violations = validate_token_source(data)
    target = ROOT / data["meta"]["generated_css_target"]
    expected_css = render_tokens_css(data)
    if not target.exists():
        violations.append(
            GuardViolation(
                str(target.relative_to(ROOT)),
                1,
                "tokens-css-missing",
                "Generated tokens.css missing — run tokens_guard.py --generate",
            )
        )
    elif target.read_text(encoding="utf-8") != expected_css:
        violations.append(
            GuardViolation(
                str(target.relative_to(ROOT)),
                1,
                "tokens-css-stale",
                "Generated tokens.css is out of date — run tokens_guard.py --generate",
            )
        )
    if scan_dir.exists():
        files = [p for p in scan_dir.rglob("*") if p.is_file()]
        violations.extend(scan_files(files, data["radius"]["allowed-px"]))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Human KOS Design System token generator & static guard")
    parser.add_argument("--generate", action="store_true", help="Generate tokens.css from tokens.dtcg.json")
    parser.add_argument("--check", action="store_true", help="Validate tokens.dtcg.json, tokens.css freshness, and UI files")
    parser.add_argument("--scan-dir", type=Path, default=DEFAULT_SCAN_DIR, help="UI directory to scan")
    args = parser.parse_args(argv)

    if args.generate:
        out = generate_css()
        print(f"Generated: {out.relative_to(ROOT)}")
    if args.check or not args.generate:
        violations = run_check(scan_dir=args.scan_dir)
        if violations:
            for v in violations:
                print(f"[FAIL] {v.path}:{v.line} ({v.rule}): {v.detail}")
            print(f"Design guard failed with {len(violations)} violation(s).")
            return 1
        print("Design guard PASSED (0 violations; Light/Dark parity verified).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
