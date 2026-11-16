import { CircleHelp, RotateCw } from "lucide-react";
import { date } from "./lib";
import { DETECTORS } from "./types";
import type { SearchResult } from "./types";

export default function ArchiveStatus({
  search,
  loaded,
  failed,
  onRetry,
  onDetector,
}: {
  search: SearchResult;
  loaded: number;
  failed: number;
  onRetry: () => void;
  onDetector: (detector: number) => void;
}) {
  const coverageIncomplete = search.searchCoverage?.complete === false;
  const choices =
    search.detectorOptions?.filter(
      (choice) => choice.detector !== search.query.detector,
    ) ?? [];
  let message = "";
  if (!search.observations.length) {
    if (search.outcome === "other-detectors")
      message = `The returned metadata contain exposures in other detectors. ${coverageIncomplete ? "Coverage for the selected detector is still unverified." : "The completed query returned none for the selected detector."}`;
    else if (search.outcome === "no-coverage")
      message =
        "The completed archive search returned no matching Level 2 exposures at this field centre.";
    else if (coverageIncomplete)
      message =
        "Coverage is unverified here. IRSA did not complete the search and no matching NASA FITS header was found in the available sample.";
    else message = "This request returned no exposure records.";
  } else if (!loaded)
    message =
      "Exposure metadata were found, but none of the attempted images returned usable pixels. See the individual failures below.";
  else if (loaded === 1)
    message =
      "One usable exposure loaded. A second usable observation is needed to compare epochs.";
  else if (failed)
    message = `${loaded} NASA exposures loaded. ${failed} image request${failed === 1 ? "" : "s"} could not supply usable pixels.`;
  else if (coverageIncomplete)
    message =
      "Viewing real NASA exposures from a partial archive search. More observations may exist than are listed here.";
  if (!message && !choices.length) return null;
  return (
    <section
      className="archive-recovery"
      aria-label="Archive coverage and detector options"
    >
      {message && (
        <div className="archive-recovery-message" role="status">
          <CircleHelp size={16} />
          <span>{message}</span>
          {(!loaded || failed > 0 || coverageIncomplete) && (
            <button className="secondary" onClick={onRetry}>
              <RotateCw size={13} /> Retry lookup
            </button>
          )}
        </div>
      )}
      {choices.length > 0 && (
        <details open={loaded < 2 ? true : undefined}>
          <summary>Other detectors for this position</summary>
          <div className="detector-options">
            {choices.map((option) => (
              <button
                key={option.detector}
                className="secondary"
                onClick={() => onDetector(option.detector)}
              >
                <strong>
                  D{option.detector} · {DETECTORS[option.detector - 1]} µm
                </strong>
                <span>
                  {option.count} exposure{option.count !== 1 ? "s" : ""} found ·{" "}
                  {option.visits} date group{option.visits !== 1 ? "s" : ""}
                </span>
                <span>
                  {date(option.firstMjd)} to {date(option.lastMjd)}
                </span>
              </button>
            ))}
          </div>
          <p className="caption">
            Counts come from metadata. Pixel quality is checked when you open a
            detector.
          </p>
        </details>
      )}
    </section>
  );
}
