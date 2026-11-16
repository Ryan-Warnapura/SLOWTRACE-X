import type {
  Candidate,
  EpochEvidence,
  SurveyField,
  SurveySnapshot,
} from "../surveyTypes";

export const MJD_UNIX_EPOCH = 40587;
const DAY_MS = 86_400_000;
const dateFormatter = new Intl.DateTimeFormat("en-CA", {
  year: "numeric",
  month: "short",
  day: "numeric",
  timeZone: "UTC",
});

export function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function utcDate(iso: string) {
  const timestamp = Date.parse(iso);
  return Number.isFinite(timestamp)
    ? dateFormatter.format(timestamp)
    : "Date unavailable";
}

export function dateOfMjd(mjd: number) {
  return finite(mjd)
    ? dateFormatter.format((mjd - MJD_UNIX_EPOCH) * DAY_MS)
    : "Date unavailable";
}

export function readable(value: string) {
  return value.replaceAll("-", " ").replaceAll("_", " ");
}

export function candidateSpeed(candidate: Candidate) {
  const { velocityWestArcsecDay: west, velocitySouthArcsecDay: south } =
    candidate.evidence;
  return finite(west) && finite(south) ? Math.hypot(west, south) : null;
}

export function validSamples(candidate: Candidate) {
  return (candidate.evidence.epochMeasurements ?? []).filter(
    (sample) => sample.sampleValid !== false && finite(sample.mjd),
  );
}

export function sampledBrightness(candidate: Candidate) {
  const values = validSamples(candidate)
    .map((sample) => sample.surfaceBrightnessMjySr)
    .filter(finite)
    .sort((a, b) => a - b);
  if (!values.length) return null;
  return (
    (values[Math.floor(values.length / 2)] +
      values[Math.floor((values.length - 1) / 2)]) /
    2
  );
}

export function distribution(values: unknown[], binCount = 8) {
  const measured = values.filter(finite);
  if (!measured.length) return [];
  const min = Math.min(...measured);
  const max = Math.max(...measured);
  if (min === max) return [{ from: min, to: max, count: measured.length }];
  const step = (max - min) / binCount;
  const bins = Array.from({ length: binCount }, (_, index) => ({
    from: min + index * step,
    to: index === binCount - 1 ? max : min + (index + 1) * step,
    count: 0,
  }));
  for (const value of measured) {
    bins[Math.min(binCount - 1, Math.floor((value - min) / step))].count++;
  }
  return bins;
}

export interface SurveyInput {
  id: string;
  url: string;
  collection: string;
  detector: number;
  mjd: number;
  wavelengthUm: number | null;
  quality?: { badFraction?: number; saturatedFraction?: number };
}

export interface SurveyAnalysis {
  id: string;
  fieldId: string;
  baselineDays: number;
  observations: SurveyInput[];
}

export interface StatisticsSnapshot extends SurveySnapshot {
  analyses: SurveyAnalysis[];
}

export function surveyFields(snapshot: StatisticsSnapshot) {
  return snapshot.fields.map((field) => {
    const analyses = snapshot.analyses.filter(
      (analysis) => analysis.fieldId === field.id,
    );
    const distinct = new Map(
      analyses
        .flatMap((analysis) => analysis.observations)
        .map((obs) => [obs.url, obs]),
    );
    const observations = [...distinct.values()].sort((a, b) => a.mjd - b.mjd);
    return { ...field, observations, analyzed: analyses.length > 0 };
  });
}

/** Sum of nominal square gnomonic footprints, including overlap and all masked pixels. */
export function nominalAreaCeiling(fields: SurveyField[]) {
  const toRad = Math.PI / 180;
  return fields.reduce((sum, field) => {
    if (!finite(field.fov) || field.fov <= 0) return sum;
    const halfWidth = (field.fov / 120) * toRad;
    const solidAngle =
      4 * Math.atan(halfWidth ** 2 / Math.sqrt(1 + 2 * halfWidth ** 2));
    return sum + solidAngle / toRad ** 2;
  }, 0);
}

export function tangentOffsets(ra: number, dec: number, sample: EpochEvidence) {
  const rad = Math.PI / 180;
  const delta = (sample.ra - ra) * rad;
  const lat = sample.dec * rad;
  const lat0 = dec * rad;
  const denominator =
    Math.sin(lat) * Math.sin(lat0) +
    Math.cos(lat) * Math.cos(lat0) * Math.cos(delta);
  if (denominator <= 0) return null;
  const arcsec = 3600 / rad;
  return {
    east: (arcsec * Math.cos(lat) * Math.sin(delta)) / denominator,
    north:
      (arcsec *
        (Math.sin(lat) * Math.cos(lat0) -
          Math.cos(lat) * Math.sin(lat0) * Math.cos(delta))) /
      denominator,
  };
}

export interface InjectionRecord {
  kind: string;
  trials: number;
  selectedFrameIndices: number[];
  baselineDays: number;
  thresholdSnr: number;
  injectedSingleFrameNominalSnr: number;
  motionArcsecDay: number[];
  recovered: {
    shiftStack: number;
    staticStack: number;
    bestSingleFrame: number;
  };
  unInjectedControlPeaks: number;
  negativeControlPeaks: number;
  controlPeakCountCappedAt: number;
  measurements: {
    shiftStackSnr: number | null;
    staticStackSnr: number | null;
    bestSingleFrameSnr: number | null;
  }[];
  notes: string[];
}
