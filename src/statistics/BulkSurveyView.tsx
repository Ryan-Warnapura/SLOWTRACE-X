import { useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  CircleAlert,
  Crosshair,
  Database,
  Globe2,
  Map,
  Telescope,
} from "lucide-react";
import { useBulkSurvey, type BulkSurveyBatch } from "../bulkSurvey";
import { finite } from "./data";
import "./bulk-survey.css";

const integers = new Intl.NumberFormat("en-CA");
const areas = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 4 });
const rates = new Intl.NumberFormat("en-CA", { maximumFractionDigits: 1 });
const skySquareDegrees = (4 * 180 ** 2) / Math.PI;
const utc = new Intl.DateTimeFormat("en-CA", {
  dateStyle: "medium",
  timeStyle: "short",
  timeZone: "UTC",
});

function number(value: unknown, format = integers) {
  return finite(value) ? format.format(value) : "—";
}

function absoluteTime(value?: string | null) {
  const timestamp = value ? Date.parse(value) : NaN;
  return finite(timestamp) ? utc.format(timestamp) : "—";
}

function perHour(batch: BulkSurveyBatch) {
  const seconds = finite(batch.wallSeconds)
    ? batch.wallSeconds
    : batch.finishedAt
      ? (Date.parse(batch.finishedAt) - Date.parse(batch.startedAt)) / 1000
      : NaN;
  return seconds > 0 && finite(batch.successful)
    ? (batch.successful * 3600) / seconds
    : null;
}

export default function BulkSurveyView({
  onAtlas,
}: {
  onAtlas?: (ra: number, dec: number, label?: string) => void;
}) {
  const { snapshot, unavailable, reload } = useBulkSurvey();
  const [chart, setChart] = useState<"volume" | "throughput">("volume");
  if (!snapshot) {
    return (
      <div className="stats-notice" role="status">
        {unavailable ? <CircleAlert size={18} /> : <Activity size={18} />}
        <span>
          {unavailable
            ? "The large archive survey snapshot is unavailable."
            : "Loading the large archive survey…"}
        </span>
        {unavailable && (
          <button type="button" className="stats-button" onClick={reload}>
            Try again
          </button>
        )}
      </div>
    );
  }

  const { goal, summary, coverage, inventory, ledgerUrl } = snapshot;
  const incompleteCatalog =
    finite(summary.catalogCompleted) && finite(summary.investigated)
      ? summary.investigated - summary.catalogCompleted
      : null;
  const completion = summary.uniqueProcessed / goal;
  const progress = new Intl.NumberFormat("en-CA", {
    maximumFractionDigits: 4,
    minimumFractionDigits: completion > 0 && completion < 0.0001 ? 4 : 0,
    style: "percent",
  }).format(completion);
  const lastRegion = snapshot.footprints.at(0);
  const finished = [...snapshot.batches]
    .sort((a, b) => Date.parse(a.startedAt) - Date.parse(b.startedAt))
    .slice(-24);
  const plot =
    chart === "volume"
      ? finished.map((batch) => batch.uniqueProcessed)
      : finished.map(perHour);
  const chartMaximum = Math.max(1, ...plot.map((value) => value ?? 0));
  const chartUnit = chart === "volume" ? "new unique images" : "images / hour";
  const countRows = [
    ["Distinct archive images listed", summary.discovered],
    ["Images waiting", summary.pending],
    ["Images being processed", summary.running],
    ["Images with an error", summary.failed],
    ["Images skipped", summary.skipped],
    ["Processing error attempts", summary.errorAttempts],
    ["Interrupted attempts", summary.interrupted],
    ["Processing retries", summary.retries],
  ] as const;
  const motionRows = [
    ["Regions waiting for DeepTrace", summary.fieldsPending],
    ["Incomplete region searches", summary.fieldsIncomplete],
    ["Unsearched planned regions", summary.fieldsUnsearched],
    ["Regions waiting for compatible epochs", summary.fieldsWaitingEpochs],
    ["Regions with a processing error", summary.fieldsFailed],
    ["Completed searches with zero peaks", summary.fieldsEmpty],
    ["Catalog investigations recorded", summary.investigated],
    ["Complete Gaia and JPL investigations", summary.catalogCompleted],
    ["Catalog-check attempts", summary.catalogAttempts],
    ["Catalog-consistent matches", summary.knownMatches],
    ["Unresolved candidates", summary.unresolved],
  ] as const;

  return (
    <div className="bulk-survey">
      <section className="bulk-survey-hero" aria-labelledby="bulk-title">
        <div className="bulk-survey-title">
          <div>
            <h2 id="bulk-title">Large archive survey</h2>
            <p>
              Measured results from the published survey batches over NASA
              SPHEREx DR1 and QR3.
            </p>
          </div>
          <div className="stats-intro-meta">
            <span>Published {absoluteTime(snapshot.generatedAt)} UTC</span>
            <a className="stats-button" download href="/bulk-survey.json">
              <ArrowDownToLine size={15} /> Download results
            </a>
            {ledgerUrl && (
              <a className="stats-button" href={ledgerUrl} download>
                <ArrowDownToLine size={15} /> Download processing ledger
              </a>
            )}
          </div>
        </div>
        <div className="bulk-survey-progress">
          <div>
            <strong>{number(summary.uniqueProcessed)}</strong>
            <span> / {number(goal)} unique NASA images processed</span>
          </div>
          <span>{progress}</span>
        </div>
        <progress
          value={Math.min(summary.uniqueProcessed, goal)}
          max={goal}
          aria-label="Unique observations completed toward the survey goal"
        />
        <p>
          Each observation and detector pair counts once after full-image
          processing.
        </p>
        {unavailable && (
          <p>
            The most recent refresh failed. Showing the last published totals.
          </p>
        )}
      </section>

      <div className="bulk-results" aria-label="Verified survey results">
        <section className="bulk-result-card">
          <h3>
            <Telescope size={16} /> Usable image coverage
          </h3>
          <strong>
            {number(coverage.areaSquareDegrees, areas)} <small>deg²</small>
          </strong>
          <p>
            Overlapping areas count once. Estimated from the native image
            quality masks.
          </p>
        </section>
        <section className="bulk-result-card bulk-result-motion">
          <h3>
            <Crosshair size={16} /> DeepTrace motion search
          </h3>
          <dl>
            <div>
              <dt>Images used</dt>
              <dd>{number(summary.motionInputs)}</dd>
            </div>
            <div>
              <dt>Sky regions searched</dt>
              <dd>{number(summary.regionsAnalyzed)}</dd>
            </div>
          </dl>
          <p>
            <b>{number(coverage.motionAreaSquareDegrees, areas)} deg²</b> of
            common usable coverage across compatible epochs.
          </p>
        </section>
        <section className="bulk-result-card bulk-result-review">
          <h3>
            <Activity size={16} /> Candidate review
          </h3>
          <strong>
            {number(summary.candidates)} <small>preliminary peaks</small>
          </strong>
          <p>
            {number(summary.investigated)} investigated ·{" "}
            {number(incompleteCatalog)} catalog checks incomplete ·{" "}
            {number(summary.knownMatches)} catalog-consistent matches.
          </p>
        </section>
      </div>

      <div className="bulk-survey-grid">
        <section className="stats-panel bulk-survey-panel">
          <div className="stats-panel-header">
            <h3>
              <Telescope size={17} /> Image processing
            </h3>
            <p>
              {number(summary.successfulOperations)} successful image-processing
              operations
            </p>
          </div>
          <CountList values={countRows} />
          {inventory && (
            <p className="stats-plot-note">
              Archive inventory pagination completed for{" "}
              {number(inventory.completedScopes)} of{" "}
              {number(inventory.listedScopes)} requested listings.
              {inventory.errors
                ? ` ${number(inventory.errors)} listing attempts failed.`
                : ""}
            </p>
          )}
        </section>
        <section className="stats-panel bulk-survey-panel">
          <div className="stats-panel-header">
            <h3>
              <Globe2 size={17} /> How coverage is measured
            </h3>
          </div>
          <dl className="bulk-survey-area">
            <div>
              <dt>Unique area with usable image samples</dt>
              <dd>{number(coverage.areaSquareDegrees, areas)} deg²</dd>
            </div>
            {finite(coverage.areaSquareDegrees) && (
              <div>
                <dt>Share of the celestial sphere</dt>
                <dd>
                  {number(
                    (100 * coverage.areaSquareDegrees) / skySquareDegrees,
                    areas,
                  )}
                  %
                </dd>
              </div>
            )}
            <div>
              <dt>Area searched for motion</dt>
              <dd>{number(coverage.motionAreaSquareDegrees, areas)} deg²</dd>
            </div>
          </dl>
          <p className="stats-plot-note">{coverage.method}</p>
          {finite(coverage.cellAreaSquareDegrees) && (
            <p className="stats-plot-note">
              Grid cells are {number(coverage.cellAreaSquareDegrees, areas)}{" "}
              deg². Grid resolution limits the precision of the area estimate.
            </p>
          )}
          {lastRegion && onAtlas && (
            <button
              className="stats-button"
              type="button"
              onClick={() =>
                onAtlas(
                  lastRegion.ra,
                  lastRegion.dec,
                  "Processed SPHEREx region",
                )
              }
            >
              <Map size={15} /> View coverage in Sky Atlas
            </button>
          )}
        </section>
        <section className="stats-panel bulk-survey-panel">
          <div className="stats-panel-header">
            <h3>
              <Crosshair size={17} /> Motion survey and catalog review
            </h3>
            <p>DeepTrace uses compatible, overlapping epochs.</p>
          </div>
          <CountList values={motionRows} />
          <a className="stats-button" href="/?page=survey">
            <Crosshair size={15} /> Open discovery records
          </a>
        </section>
        <section className="stats-panel bulk-survey-panel">
          <div className="stats-panel-header">
            <h3>
              <Activity size={17} /> Scientific limits
            </h3>
            <p>See Validation for empirical injection recovery and controls.</p>
          </div>
          {snapshot.limitations.length > 0 && (
            <ul className="bulk-survey-limits">
              {snapshot.limitations.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="stats-panel bulk-survey-panel">
        <div className="stats-panel-header">
          <h3>Processing history</h3>
          <p>
            Recent worker batches in UTC. Throughput uses successful image
            operations divided by each batch’s wall time.
          </p>
        </div>
        {finished.length ? (
          <>
            <div
              className="stats-tabs bulk-survey-switch"
              aria-label="Batch chart metric"
            >
              <button
                type="button"
                aria-pressed={chart === "volume"}
                onClick={() => setChart("volume")}
              >
                New unique images
              </button>
              <button
                type="button"
                aria-pressed={chart === "throughput"}
                onClick={() => setChart("throughput")}
              >
                Throughput
              </button>
            </div>
            <div className="bulk-survey-bars" aria-hidden="true">
              {finished.map((batch, i) => (
                <div
                  key={batch.id}
                  title={`${absoluteTime(batch.startedAt)} · ${number(plot[i], rates)} ${chartUnit}`}
                >
                  <span
                    style={{
                      height: `${((plot[i] ?? 0) * 100) / chartMaximum}%`,
                    }}
                  />
                </div>
              ))}
            </div>
            <div className="stats-table-scroll" tabIndex={0}>
              <table className="stats-table bulk-survey-table">
                <thead>
                  <tr>
                    <th scope="col">Started UTC</th>
                    <th scope="col">Finished UTC</th>
                    <th scope="col">Workers</th>
                    <th scope="col">Successful images</th>
                    <th scope="col">New unique</th>
                    <th scope="col">Images / hour</th>
                    <th scope="col">Errors</th>
                    <th scope="col">Skipped</th>
                    <th scope="col">Interrupted</th>
                    <th scope="col">Retries</th>
                  </tr>
                </thead>
                <tbody>
                  {[...finished].reverse().map((batch) => (
                    <tr key={batch.id}>
                      <td>{absoluteTime(batch.startedAt)}</td>
                      <td>{absoluteTime(batch.finishedAt)}</td>
                      <td>{number(batch.workers)}</td>
                      <td>{number(batch.successful)}</td>
                      <td>{number(batch.uniqueProcessed)}</td>
                      <td>{number(perHour(batch), rates)}</td>
                      <td>{number(batch.failed)}</td>
                      <td>{number(batch.skipped)}</td>
                      <td>{number(batch.interrupted)}</td>
                      <td>{number(batch.retries)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="stats-plot-note">
            No worker batches have been published.
          </p>
        )}
      </section>
    </div>
  );
}

function CountList({
  values,
}: {
  values: ReadonlyArray<readonly [string, unknown]>;
}) {
  return (
    <dl className="bulk-survey-counts">
      {values.map(([name, value]) => (
        <div key={name}>
          <dt>{name}</dt>
          <dd>{number(value)}</dd>
        </div>
      ))}
    </dl>
  );
}
