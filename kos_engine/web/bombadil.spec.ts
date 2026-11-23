/**
 * Bombadil (v0.8.0) property-based UI specification for Human KOS 2D Knowledge World Map & Workbench.
 *
 * Run on Linux / macOS / WSL (with Chromium & reachable kos-engine origin):
 *   bombadil browser test --headless --time-limit 60s --exit-on-violation http://127.0.0.1:8787/map bombadil.spec.ts
 */

import { always } from "@antithesishq/bombadil";
import { extract } from "@antithesishq/bombadil/browser";
import {
  noConsoleErrors,
  noHttpErrorCodes,
  noUncaughtExceptions,
  noUnhandledPromiseRejections,
} from "@antithesishq/bombadil/browser/defaults/properties";

export {
  noConsoleErrors,
  noHttpErrorCodes,
  noUncaughtExceptions,
  noUnhandledPromiseRejections,
};

const wrappedButtonsCount = extract((state) => {
  const controls = state.document.querySelectorAll(".kos-btn, .kos-tab, .kos-chip-sm, .kos-facet-chip");
  let count = 0;
  for (const el of Array.from(controls)) {
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.height > 36.5) {
      count += 1;
    }
  }
  return count;
});

const collapsedInputsCount = extract((state) => {
  const inputs = state.document.querySelectorAll("input.kos-input-pill");
  let count = 0;
  for (const el of Array.from(inputs)) {
    const r = el.getBoundingClientRect();
    if ((r.width > 0 || r.height > 0) && r.height < 30) {
      count += 1;
    }
  }
  return count;
});

const hasHorizontalOverflow = extract((state) => {
  return state.document.documentElement.scrollWidth > state.window.innerWidth + 1;
});

const themeTokenState = extract((state) => {
  const theme = state.document.documentElement.dataset.theme || "";
  const surface = state.window.getComputedStyle(state.document.documentElement).getPropertyValue("--kos-surface").trim();
  return { theme, hasSurface: surface.length > 0 };
});

const mapCanvasValidWhenActive = extract((state) => {
  const mapView = state.document.getElementById("view-map");
  if (!mapView || !mapView.classList.contains("is-active")) {
    return true;
  }
  const voronoi = state.document.getElementById("voronoi-canvas");
  if (!voronoi) return false;
  const r = voronoi.getBoundingClientRect();
  return r.width >= 100 && r.height >= 100;
});

export const noButtonMultiLineWrapping = always(() => wrappedButtonsCount.current === 0);

export const noCollapsedTextInputs = always(() => collapsedInputsCount.current === 0);

export const noHorizontalPageOverflow = always(() => !hasHorizontalOverflow.current);

export const dualModeDesignTokensActive = always(
  () => (themeTokenState.current.theme === "light" || themeTokenState.current.theme === "dark") && themeTokenState.current.hasSurface,
);

const mapDiagStats = extract((state) => {
  const diag = (state.window as unknown as { __KOS_DIAG__?: { captureSnapshot: (p: string) => { customBBox: { x: [number, number]; y: [number, number] } | null; overlapStats: { maxScreenRadiusPx: number } } } }).__KOS_DIAG__;
  if (!diag) return { hasCustomBBox: true, maxRadius: 0 };
  const snap = diag.captureSnapshot("bombadil");
  const hasFixed =
    snap.customBBox !== null &&
    snap.customBBox.x[0] === 0 &&
    snap.customBBox.x[1] === 10000 &&
    snap.customBBox.y[0] === 0 &&
    snap.customBBox.y[1] === 10000;
  return { hasCustomBBox: hasFixed, maxRadius: snap.overlapStats.maxScreenRadiusPx };
});

export const mapCanvasVisibleWhenOnMapTab = always(() => mapCanvasValidWhenActive.current);

export const worldBBoxStaysPinned = always(() => mapDiagStats.current.hasCustomBBox);

export const highZoomNodeRadiusBounded = always(() => mapDiagStats.current.maxRadius <= 8.5);
