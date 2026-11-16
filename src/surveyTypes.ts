import type { Query } from "./types";

export interface EpochEvidence {
  ra: number;
  dec: number;
  mjd: number;
  positionKind?: string;
  wavelengthUm?: number | null;
  surfaceBrightnessMjySr?: number | null;
  variance?: number | null;
  flagBits?: number;
  observerState?: unknown;
  [key: string]: unknown;
}
export interface InvestigationInput {
  id?: string;
  ra: number;
  dec: number;
  referenceMjd: number;
  evidence: {
    epochMeasurements?: EpochEvidence[];
    nominalSnr?: number;
    staticSnr?: number | null;
    snrGainOverStatic?: number | null;
    velocityWestArcsecDay?: number;
    velocitySouthArcsecDay?: number;
    [key: string]: unknown;
  };
}
export interface Candidate extends InvestigationInput {
  id: string;
  fieldId: string;
  field?: Query;
  analysisPixels?: number;
  detector: number;
  fov: number;
  analysisId: string;
  classification: string;
  observations: {
    id: string;
    url: string;
    collection?: string;
    mjd: number;
    date?: string;
    wavelengthUm?: number | null;
    quality?: unknown;
    provenance?: unknown;
  }[];
  history?: Record<string, unknown>[];
  investigation?: Investigation;
  catalogInvestigation?: Investigation;
}
export interface Investigation {
  classification?: string;
  investigatedAt?: string;
  generatedAt?: string;
  checkedAt?: string;
  reasons?: string[];
  hypotheses?: unknown;
  scope?: unknown;
  warnings?: string[];
  gaia?: Record<string, unknown>;
  jpl?: Record<string, unknown>;
  [key: string]: unknown;
}
export interface SurveyField extends Query {
  id: string;
  label: string;
  status: string;
  latest?: {
    attempt: number;
    startedAt: string;
    finishedAt?: string;
    searchStatus?: string;
    archiveTotal?: number;
    observationsFetched?: number;
    observationsAnalyzed?: number;
    usablePixelSamples?: number;
    baselineDays?: number;
    analysisId?: string;
    message?: string;
    notes?: string[];
  };
  history?: Record<string, unknown>[];
}
export interface SurveySnapshot {
  schemaVersion: number;
  surveyId: string;
  label: string;
  generatedAt: string;
  config: Record<string, unknown>;
  summary: Record<string, number>;
  fields: SurveyField[];
  candidates: Candidate[];
  limitations: string[];
}
