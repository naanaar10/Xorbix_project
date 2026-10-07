// Motion helpers. Everything here becomes instant under prefers-reduced-motion.
export const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function countUp(el, value, format, ms = 700) {
  if (reducedMotion()) {
    el.textContent = format(value);
    return;
  }
  const start = performance.now();
  const tick = (now) => {
    const t = Math.min(1, (now - start) / ms);
    el.textContent = format(value * (1 - (1 - t) ** 3));
    if (t < 1) requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

export function countAll(root, format) {
  root.querySelectorAll("[data-count]").forEach((el) => countUp(el, Number(el.dataset.count), format));
}

// Bars are drawn at width 0 and grow to their data-w on the next frames.
export function growBars(root) {
  const bars = root.querySelectorAll("[data-w]");
  const apply = () => bars.forEach((bar) => { bar.style.width = bar.dataset.w; });
  if (reducedMotion()) apply();
  else requestAnimationFrame(() => requestAnimationFrame(apply));
}
