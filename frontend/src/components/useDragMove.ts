import { type CSSProperties, type PointerEvent, useState } from "react";

// How much of a moved window stays on screen, so it can always be brought back.
const KEEP_VISIBLE = 80;
const TITLE_HEIGHT = 34;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

/**
 * A window over the main one, moved by its title bar like a desktop window.
 * It opens centred, as before: the offset is dropped while it is closed.
 */
export function useDragMove(open = true): {
  style: CSSProperties;
  onPointerDown: (e: PointerEvent<HTMLElement>) => void;
} {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  if (!open && (offset.x !== 0 || offset.y !== 0)) setOffset({ x: 0, y: 0 });

  const onPointerDown = (e: PointerEvent<HTMLElement>) => {
    if (e.button !== 0) return;
    if ((e.target as HTMLElement).closest("button, input, select, textarea, a")) return;
    const frame = e.currentTarget.closest<HTMLElement>("[role='dialog']");
    if (!frame) return;
    e.preventDefault();
    const bar = e.currentTarget;
    const box = frame.getBoundingClientRect();
    const start = { x: e.clientX, y: e.clientY, offset };
    bar.setPointerCapture(e.pointerId);
    const move = (ev: globalThis.PointerEvent) => {
      const dx = clamp(
        ev.clientX - start.x,
        KEEP_VISIBLE - box.right,
        window.innerWidth - KEEP_VISIBLE - box.left,
      );
      const dy = clamp(ev.clientY - start.y, -box.top, window.innerHeight - TITLE_HEIGHT - box.top);
      setOffset({ x: start.offset.x + dx, y: start.offset.y + dy });
    };
    const end = () => {
      bar.removeEventListener("pointermove", move);
      bar.removeEventListener("pointerup", end);
      bar.removeEventListener("pointercancel", end);
    };
    bar.addEventListener("pointermove", move);
    bar.addEventListener("pointerup", end);
    bar.addEventListener("pointercancel", end);
  };

  return {
    style: { transform: `translate(calc(-50% + ${offset.x}px), calc(-50% + ${offset.y}px))` },
    onPointerDown,
  };
}
