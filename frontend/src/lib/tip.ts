/** The charts' hover box. Its lines are set as text, never as markup: the
 *  names and headlines come from feeds anyone can write to. */
export type TipLine = string | { text: string; bold?: boolean; dim?: boolean };

export function showTip(el: HTMLElement | null, e: MouseEvent, lines: TipLine[]): void {
  if (!el) return;
  el.replaceChildren(
    ...lines.filter((l) => (typeof l === "string" ? l : l.text)).map((l) => {
      const row = document.createElement("div");
      if (typeof l === "string") row.textContent = l;
      else {
        row.textContent = l.text;
        if (l.bold) row.style.fontWeight = "600";
        if (l.dim) row.style.opacity = "0.7";
      }
      return row;
    }),
  );
  el.style.display = "block";
  // Kept inside the window.
  const pad = 12;
  const w = el.offsetWidth, h = el.offsetHeight;
  el.style.left = `${Math.min(e.clientX + pad, window.innerWidth - w - 4)}px`;
  el.style.top = `${e.clientY + pad + h > window.innerHeight ? e.clientY - h - pad : e.clientY + pad}px`;
}

export function hideTip(el: HTMLElement | null): void {
  if (el) el.style.display = "none";
}
