// Pointer-based drag reordering for grids and lists, without a library.
//
// Mouse: drag starts after a few pixels of movement.
// Touch: drag starts after a short hold, so ordinary swipes still scroll.
// Keyboard: Alt + arrow keys move the focused item.
// The dragged item stays in the list as a placeholder; a ghost follows the pointer.
// Optional drop targets (e.g. a folder tile, a breadcrumb) take the item instead of reordering.

import { useCallback, useEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

const MOUSE_SLOP_PX = 5;
const TOUCH_HOLD_MS = 280;
const TOUCH_CANCEL_PX = 8;
// Over a drop target's edge, wait this long before reordering, so heading for its
// middle doesn't shove it out from under the pointer.
const EDGE_DWELL_MS = 350;

export interface DragGhost {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  offsetX: number;
  offsetY: number;
}

interface Options {
  /** Called once on drop with the new order, only if it changed. */
  onCommit: (ids: string[]) => void;
  /** Touch long-press released without moving (e.g. open a context menu). */
  onLongPress?: (id: string, x: number, y: number) => void;
  disabled?: boolean;
  /** Dropping onto a bound target (see bindTarget) instead of into a slot. */
  drop?: {
    accepts: (dragId: string, targetKey: string) => boolean;
    onDrop: (dragId: string, targetKey: string) => void;
  };
}

export function useReorder(ids: string[], { onCommit, onLongPress, disabled, drop }: Options) {
  const [preview, setPreview] = useState<string[] | null>(null);
  const [ghost, setGhost] = useState<DragGhost | null>(null);
  const [over, setOver] = useState<string | null>(null);
  const elements = useRef(new Map<string, HTMLElement>());
  // Drop targets; `inset` keeps a target's edges free for reordering (fraction of its size).
  const targets = useRef(new Map<string, { el: HTMLElement; inset: number }>());
  const session = useRef<{
    id: string;
    pointerId: number;
    startX: number;
    startY: number;
    touch: boolean;
    active: boolean;
    holdTimer?: ReturnType<typeof setTimeout>;
    order: string[];
    rect: DOMRect;
    over: string | null;
    edge?: { key: string; ready: boolean; timer: ReturnType<typeof setTimeout> };
  } | null>(null);
  const moveRef = useRef<(x: number, y: number) => void>(() => {});
  const suppressClick = useRef(false);
  const latest = useRef({ ids, onCommit, onLongPress, drop });
  latest.current = { ids, onCommit, onLongPress, drop };

  const order = preview ?? ids;

  const activate = useCallback((x: number, y: number) => {
    const s = session.current;
    if (!s) return;
    s.active = true;
    suppressClick.current = true;
    setPreview(s.order);
    setGhost({
      id: s.id,
      x,
      y,
      width: s.rect.width,
      height: s.rect.height,
      offsetX: s.startX - s.rect.left,
      offsetY: s.startY - s.rect.top,
    });
  }, []);

  const move = useCallback((x: number, y: number) => {
    const s = session.current;
    if (!s?.active) return;
    setGhost((g) => (g ? { ...g, x, y } : g));
    const { drop } = latest.current;
    let target: string | null = null;
    let edge: string | null = null;
    if (drop) {
      for (const [key, { el, inset }] of targets.current) {
        const r = el.getBoundingClientRect();
        if (x < r.left || x > r.right || y < r.top || y > r.bottom || !drop.accepts(s.id, key)) continue;
        const dx = r.width * inset;
        const dy = r.height * inset;
        if (x >= r.left + dx && x <= r.right - dx && y >= r.top + dy && y <= r.bottom - dy) target = key;
        else edge = key;
        break;
      }
    }
    if (target !== s.over) {
      s.over = target;
      setOver(target);
    }
    if (target) return;
    if (edge !== (s.edge?.key ?? null)) {
      if (s.edge) clearTimeout(s.edge.timer);
      s.edge = edge
        ? { key: edge, ready: false, timer: setTimeout(() => {
            if (session.current?.edge?.key !== edge) return;
            session.current.edge.ready = true;
            moveRef.current(x, y);
          }, EDGE_DWELL_MS) }
        : undefined;
    }
    if (s.edge && !s.edge.ready) return;
    // Hit-test the item under the pointer; move the dragged item into its slot.
    for (const [id, el] of elements.current) {
      if (id === s.id) continue;
      const r = el.getBoundingClientRect();
      if (x >= r.left && x <= r.right && y >= r.top && y <= r.bottom) {
        const next = s.order.filter((i) => i !== s.id);
        next.splice(s.order.indexOf(id), 0, s.id);
        if (next.join() !== s.order.join()) {
          s.order = next;
          setPreview(next);
        }
        break;
      }
    }
  }, []);
  moveRef.current = move;

  const end = useCallback((commit: boolean) => {
    const s = session.current;
    session.current = null;
    if (!s) return;
    clearTimeout(s.holdTimer);
    if (s.edge) clearTimeout(s.edge.timer);
    const dropped = s.active && commit && s.over !== null;
    if (dropped) latest.current.drop?.onDrop(s.id, s.over!);
    else if (s.active && commit && s.order.join() !== latest.current.ids.join()) latest.current.onCommit(s.order);
    setGhost(null);
    setOver(null);
    // Keep the previewed order until the parent re-renders with saved data.
    if (!s.active || !commit || dropped) setPreview(null);
    // Clicks fire after pointerup; clear the suppression once they had a chance to.
    setTimeout(() => (suppressClick.current = false), 0);
  }, []);

  // Clear the preview once the committed order arrives from the server.
  useEffect(() => {
    if (preview && !session.current && preview.join() === ids.join()) setPreview(null);
  }, [ids, preview]);

  useEffect(() => {
    if (!ghost && !session.current) return;
    const onMove = (e: globalThis.PointerEvent) => {
      const s = session.current;
      if (!s || e.pointerId !== s.pointerId) return;
      const dist = Math.hypot(e.clientX - s.startX, e.clientY - s.startY);
      if (!s.active) {
        if (s.touch) {
          if (dist > TOUCH_CANCEL_PX) end(false); // it was a scroll
        } else if (dist > MOUSE_SLOP_PX) {
          activate(e.clientX, e.clientY);
        }
        return;
      }
      e.preventDefault();
      move(e.clientX, e.clientY);
    };
    const onUp = (e: globalThis.PointerEvent) => {
      const s = session.current;
      if (!s || e.pointerId !== s.pointerId) return;
      if (s.touch && s.active && s.over === null && s.order.join() === latest.current.ids.join()) {
        // Long-press without moving: treat as a context-menu gesture.
        const { onLongPress } = latest.current;
        end(false);
        onLongPress?.(s.id, e.clientX, e.clientY);
        return;
      }
      end(true);
    };
    const onCancel = () => end(false);
    // iOS needs touchmove cancelled to stop the page scrolling under an active drag.
    const onTouchMove = (e: TouchEvent) => {
      if (session.current?.active) e.preventDefault();
    };
    window.addEventListener("touchmove", onTouchMove, { passive: false });
    window.addEventListener("pointermove", onMove, { passive: false });
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    return () => {
      window.removeEventListener("touchmove", onTouchMove);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
    };
  });

  const bind = useCallback(
    (id: string) => ({
      ref: (el: HTMLElement | null) => {
        if (el) elements.current.set(id, el);
        else elements.current.delete(id);
      },
      "data-dragging": session.current?.active && session.current.id === id ? "" : undefined,
      onPointerDown: (e: PointerEvent<HTMLElement>) => {
        if (disabled || e.button !== 0 || session.current) return;
        if ((e.target as HTMLElement).closest("[data-no-drag]")) return;
        const touch = e.pointerType !== "mouse";
        const rect = e.currentTarget.getBoundingClientRect();
        session.current = {
          id,
          pointerId: e.pointerId,
          startX: e.clientX,
          startY: e.clientY,
          touch,
          active: false,
          order: latest.current.ids,
          rect,
          over: null,
        };
        if (touch) {
          const { clientX, clientY } = e;
          session.current.holdTimer = setTimeout(() => activate(clientX, clientY), TOUCH_HOLD_MS);
        }
        forceListeners(); // attach window listeners for this gesture
      },
      onClickCapture: (e: React.MouseEvent) => {
        if (suppressClick.current) {
          e.preventDefault();
          e.stopPropagation();
        }
      },
      onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
        if (disabled || !e.altKey) return;
        const delta = e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : 0;
        if (!delta) return;
        e.preventDefault();
        const current = latest.current.ids;
        const index = current.indexOf(id);
        const target = index + delta;
        if (target < 0 || target >= current.length) return;
        const next = [...current];
        next.splice(index, 1);
        next.splice(target, 0, id);
        setPreview(next);
        latest.current.onCommit(next);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [disabled, activate],
  );

  // A state tick so the window listeners effect re-runs when a gesture starts.
  const [, setTick] = useState(0);
  const forceListeners = () => setTick((t) => t + 1);

  /** Register a drop target. Only used while dragging, when `drop` is given. */
  const bindTarget = useCallback(
    (key: string, inset = 0) => (el: HTMLElement | null) => {
      if (el) targets.current.set(key, { el, inset });
      else targets.current.delete(key);
    },
    [],
  );

  return { order, ghost, bind, bindTarget, over, dragging: ghost !== null };
}
