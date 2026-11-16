/** Display colours for SPHEREx wavelengths. See DESIGN.md: hues follow the
 *  tints NASA used for the six detectors in the first-light release. */
export const BAND_COLORS = [
  "#b18cf5",
  "#6ea4f2",
  "#45c9b3",
  "#a8cc4e",
  "#e6b93f",
  "#f07a55",
] as const;

// Band centres in microns; colours are interpolated between them.
const STOPS: [number, string][] = [
  [0.925, BAND_COLORS[0]],
  [1.37, BAND_COLORS[1]],
  [2.03, BAND_COLORS[2]],
  [3.12, BAND_COLORS[3]],
  [4.12, BAND_COLORS[4]],
  [4.71, BAND_COLORS[5]],
];
const NEUTRAL = "#8d8b85";

const channels = (hex: string) =>
  [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));

export function bandColor(detector?: number | null) {
  return detector && detector >= 1 && detector <= 6
    ? BAND_COLORS[detector - 1]
    : NEUTRAL;
}

export function wavelengthColor(microns?: number | null) {
  if (microns === null || microns === undefined || !Number.isFinite(microns))
    return NEUTRAL;
  if (microns <= STOPS[0][0]) return STOPS[0][1];
  for (let i = 1; i < STOPS.length; i++) {
    const [hi, hiColor] = STOPS[i];
    if (microns > hi) continue;
    const [lo, loColor] = STOPS[i - 1];
    const t = (microns - lo) / (hi - lo);
    const a = channels(loColor),
      b = channels(hiColor);
    return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * t)).join(" ")})`;
  }
  return STOPS[STOPS.length - 1][1];
}
