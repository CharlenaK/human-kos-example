import { ALL_FACETS, FACET_LABELS, type FacetCandidate, type FacetType, type LicenseBoundary, kosApi } from "./api";

export interface WorkbenchCallbacks {
  onFocusNodeOnMap: (node: { node_id: string; map_x: number; map_y: number; facet_type: FacetType; label: string }) => void;
  onComplianceUpdate: (boundary: LicenseBoundary) => void;
  onToast: (msg: string) => void;
}

export function initWorkbench(cb: WorkbenchCallbacks): { refresh: () => Promise<void> } {
  const titleInput = document.getElementById("attach-title") as HTMLInputElement;
  const textInput = document.getElementById("attach-text") as HTMLTextAreaElement;
  const proposeBtn = document.getElementById("btn-propose-attach") as HTMLButtonElement;
  const confirmBtn = document.getElementById("btn-confirm-attach") as HTMLButtonElement;
  const proposalBox = document.getElementById("attach-proposal-box") as HTMLElement;

  const serendipityBtn = document.getElementById("btn-run-serendipity") as HTMLButtonElement;
  const serendipityOut = document.getElementById("serendipity-output") as HTMLElement;

  const refreshBtn = document.getElementById("btn-refresh-bridge") as HTMLButtonElement;
  const collectionsOut = document.getElementById("collections-output") as HTMLElement;
  const sessionsOut = document.getElementById("sessions-output") as HTMLElement;

  const cherryPathInput = document.getElementById("cherry-path-input") as HTMLInputElement;
  const cherryDryRun = document.getElementById("cherry-dryrun-check") as HTMLInputElement;
  const cherryBtn = document.getElementById("btn-import-cherry") as HTMLButtonElement;
  const cherryOut = document.getElementById("cherry-import-output") as HTMLElement;

  const selectedBindings = new Map<string, { facet_type: FacetType; node_id: string; pack_id: string; confidence: number }>();

  function syncConfirmBtn(): void {
    confirmBtn.disabled = selectedBindings.size === 0;
  }

  function renderProposal(byFacet: Record<FacetType, FacetCandidate[]>): void {
    selectedBindings.clear();
    syncConfirmBtn();
    proposalBox.innerHTML = "";

    for (const facet of ALL_FACETS) {
      const cands = byFacet[facet] || [];
      const group = document.createElement("div");
      group.className = "kos-facet-group";

      const head = document.createElement("div");
      head.className = "kos-facet-group-title";
      head.innerHTML = `<span class="kos-swatch" data-facet="${facet}"></span><span>${FACET_LABELS[facet]} (${cands.length})</span>`;
      group.appendChild(head);

      if (cands.length === 0) {
        const empty = document.createElement("div");
        empty.className = "kos-row-meta";
        empty.textContent = "该分面暂无匹配候选。";
        group.appendChild(empty);
      } else {
        for (const c of cands) {
          const row = document.createElement("label");
          row.className = "kos-inner-row";

          const left = document.createElement("div");
          left.className = "kos-inner-row-main";
          const lbl = c.canonical_label_zh || c.canonical_label_en || c.node_id;
          left.innerHTML = `
            <span class="kos-row-label">${escapeHtml(lbl)}</span>
            <span class="kos-row-meta">${escapeHtml(c.breadcrumb_path)}</span>
            <span class="kos-code-id">${escapeHtml(c.node_id)} · IC ${c.info_content.toFixed(2)} · ${escapeHtml(c.license_spdx)}</span>
          `;

          const chk = document.createElement("input");
          chk.type = "checkbox";
          chk.addEventListener("change", () => {
            const key = `${facet}:${c.node_id}`;
            if (chk.checked) {
              selectedBindings.set(key, {
                facet_type: facet,
                node_id: c.node_id,
                pack_id: c.pack_id || "core",
                confidence: Math.min(1, Math.max(0.5, c.fused_score * 25 + 0.5)),
              });
            } else {
              selectedBindings.delete(key);
            }
            syncConfirmBtn();
          });

          row.appendChild(left);
          row.appendChild(chk);
          group.appendChild(row);
        }
      }
      proposalBox.appendChild(group);
    }
  }

  proposeBtn.addEventListener("click", async () => {
    const query = `${titleInput.value} ${textInput.value}`.trim();
    if (!query) {
      cb.onToast("请输入会话标题或内容后再生成五维候选。");
      return;
    }
    proposeBtn.disabled = true;
    proposeBtn.textContent = "检索五维候选中…";
    try {
      const prop = await kosApi.proposeAttach(query, "hybrid");
      renderProposal(prop.candidates_by_facet);
      cb.onComplianceUpdate(prop.license_boundary);
      cb.onToast("已生成五维隔离候选池，请勾选后确认挂载。");
    } catch (err) {
      cb.onToast(`生成候选失败：${String(err)}`);
    } finally {
      proposeBtn.disabled = false;
      proposeBtn.textContent = "生成五维候选";
    }
  });

  confirmBtn.addEventListener("click", async () => {
    if (selectedBindings.size === 0) return;
    confirmBtn.disabled = true;
    try {
      const title = titleInput.value.trim() || "未命名探索会话";
      const content = textInput.value.trim() || title;
      const res = await kosApi.confirmAttach({
        session: {
          source_client: "kos_workbench",
          external_session_id: `wb-${Date.now()}`,
          title,
          content_text: content,
        },
        bindings: Array.from(selectedBindings.values()),
      });
      cb.onComplianceUpdate(res.license_boundary);
      cb.onToast(`已挂载 ${res.applied_bindings.length} 个五维锚点至 DB III（${res.session.session_uid}）。`);
      await refreshBridge();
    } catch (err) {
      cb.onToast(`挂载失败：${String(err)}`);
    } finally {
      syncConfirmBtn();
    }
  });

  serendipityBtn.addEventListener("click", async () => {
    serendipityBtn.disabled = true;
    try {
      const brf = await kosApi.runSerendipity();
      cb.onComplianceUpdate(brf.license_boundary);
      serendipityOut.innerHTML = "";
      if (brf.items.length === 0) {
        serendipityOut.innerHTML = `<div class="kos-row-meta">当前 DB III 尚无种子映射，请先完成一次 /attach 挂载。</div>`;
      } else {
        for (const it of brf.items) {
          const row = document.createElement("div");
          row.className = "kos-inner-row";
          row.innerHTML = `
            <div class="kos-inner-row-main">
              <div class="kos-drawer-eyebrow">
                <span class="kos-swatch" data-facet="${it.target_facet_type}"></span>
                <span class="kos-row-label">${escapeHtml(it.target_label)}</span>
                <span class="kos-badge-neutral">score ${it.score.toFixed(2)}</span>
                <span class="kos-badge-neutral">UCB +${it.ucb_bonus.toFixed(2)}</span>
              </div>
              <span class="kos-row-meta">${escapeHtml(it.rationale)}</span>
              <span class="kos-code-id">${escapeHtml(it.target_breadcrumb)} · ${escapeHtml(it.license_spdx)}</span>
            </div>
          `;
          row.addEventListener("click", () => {
            cb.onFocusNodeOnMap({
              node_id: it.target_node_id,
              map_x: it.map_x,
              map_y: it.map_y,
              facet_type: it.target_facet_type,
              label: it.target_label,
            });
          });
          serendipityOut.appendChild(row);
        }
      }
      cb.onToast(`已生成受控漫游简报（${brf.items.length} 条拓扑推荐）。`);
    } catch (err) {
      cb.onToast(`简报生成失败：${String(err)}`);
    } finally {
      serendipityBtn.disabled = false;
    }
  });

  async function refreshBridge(): Promise<void> {
    try {
      const [cols, sessions] = await Promise.all([kosApi.getCollections(), kosApi.getSessions()]);
      collectionsOut.innerHTML = "";
      if (cols.length === 0) {
        collectionsOut.innerHTML = `<div class="kos-row-meta">暂无动态专题集合。</div>`;
      } else {
        for (const col of cols) {
          const el = document.createElement("div");
          el.className = "kos-inner-row";
          el.innerHTML = `
            <div class="kos-inner-row-main">
              <div class="kos-drawer-eyebrow">
                <span class="kos-swatch" data-facet="${col.facet_type}"></span>
                <span class="kos-row-label">${escapeHtml(col.anchor_label)}</span>
                <span class="kos-badge-neutral">${col.session_count} 会话</span>
              </div>
              <span class="kos-code-id">${escapeHtml(col.anchor_node_id)} · 有效激活 ${col.effective_activation.toFixed(2)}</span>
            </div>
            <span class="kos-heat-cell" title="有效激活度"></span>
          `;
          collectionsOut.appendChild(el);
        }
      }

      sessionsOut.innerHTML = "";
      if (sessions.length === 0) {
        sessionsOut.innerHTML = `<div class="kos-row-meta">DB III 当前为干净状态（0 条会话）。</div>`;
      } else {
        for (const s of sessions) {
          const el = document.createElement("div");
          el.className = "kos-inner-row";
          const tags = s.mappings
            .map((m) => `<span class="kos-badge-neutral">${escapeHtml(m.facet_type)}: ${escapeHtml(m.canonical_label)}</span>`)
            .join(" ");
          el.innerHTML = `
            <div class="kos-inner-row-main">
              <span class="kos-row-label">${escapeHtml(s.title)}</span>
              <span class="kos-code-id">${escapeHtml(s.source_client)} · ${escapeHtml(s.session_uid)}</span>
              <div class="kos-hud-row">${tags || '<span class="kos-row-meta">尚未挂载分面</span>'}</div>
            </div>
          `;
          sessionsOut.appendChild(el);
        }
      }
    } catch (err) {
      cb.onToast(`刷新账本失败：${String(err)}`);
    }
  }

  refreshBtn.addEventListener("click", () => void refreshBridge());

  cherryBtn.addEventListener("click", async () => {
    const path = cherryPathInput.value.trim();
    if (!path) {
      cb.onToast("请先显式填写备份文件路径；工具不会自动扫描本机目录。");
      return;
    }
    cherryBtn.disabled = true;
    try {
      const res = await kosApi.importCherry(path, cherryDryRun.checked);
      cherryOut.innerHTML = `
        <div class="kos-inner-row">
          <div class="kos-inner-row-main">
            <span class="kos-row-label">${res.dry_run ? "Dry-Run 预览结果" : "导入完成"}（共 ${res.total_seen} 条）</span>
            <span class="kos-row-meta">新增 ${res.inserted_count} · 更新 ${res.updated_count} · 跳过重复 ${res.skipped_count} · 密钥过滤 ${res.private_filtered_count}</span>
            <span class="kos-code-id">receipt: ${escapeHtml(res.receipt_id)}</span>
          </div>
        </div>
      `;
      if (!res.dry_run) {
        await refreshBridge();
      }
      cb.onToast(res.dry_run ? "Cherry Studio Dry-Run 预览完成。" : "Cherry Studio 备份导入完成。");
    } catch (err) {
      cb.onToast(`导入失败：${String(err)}`);
    } finally {
      cherryBtn.disabled = false;
    }
  });

  return { refresh: refreshBridge };
}

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
