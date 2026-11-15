import type { Frame, Query } from "./types";
export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) {
    let message = `Request failed (${r.status})`;
    try {
      const b = await r.json();
      message =
        typeof b.detail === "string"
          ? b.detail
          : b.error || JSON.stringify(b.detail || b);
    } catch {
      /* upstream response is not JSON */
    }
    throw new Error(message);
  }
  return r.json();
}
export const post = <T>(url: string, data: unknown) =>
  request<T>(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
export function download(
  name: string,
  data: unknown,
  type = "application/json",
) {
  const b = new Blob(
    [typeof data === "string" ? data : JSON.stringify(data, null, 2)],
    { type },
  );
  const u = URL.createObjectURL(b);
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
export function fmt(value: number | undefined | null, d = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(d)
    : "—";
}
export function date(value: string | number) {
  const d =
    typeof value === "number"
      ? new Date((value - 40587) * 86400000)
      : new Date(value);
  return Number.isFinite(d.getTime())
    ? d.toISOString().slice(0, 10)
    : "Unknown date";
}
export function quantile(a: number[], p: number) {
  if (!a.length) return 0;
  const s = [...a].sort((a, b) => a - b);
  return s[Math.min(s.length - 1, Math.floor(p * (s.length - 1)))];
}
export function pixelSky(x: number, y: number, w: number, h: number, q: Query) {
  const rad = Math.PI / 180,
    xi = ((-(x - (w - 1) / 2) * q.fov) / 60 / w) * rad,
    eta = ((-(y - (h - 1) / 2) * q.fov) / 60 / h) * rad,
    dec = q.dec * rad;
  const a = Math.cos(dec) - eta * Math.sin(dec);
  return {
    ra: (((q.ra + Math.atan2(xi, a) / rad) % 360) + 360) % 360,
    dec:
      Math.atan2(
        Math.sin(dec) + eta * Math.cos(dec),
        Math.sqrt(a * a + xi * xi),
      ) / rad,
  };
}
export function aperture(frame: Frame, x: number, y: number) {
  const { width: w, height: h, data, variance, wavelength } = frame;
  let sum = 0,
    v = 0,
    n = 0;
  const sky: number[] = [],
    waves: number[] = [];
  for (let j = Math.max(0, y - 7); j <= Math.min(h - 1, y + 7); j++)
    for (let i = Math.max(0, x - 7); i <= Math.min(w - 1, x + 7); i++) {
      const d = Math.hypot(i - x, j - y),
        k = j * w + i,
        f = data[k],
        err = variance[k];
      if (f === null || err === null || err <= 0) continue;
      if (d <= 2) {
        sum += f;
        v += err;
        n++;
        if (wavelength[k] != null) waves.push(wavelength[k]!);
      } else if (d >= 4 && d <= 7) sky.push(f);
    }
  const bg = quantile(sky, 0.5);
  const scatter =
    1.4826 *
    quantile(
      sky.map((v) => Math.abs(v - bg)),
      0.5,
    );
  return {
    mjd: frame.metadata.mjd,
    date: date(frame.metadata.mjd),
    wavelength: quantile(waves, 0.5) || null,
    value: n ? sum / n - bg : null,
    error: n
      ? Math.sqrt(
          v / (n * n) +
            (Math.PI * scatter * scatter) / (2 * Math.max(1, sky.length)),
        )
      : null,
    n,
    background: bg,
    source: frame.metadata.id,
  };
}
export function renderPixels(
  canvas: HTMLCanvasElement,
  frame: Frame,
  contrast = 1,
  palette = "ice",
  difference?: Frame,
  scale?: [number, number],
) {
  canvas.width = frame.width;
  canvas.height = frame.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const values = frame.data.map((v, i) =>
    v === null || difference?.data[i] === null
      ? null
      : difference
        ? v - (difference.data[i] ?? 0)
        : v,
  );
  const valid = values.filter(
    (v): v is number => v !== null && Number.isFinite(v),
  );
  const lo = difference
      ? -quantile(valid.map(Math.abs), 0.99)
      : (scale?.[0] ?? quantile(valid, 0.02)),
    hi = difference ? -lo : (scale?.[1] ?? quantile(valid, 0.995));
  const im = ctx.createImageData(frame.width, frame.height);
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    let c = [9, 14, 17];
    if (v !== null) {
      let t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)));
      t = difference ? t : Math.asinh(t * 12 * contrast) / Math.asinh(12);
      if (difference) {
        const d = Math.abs(t - 0.5) * 2;
        c =
          t > 0.5
            ? [35 + 220 * d, 38 + 130 * d, 42 + 45 * d]
            : [35 + 35 * d, 38 + 150 * d, 42 + 210 * d];
      } else if (palette === "mono") {
        c = [t * 255, t * 255, t * 255];
      } else {
        c = [
          10 + 225 * Math.pow(t, 1.3),
          17 + 231 * Math.pow(t, 1.05),
          22 + 226 * Math.pow(t, 0.8),
        ];
      }
    }
    im.data.set([...c, 255], i * 4);
  }
  ctx.putImageData(im, 0, 0);
}
