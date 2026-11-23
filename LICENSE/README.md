# Licenses & Attribution Guide

This folder centralizes all license texts, design/architecture attributions, and third-party notices for **Human KOS Example**.

| File | Scope |
| :--- | :--- |
| [`MIT.txt`](./MIT.txt) | License for all original source code, scripts, and documentation in this repository |
| [`NOTICE.md`](./NOTICE.md) | Credits and license boundaries for inspired design systems, referenced projects, core open-source dependencies, and upstream Human KOS open data |

## Key Compliance Boundaries

1. **Zero Client Redistribution**: `adapters/open_webui/` contains only thin external integration glue (Filter/Action Python scripts and JSON configs). Zero lines of Open WebUI source code are copied, modified, or redistributed here.
2. **Read-Only L1 Data Separation**: This repository ships **no** prebuilt `.sqlite` data files. Users obtain `human_kos_core.sqlite` and optional extension packs directly from [`CharlenaK/human-kos`](https://github.com/CharlenaK/human-kos). When ShareAlike packs (`cn_rel`, `unesco`, `dila`, `edam`, `iscedf`) are mounted at runtime, `kos-engine` surfaces mandatory `CC BY-SA` notices automatically.
3. **Design System Attribution**: Our visual specification in `docs/design-rules/` was adapted with gratitude from the governance and visual rules of the [Cindy Design System](https://github.com/makecindy/cindy/blob/main/docs/design-rules/cindy-design-system.md); see [`NOTICE.md`](./NOTICE.md).
