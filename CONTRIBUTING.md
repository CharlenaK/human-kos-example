# Contributing to Human KOS Example

Thank you for your interest in contributing to **Human KOS Example**! Whether you are fixing a small visual quirk, adding a thin adapter for a new AI chat client, or improving documentation, your help is warmly appreciated.

---

## Ways to Contribute

- **Report bugs or UX friction**: Open an Issue with clear reproduction steps (for map camera/viewport issues, you can run `await window.__KOS_DIAG__.runFullSuite()` in your browser DevTools console and paste the JSON summary).
- **Add a thin client adapter**: Build a zero-fork connector under `adapters/<client_name>/` talking to `kos-engine` over standard HTTP or MCP — without duplicating L2 retrieval or DB III logic.
- **Improve the 2D Knowledge World Map & Workbench**: Enhance accessibility, keyboard navigation, localization, or performance while keeping the single-file bundle under 5 MB with zero external CDN requests.
- **Improve guides & translations**: Help keep the README clear, approachable, and jargon-free for everyday users.

---

## Architecture & Boundary Rules

Please keep these core principles intact:

1. **L1 Atlas stays strictly read-only**: Never modify `human_kos_core.sqlite` or `human_kos_ext/*.sqlite`, and never add client-specific columns to L1.
2. **Three-database separation**: Keep personal mappings inside DB III (`personal_bridge.sqlite`), completely separate from L1 and never committed to Git.
3. **Zero client forks**: Adapters should integrate via official extension hooks (MCP, plugins, functions, automations) without copying or modifying third-party client source code.
4. **No unsolicited local scanning**: Session importers must require an explicit user-supplied file path and default to dry-run preview mode.
5. **Respect license boundaries**: Preserve all ShareAlike (`CC BY-SA`) runtime notices and attribution credits in `LICENSE/NOTICE.md`.

---

## Local Development Workflow

### 1. Backend & Contract Tests (Python 3.11+)

```bash
cd kos_engine
uv sync --extra dev
uv run pytest tests/ ../adapters/open_webui/tests/ -v
```

### 2. Frontend & Design System Guard (Node 20+ / pnpm)

When modifying UI colors, radii, typography, or layout:

1. Read [`docs/design-rules/DESIGN.md`](./docs/design-rules/DESIGN.md) first.
2. Edit numeric values only in [`docs/design-rules/tokens.dtcg.json`](./docs/design-rules/tokens.dtcg.json), then regenerate CSS:
   ```bash
   python docs/design-rules/tokens_guard.py --generate --check
   ```
3. Rebuild the self-contained single-file map bundle:
   ```bash
   cd kos_engine/web
   pnpm install
   pnpm build
   ```
4. Verify both **Light** and **Dark** modes in a browser and confirm `tokens_guard.py --check` reports `0 violations`.

### 3. Pull Request Checklist

- [ ] No personal data, `.sqlite` files, credentials, or local machine paths included.
- [ ] `python docs/design-rules/tokens_guard.py --check` passes with 0 violations.
- [ ] `uv run pytest tests/ ../adapters/open_webui/tests/` passes.
- [ ] Any new third-party dependency or visual reference is credited in [`LICENSE/NOTICE.md`](./LICENSE/NOTICE.md).
