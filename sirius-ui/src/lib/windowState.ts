// Single source of truth for "is the SIRIUS window visible?".
// `document.visibilityState` is not reliable in Tauri when the window is
// merely hidden to tray, so visibility is driven by Tauri window events
// (see App.tsx) and read synchronously from hot paths (rAF, timers, WS).

let visible = true;
const listeners = new Set<() => void>();

export function isWindowVisible(): boolean {
  return visible;
}

export function setWindowVisible(v: boolean): void {
  if (v === visible) return;
  visible = v;
  listeners.forEach((cb) => {
    try {
      cb();
    } catch {
      /* listener errors must not break visibility propagation */
    }
  });
}

export function onWindowVisibleChange(cb: () => void): () => void {
  listeners.add(cb);
  return () => {
    listeners.delete(cb);
  };
}
