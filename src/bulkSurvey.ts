import { useEffect, useState } from "react";
import type { Sky } from "./atlas/geometry";

export interface BulkFootprint extends Sky {
  id: string;
  boundary: Sky[];
}

export interface BulkSurveyBatch {
  id: string;
  startedAt: string;
  finishedAt?: string | null;
  successful: number;
  uniqueProcessed: number;
  failed: number;
  skipped: number;
  retries: number;
  interrupted?: number;
  wallSeconds?: number | null;
  workers?: number;
}

export interface BulkSurveySnapshot {
  generatedAt: string;
  goal: number;
  summary: {
    discovered: number;
    uniqueProcessed: number;
    successfulOperations: number;
    pending: number;
    running: number;
    failed: number;
    skipped: number;
    retries: number;
    interrupted?: number;
    regionsAnalyzed: number;
    fieldsPending: number;
    fieldsFailed: number;
    fieldsIncomplete?: number;
    fieldsEmpty?: number;
    fieldsUnsearched?: number;
    fieldsWaitingEpochs?: number;
    errorAttempts?: number;
    candidates: number;
    investigated: number;
    knownMatches: number;
    unresolved: number;
    motionInputs?: number | null;
    catalogAttempts?: number;
    catalogCompleted?: number;
  };
  coverage: {
    areaSquareDegrees: number | null;
    motionAreaSquareDegrees?: number | null;
    cellAreaSquareDegrees?: number | null;
    method: string;
    nside?: number;
    footprintsTruncated?: boolean;
  };
  batches: BulkSurveyBatch[];
  footprints: BulkFootprint[];
  limitations: string[];
  ledgerUrl?: string | null;
  inventory?: {
    listedScopes: number;
    completedScopes: number;
    errors?: number;
  };
}

function isBulkSnapshot(value: unknown): value is BulkSurveySnapshot {
  if (typeof value !== "object" || value === null) return false;
  const data = value as Partial<BulkSurveySnapshot>;
  return (
    typeof data.generatedAt === "string" &&
    typeof data.goal === "number" &&
    data.goal > 0 &&
    typeof data.summary?.uniqueProcessed === "number" &&
    typeof data.coverage?.method === "string" &&
    Array.isArray(data.batches) &&
    Array.isArray(data.footprints) &&
    Array.isArray(data.limitations)
  );
}

let published: BulkSurveySnapshot | null = null;
let checkedAt = 0;

export function useBulkSurvey(enabled = true) {
  const [snapshot, setSnapshot] = useState<BulkSurveySnapshot | null>(
    published,
  );
  const [unavailable, setUnavailable] = useState(false);
  const [requestKey, setRequestKey] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    if (published && Date.now() - checkedAt < 60_000 && requestKey === 0) {
      setSnapshot(published);
      return;
    }
    const abort = new AbortController();
    fetch("/bulk-survey.json", { signal: abort.signal, cache: "no-cache" })
      .then((response) => {
        if (!response.ok) throw new Error("Bulk survey unavailable");
        return response.json() as Promise<unknown>;
      })
      .then((value) => {
        if (!isBulkSnapshot(value))
          throw new Error("Invalid bulk survey snapshot");
        published = value;
        checkedAt = Date.now();
        setSnapshot(value);
        setUnavailable(false);
      })
      .catch(() => {
        if (!abort.signal.aborted) setUnavailable(true);
      });
    return () => abort.abort();
  }, [enabled, requestKey]);

  return {
    snapshot,
    unavailable,
    reload() {
      setUnavailable(false);
      setRequestKey((key) => key + 1);
    },
  };
}
