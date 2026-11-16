export type Vector = [number, number, number];
export type Sample = [number, ...Vector];
export type CandidateDirection = {
  id?: string;
  ra: number;
  dec: number;
  label?: string;
};
export type BodyEphemeris = {
  name: string;
  classification: string;
  target: string;
  source: string;
  samples: Sample[];
};
export interface SolarEphemerides {
  origin: string;
  frame: string;
  timeScale: string;
  positionUnit: string;
  source: string;
  sourceHome: string;
  retrievedAt: string;
  stepDays: number;
  bodies: Record<string, BodyEphemeris>;
}

export const BODY_COLORS: Record<string, string> = {
  sun: "#ffd29a",
  mercury: "#c5c8ce",
  venus: "#f9cba4",
  earth: "#75d7ff",
  mars: "#ed937d",
  jupiter: "#e2b89a",
  saturn: "#f1d096",
  uranus: "#9be9e7",
  neptune: "#859cfa",
  ceres: "#c4adf4",
  interstellar: "#7af3d6",
};

const UNITS_PER_DAY = 86400000;
const UNIX_JD = 2440587.5;
export const currentJD = () => Date.now() / UNITS_PER_DAY + UNIX_JD;
export function dateForJD(jd: number) {
  return new Date((jd - UNIX_JD) * UNITS_PER_DAY).toISOString().slice(0, 10);
}

/** Interpolate within the exact Horizons sample window. No extrapolation. */
export function positionAt(samples: Sample[], jd: number): Vector | null {
  if (
    !Number.isFinite(jd) ||
    !samples.length ||
    jd < samples[0][0] ||
    jd > samples[samples.length - 1][0]
  )
    return null;
  let upper = samples.length - 1;
  let lower = 0;
  while (upper - lower > 1) {
    const middle = Math.floor((upper + lower) / 2);
    if (samples[middle][0] > jd) upper = middle;
    else lower = middle;
  }
  const a = samples[lower];
  const b = samples[upper];
  const weight = b[0] === a[0] ? 0 : (jd - a[0]) / (b[0] - a[0]);
  return [
    a[1] + (b[1] - a[1]) * weight,
    a[2] + (b[2] - a[2]) * weight,
    a[3] + (b[3] - a[3]) * weight,
  ];
}

/** ICRS angles represented on a normalized direction sphere, with no range. */
export function skyVector(ra: number, dec: number): Vector {
  const a = (ra * Math.PI) / 180;
  const d = (dec * Math.PI) / 180;
  return [Math.cos(d) * Math.cos(a), Math.cos(d) * Math.sin(a), Math.sin(d)];
}
