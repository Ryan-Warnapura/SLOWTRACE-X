import { useEffect, useMemo, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Compass,
  Crosshair,
  ExternalLink,
  Layers3,
  Minus,
  Orbit,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Telescope,
} from "lucide-react";
import { download, fmt, request } from "./lib";
import type { Candidate, SurveySnapshot } from "./surveyTypes";
import Scene, { type SolarView } from "./solar/Scene";
import {
  BODY_COLORS,
  currentJD,
  dateForJD,
  positionAt,
  solarAssociation,
  type CandidateDirection,
  type SolarEphemerides,
} from "./solar/ephemeris";
import "./solar/solar.css";

export interface SolarSystemProps {
  focus?: CandidateDirection;
  onCandidate?: (id: string) => void;
  onObserve?: (ra: number, dec: number) => void;
}

export default function SolarSystem({
  focus,
  onCandidate,
  onObserve,
}: SolarSystemProps) {
  const [data, setData] = useState<SolarEphemerides | null>(null);
  const [error, setError] = useState("");
  const [finding, setFinding] = useState<Candidate | null>(null);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState("earth");
  const [view, setView] = useState<SolarView>(focus ? "direction" : "inner");
  const [jd, setJD] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [paths, setPaths] = useState(true);
  const [labels, setLabels] = useState(true);
  const [renderFail, setRenderFail] = useState(false);
  const [zoomSignal, setZoomSignal] = useState({ count: 0, amount: 1 });
  const [resetSignal, setResetSignal] = useState(0);
  const reference = focus?.id;
  const focusRa = focus?.ra,
    focusDec = focus?.dec;
  const focusLabel = focus?.label;

  useEffect(() => {
    const controller = new AbortController();
    request<SolarEphemerides>("/solar/horizons.json", {
      signal: controller.signal,
    })
      .then((next) => {
        const times = next.bodies.earth.samples;
        if (!times.length)
          throw new Error("The ephemeris contains no Earth samples.");
        setData(next);
        setJD(
          Math.min(
            times[times.length - 1][0],
            Math.max(times[0][0], Math.floor(currentJD() - 0.5) + 0.5),
          ),
        );
      })
      .catch((reason) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Could not load Horizons ephemerides.",
          );
      });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (!reference) return;
    const controller = new AbortController();
    request<SurveySnapshot>("/survey.json", { signal: controller.signal })
      .then((record) => {
        if (!controller.signal.aborted) {
          setFinding(
            record.candidates.find((candidate) => candidate.id === reference) ??
              null,
          );
        }
      })
      .catch(() => {});
    return () => controller.abort();
  }, [reference]);

  useEffect(() => {
    if (typeof focusRa === "number" && typeof focusDec === "number") {
      setView("direction");
      setPlaying(false);
    }
  }, [reference, focusRa, focusDec]);

  const stableFocus = useMemo(
    () =>
      typeof focusRa === "number" && typeof focusDec === "number"
        ? { id: reference, ra: focusRa, dec: focusDec, label: focusLabel }
        : undefined,
    [reference, focusRa, focusDec, focusLabel],
  );
  const start = data?.bodies.earth.samples[0][0] ?? 0;
  const end = data?.bodies.earth.samples.at(-1)?.[0] ?? 0;
  useEffect(() => {
    if (!playing || view === "direction") return;
    const timer = window.setInterval(() => {
      if (document.hidden) return;
      setJD((previous) => (previous + 1 > end ? start : previous + 1));
    }, 160);
    return () => window.clearInterval(timer);
  }, [playing, start, end, view]);

  function setMode(next: SolarView) {
    setView(next);
    setPlaying(false);
  }
  function chooseBody(id: string) {
    setSelected(id);
    const body = data?.bodies[id];
    const coords = body ? positionAt(body.samples, jd) : null;
    if (view === "inner" && coords && Math.hypot(...coords) > 6)
      setMode("outer");
  }
  function adjustDay(value: number) {
    setPlaying(false);
    setJD(Math.min(end, Math.max(start, value)));
  }
  function zoom(amount: number) {
    setZoomSignal(({ count }) => ({ count: count + 1, amount }));
  }
  function downloadEvidence() {
    if (!data) return;
    download("slowtrace-horizons-reference.json", {
      ...data,
      selectedDate: dateForJD(jd),
      interpolation:
        "Linear Cartesian interpolation between adjacent 2-day samples. No extrapolation.",
    });
  }

  if (!data)
    return (
      <section className="solar-loading panel" role="status">
        <Orbit size={30} />
        <div>
          <h2>
            {error
              ? "Ephemerides unavailable"
              : "Loading JPL Horizons ephemerides"}
          </h2>
          {error && (
            <>
              <p>{error}</p>
              <button
                className="secondary"
                onClick={() => {
                  setError("");
                  setRetry((v) => v + 1);
                }}
              >
                Retry
              </button>
            </>
          )}
        </div>
      </section>
    );
  const dir = view === "direction" && stableFocus;
  const linkedFinding = finding?.id === reference ? finding : null;
  const association = solarAssociation(linkedFinding, data.bodies);
  const matchedId = association?.bodyId;
  const matchedBody = matchedId ? data.bodies[matchedId] : null;
  function showCatalogBody() {
    if (!matchedId || !matchedBody) return;
    const referenceDay =
      Math.floor(linkedFinding?.referenceMjd ?? NaN) + 2400000.5;
    const selectedDay =
      referenceDay >= start && referenceDay <= end ? referenceDay : jd;
    const position = positionAt(matchedBody.samples, selectedDay);
    if (!position) return;
    setSelected(matchedId);
    setJD(selectedDay);
    setMode(Math.hypot(...position) > 6 ? "outer" : "inner");
  }
  const body = data.bodies[selected];
  const coords =
    selected === "sun" ? [0, 0, 0] : body ? positionAt(body.samples, jd) : null;
  const computed = (jd - start) % data.stepDays !== 0;
  const dateString = dateForJD(jd);

  return (
    <div className="solar-workbench">
      <section
        className="solar-visual"
        aria-label="Interactive solar system reference"
      >
        <div className="solar-toolbar">
          <div className="solar-source">
            <span>
              {dir
                ? "Angular direction in ICRS"
                : "Positions from NASA/JPL Horizons"}
            </span>
          </div>
          <div className="solar-mode" aria-label="Solar system view">
            <button
              aria-pressed={view === "inner"}
              onClick={() => setMode("inner")}
            >
              Inner system
            </button>
            <button
              aria-pressed={view === "outer"}
              onClick={() => setMode("outer")}
            >
              Outer system
            </button>
            {stableFocus && (
              <button
                aria-pressed={view === "direction"}
                onClick={() => setMode("direction")}
              >
                Candidate direction
              </button>
            )}
          </div>
        </div>
        <div className="solar-stage-shell">
          <div className="solar-graphic-key">
            <span className="solar-status-dot" />
            {dir
              ? "Unit direction, no distance axis"
              : "Geometric heliocentric positions, in au"}
          </div>
          {renderFail ? (
            <PlanarFallback
              data={data}
              view={view}
              direction={stableFocus}
              jd={jd}
              paths={paths}
              selected={selected}
              onSelect={chooseBody}
            />
          ) : (
            <Scene
              data={data}
              view={view}
              focus={stableFocus}
              state={{ jd, selected, labels, paths }}
              onSelect={chooseBody}
              onFail={() => setRenderFail(true)}
              zoomSignal={zoomSignal}
              resetSignal={resetSignal}
            />
          )}
          {!renderFail && (
            <div className="solar-camera" aria-label="Camera controls">
              <button aria-label="Zoom in" onClick={() => zoom(0.77)}>
                <Plus size={16} />
              </button>
              <button aria-label="Zoom out" onClick={() => zoom(1 / 0.77)}>
                <Minus size={16} />
              </button>
              <button
                aria-label="Reset camera"
                onClick={() => setResetSignal((v) => v + 1)}
              >
                <RotateCcw size={15} />
              </button>
            </div>
          )}
          <div className="solar-stage-note">
            {renderFail
              ? "Planar fallback, 3D rendering unavailable"
              : dir
                ? "Drag to rotate the direction sphere"
                : "Drag to rotate, pinch or scroll to zoom"}
          </div>
        </div>
        {!dir && (
          <div className="solar-timeline">
            <div className="solar-timeline-top">
              <div className="solar-player">
                <button
                  className="solar-play"
                  aria-label={
                    playing
                      ? "Pause ephemeris playback"
                      : "Play ephemeris playback"
                  }
                  onClick={() => setPlaying((v) => !v)}
                >
                  {playing ? <Pause size={16} /> : <Play size={16} />}
                </button>
                <button
                  aria-label="Previous ephemeris day"
                  onClick={() => adjustDay(jd - 1)}
                  disabled={jd <= start}
                >
                  <ChevronLeft size={17} />
                </button>
                <button
                  aria-label="Next ephemeris day"
                  onClick={() => adjustDay(jd + 1)}
                  disabled={jd >= end}
                >
                  <ChevronRight size={17} />
                </button>
                <b aria-live={playing ? "off" : "polite"}>
                  {dateString} <small>UTC</small>
                </b>
              </div>
              <span>
                {computed
                  ? "Interpolated between samples"
                  : "Horizons sample epoch"}
              </span>
            </div>
            <input
              aria-label="Ephemeris date"
              aria-valuetext={`${dateString} UTC`}
              type="range"
              min={start}
              max={end}
              step={1}
              value={jd}
              onChange={(event) => adjustDay(Number(event.target.value))}
            />
            <div className="solar-range">
              <span>{dateForJD(start)}</span>
              <span>{dateForJD(end)}</span>
            </div>
          </div>
        )}
        <div className="solar-underbar">
          <span>
            {dir
              ? "J2000 equatorial direction display"
              : "Positions to scale, marker sizes illustrative"}
          </span>
          <div>
            {!dir && (
              <label>
                <Layers3 size={13} />
                <input
                  type="checkbox"
                  checked={paths}
                  onChange={(e) => setPaths(e.target.checked)}
                />{" "}
                Sampled paths
              </label>
            )}
            <label>
              <input
                type="checkbox"
                checked={labels}
                onChange={(e) => setLabels(e.target.checked)}
              />{" "}
              Labels
            </label>
          </div>
        </div>
      </section>

      <aside className="solar-inspector" aria-label="Object inspector">
        {dir ? (
          <>
            <p className="solar-inspector-kicker">DeepTrace sky direction</p>
            <h2>{dir.label || dir.id || "Selected sky direction"}</h2>
            <p>
              This ray represents the candidate’s published ICRS direction. Its
              length is a drawing convention. The observations provide no
              physical distance or orbit.
            </p>
            <dl className="solar-measurements">
              <div>
                <dt>Right ascension</dt>
                <dd>{fmt(dir.ra, 6)}°</dd>
              </div>
              <div>
                <dt>Declination</dt>
                <dd>{fmt(dir.dec, 6)}°</dd>
              </div>
              <div>
                <dt>Distance</dt>
                <dd>Unconstrained</dd>
              </div>
            </dl>
            {association && (
              <div className="solar-catalog-context">
                <strong>Catalog association: {association.name}</strong>
                <p>
                  Published position checks support this association at the
                  measured epochs.{" "}
                  {matchedBody
                    ? "Open the catalog object’s sampled heliocentric positions."
                    : "Open the original JPL observer ephemeris for this target."}
                </p>
                <div className="solar-link-list">
                  {matchedBody && association.bodyId && (
                    <button className="secondary" onClick={showCatalogBody}>
                      <Orbit size={15} /> Explore {matchedBody.name} in 3D
                    </button>
                  )}
                  <a
                    href={association.evidenceUrl}
                    target="_blank"
                    rel="noreferrer"
                  >
                    JPL positions at the measured epochs{" "}
                    <ExternalLink size={13} />
                  </a>
                </div>
              </div>
            )}
            <div className="solar-link-list">
              {dir.id && onCandidate && (
                <button
                  className="secondary"
                  onClick={() => onCandidate(dir.id!)}
                >
                  Candidate evidence <ArrowRight size={15} />
                </button>
              )}
              {onObserve && (
                <button
                  className="secondary"
                  onClick={() => onObserve(dir.ra, dir.dec)}
                >
                  <Telescope size={15} /> Inspect sky field
                </button>
              )}
            </div>
          </>
        ) : (
          <>
            <h2>
              <span
                style={{ background: BODY_COLORS[selected] || "#efede6" }}
              />
              {body?.name ?? "Sun"}
            </h2>
            <p>
              {body?.classification ?? "Star and coordinate origin"},{" "}
              {computed ? "interpolated position" : "sampled position"}
            </p>
            {coords && (
              <dl className="solar-measurements">
                <div>
                  <dt>Distance from Sun</dt>
                  <dd>{fmt(Math.hypot(...coords), 3)} au</dd>
                </div>
                {coords.map((v, i) => (
                  <div key={i}>
                    <dt>{["Ecliptic X", "Ecliptic Y", "Ecliptic Z"][i]}</dt>
                    <dd>{fmt(v, 4)} au</dd>
                  </div>
                ))}
              </dl>
            )}
            <div className="solar-body-list" aria-label="Ephemeris objects">
              {[
                ["sun", "Sun"],
                ...Object.entries(data.bodies).map(([id, b]) => [id, b.name]),
              ].map(([id, name]) => (
                <button
                  key={id}
                  onClick={() => chooseBody(id)}
                  aria-pressed={selected === id}
                >
                  <span style={{ background: BODY_COLORS[id] || "#efede6" }} />
                  {name}
                </button>
              ))}
            </div>
            <div className="solar-link-list">
              {association?.bodyId === selected &&
                linkedFinding?.id &&
                onCandidate && (
                  <button
                    className="secondary"
                    onClick={() => onCandidate(linkedFinding.id)}
                  >
                    Candidate evidence <ArrowRight size={15} />
                  </button>
                )}
              {body && (
                <a href={body.source} target="_blank" rel="noreferrer">
                  Original Horizons query <ExternalLink size={13} />
                </a>
              )}
              {selected === "interstellar" && (
                <a
                  href="https://irsa.ipac.caltech.edu/data/SPHEREx/docs/comet3iatlas/index.html"
                  target="_blank"
                  rel="noreferrer"
                >
                  NASA SPHEREx observations of 3I/ATLAS{" "}
                  <ExternalLink size={13} />
                </a>
              )}
              <button className="text-button" onClick={downloadEvidence}>
                <ArrowDownToLine size={14} /> Export ephemerides
              </button>
            </div>
          </>
        )}
      </aside>
      <div className="solar-provenance">
        <Compass size={17} />
        <p>
          <strong>
            {dir
              ? "How to read the sky direction"
              : "How to read the orbital reference"}
          </strong>
          {dir
            ? "Earth supplies a reference origin for the display. The direction comes from the SPHEREx field and has no observer correction. The unit sphere carries no distance scale."
            : `The paths connect geometric position vectors in the J2000 ecliptic frame. Bodies share one display date. The viewer linearly interpolates between two-day samples. Outer paths show arcs over the sampled window. JPL data retrieved ${data.retrievedAt.slice(0, 10)} UTC.`}
        </p>
        <a href={data.sourceHome} target="_blank" rel="noreferrer">
          NASA/JPL Horizons <ExternalLink size={12} />
        </a>
      </div>
    </div>
  );
}

function PlanarFallback({
  data,
  view,
  direction,
  jd,
  paths,
  selected,
  onSelect,
}: {
  data: SolarEphemerides;
  view: SolarView;
  direction?: CandidateDirection;
  jd: number;
  paths: boolean;
  selected: string;
  onSelect: (id: string) => void;
}) {
  if (view === "direction" && direction)
    return (
      <div className="solar-direction-fallback">
        <Crosshair size={36} />
        <strong>
          {fmt(direction.ra, 5)}° RA, {fmt(direction.dec, 5)}° Dec
        </strong>
        <span>ICRS sky direction only</span>
      </div>
    );
  const scale = view === "outer" ? 32 : 6;
  return (
    <svg
      className="solar-fallback-svg"
      viewBox={`${-scale} ${-scale} ${scale * 2} ${scale * 2}`}
      role="img"
      aria-label="Top-down JPL heliocentric ephemeris reference"
    >
      {[0.25, 0.5, 0.75, 0.95].map((r) => (
        <circle
          key={r}
          r={r * scale}
          fill="none"
          stroke="#363a40"
          strokeWidth={scale * 0.003}
        />
      ))}
      {Object.entries(data.bodies).map(([id, body]) => {
        const coords = positionAt(body.samples, jd),
          color = BODY_COLORS[id] || "#efede6";
        if (!coords) return null;
        return (
          <g key={id}>
            {paths && (
              <polyline
                fill="none"
                stroke={color}
                opacity={selected === id ? 0.8 : 0.27}
                strokeWidth={scale * 0.004}
                points={body.samples.map(([, x, y]) => `${x},${-y}`).join(" ")}
              />
            )}
            <circle
              cx={coords[0]}
              cy={-coords[1]}
              r={scale * (selected === id ? 0.02 : 0.014)}
              fill={color}
              onClick={() => onSelect(id)}
            >
              <title>{body.name}</title>
            </circle>
          </g>
        );
      })}
      <circle
        r={scale * 0.028}
        fill={BODY_COLORS.sun}
        onClick={() => onSelect("sun")}
      >
        <title>Sun</title>
      </circle>
    </svg>
  );
}
