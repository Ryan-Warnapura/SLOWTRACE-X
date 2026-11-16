import { useEffect, useMemo, useState } from "react";
import type { CSSProperties, FormEvent } from "react";
import SkyCanvas from "./SkyCanvas";
import { date, fmt, quantile, request } from "./lib";
import { parseCoordinate } from "./observation";
import { TARGET_PLATES } from "./mission/targetPlates";
import { DETECTORS, TARGETS } from "./types";
import type { Frame } from "./types";
import type { SurveySnapshot } from "./surveyTypes";
import { BAND_COLORS, wavelengthColor } from "./wavelength";

type MissionDestination =
  | "observe"
  | "atlas"
  | "spectra"
  | "trace"
  | "lab"
  | "notebook"
  | "planner"
  | "survey"
  | "stats"
  | "solar"
  | "methods";

const TOOLS: [MissionDestination, string, string][] = [
  [
    "observe",
    "Observe",
    "Blink, subtract and overlay exposures of any position. Step by date, match wavelengths, open the original FITS file.",
  ],
  [
    "atlas",
    "Sky Atlas",
    "Find a position on a globe or a flat map of the sky and open the exposures behind it.",
  ],
  [
    "spectra",
    "Spectra",
    "Measure the brightness at one point in every loaded exposure, by wavelength or by date.",
  ],
  [
    "trace",
    "DeepTrace",
    "Shift and stack exposures along trial motions to bring out sources too faint for a single frame.",
  ],
  [
    "lab",
    "Experiment lab",
    "Inject synthetic moving sources into real exposures and count how many the search recovers.",
  ],
  [
    "notebook",
    "Notebook",
    "Record what you see with the source files attached. Notes stay in your browser.",
  ],
  [
    "planner",
    "Planner",
    "Work out when a position is high in a dark sky from your observing site.",
  ],
  [
    "survey",
    "Discoveries",
    "Browse every field the automated survey processed and the trial peaks it kept, with catalog checks.",
  ],
  [
    "stats",
    "Statistics",
    "The survey's measured coverage and detections, and the injection study behind them.",
  ],
  [
    "solar",
    "Solar System",
    "See where the planets are from JPL Horizons and how a candidate sightline passes through.",
  ],
  [
    "methods",
    "Methods",
    "What the tool reads, what it calculates, and what it does not claim.",
  ],
];

const band = (color: string) => ({ "--band": color }) as CSSProperties;

export default function MissionHome({
  onNavigate,
  onExample,
  onPosition,
}: {
  onNavigate: (page: MissionDestination) => void;
  onExample: (index: number) => void;
  onPosition: (ra: number, dec: number) => void;
}) {
  const [survey, setSurvey] = useState<SurveySnapshot | null>(null);
  const [frames, setFrames] = useState<Frame[]>([]);
  const [active, setActive] = useState(0);
  const [ra, setRa] = useState("");
  const [dec, setDec] = useState("");
  const [problem, setProblem] = useState("");
  useEffect(() => {
    const cancellation = new AbortController();
    request<SurveySnapshot>("/survey.json", { signal: cancellation.signal })
      .then(setSurvey)
      .catch(() => {});
    request<{ frames: Frame[] }>("/examples/wise0855.json", {
      signal: cancellation.signal,
    })
      .then((data) => setFrames(data.frames))
      .catch(() => {});
    return () => cancellation.abort();
  }, []);
  const scale = useMemo<[number, number] | undefined>(() => {
    if (!frames.length) return;
    const values = frames.flatMap((frame) =>
      frame.data.filter((value): value is number => value !== null),
    );
    return [quantile(values, 0.02), quantile(values, 0.995)];
  }, [frames]);
  const frame = frames[active];
  const metrics = survey?.summary;
  const barnard = TARGET_PLATES[0];

  function openPosition(event: FormEvent) {
    event.preventDefault();
    try {
      onPosition(parseCoordinate(ra, "ra"), parseCoordinate(dec, "dec"));
    } catch (error) {
      setProblem((error as Error).message);
    }
  }

  return (
    <div className="mission">
      <section className="m-hero" aria-labelledby="mission-title">
        <div className="m-hero-copy">
          <h1 id="mission-title">Blink the infrared sky</h1>
          <p className="lede">
            SLOWTRACE X lines up real NASA SPHEREx exposures of one patch of
            sky, taken months apart, and flicks between them. Anything that
            moved or changed brightness stands out. That is how Pluto was found
            in 1930, and how you would look for a distant planet today.
          </p>
          <form className="m-open" onSubmit={openPosition}>
            <label>
              Right ascension
              <input
                type="text"
                required
                placeholder="269.4462"
                value={ra}
                onChange={(e) => setRa(e.target.value)}
              />
            </label>
            <label>
              Declination
              <input
                type="text"
                required
                placeholder="4.76883"
                value={dec}
                onChange={(e) => setDec(e.target.value)}
              />
            </label>
            <button type="submit" className="btn btn-primary">
              Open in the blink viewer
            </button>
          </form>
          {problem ? (
            <p className="m-open-note" role="alert">
              {problem}
            </p>
          ) : (
            <p className="m-open-note">
              ICRS, in decimal degrees or as 17h57m48s and +04d41m36s. Or open{" "}
              <button className="inline-link" onClick={() => onExample(0)}>
                Barnard’s Star
              </button>
              , which loads recorded exposures at once.
            </p>
          )}
        </div>
        <div className="m-hero-plates">
          <figure className="figure m-allsky">
            <img
              src="/images/spherex-allsky.webp"
              alt="Oval map of the whole sky in infrared light. The Milky Way runs across the middle as a bright band wrapped in orange dust clouds."
              width={2133}
              height={1200}
              fetchPriority="high"
            />
            <figcaption>
              <strong>
                The whole sky in infrared, from SPHEREx’s first all-sky map.
              </strong>{" "}
              <a
                href="https://www.jpl.nasa.gov/images/pia26600-spherexs-first-all-sky-map/"
                target="_blank"
                rel="noreferrer"
              >
                NASA/JPL-Caltech
              </a>
            </figcaption>
          </figure>
          <figure className="m-inset">
            <div className="m-blink">
              <img src={barnard.epochs[0].src} alt="" width={96} height={96} />
              <img
                src={barnard.epochs[1].src}
                alt="SPHEREx cutout around Barnard’s Star, alternating between two dates a year apart"
                width={96}
                height={96}
              />
            </div>
            <figcaption>
              <strong className="object-name">Barnard’s Star</strong>
              <span>A 5 arcmin patch of that sky</span>
              <span className="num">
                {barnard.epochs[0].date}, {barnard.epochs[1].date}
              </span>
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="m-section" aria-labelledby="targets-title">
        <header className="m-head">
          <h2 id="targets-title">Five challenge targets</h2>
          <p>
            The Planet X and SPHEREx challenge names five objects to test a
            tool on. Each one opens with recorded NASA exposures, so it works
            even when the archive is slow.
          </p>
        </header>
        <ul className="m-targets">
          {TARGETS.map((target, index) => {
            const plate = TARGET_PLATES[index];
            const [first, last] = plate.epochs;
            return (
              <li key={target.name}>
                <button
                  className="m-target"
                  onClick={() => onExample(index)}
                  aria-label={`Open ${target.name} in the blink viewer`}
                >
                  <span className="m-blink">
                    <img src={first.src} alt="" width={96} height={96} />
                    <img src={last.src} alt="" width={96} height={96} />
                  </span>
                  <strong className="object-name">{target.name}</strong>
                  <span className="m-target-kind">{target.type}</span>
                  <span className="m-target-data">
                    <span className="num">
                      {fmt(target.ra, 4)}°, {fmt(target.dec, 4)}°
                    </span>
                    <span
                      className="band"
                      style={band(wavelengthColor(first.wavelength))}
                    >
                      D{first.detector}, {plate.count} exposures
                    </span>
                    <span className="num">
                      {first.date} to {last.date}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
        <p className="credit">
          Target images are SPHEREx cutouts from NASA/IPAC IRSA, shown at
          native pixel scale. Hover a plate to blink its two dates.
        </p>
      </section>

      <section
        className="m-section m-guide"
        id="mission-guide"
        aria-labelledby="mission-guide-title"
      >
        <div className="m-guide-copy">
          <h2 id="mission-guide-title">One field, two dates</h2>
          <p>
            This field contains the infrared brown dwarf WISE 0855. Switch
            between the two observations and look for stable stars to orient
            yourself. A brightness change can come from wavelength, detector
            response, or a real change in the sky.
          </p>
          <ol>
            <li>Compare the dates at the same display stretch.</li>
            <li>Check the selected wavelength and quality flags.</li>
            <li>Open both source exposures and record what you notice.</li>
          </ol>
          <button className="btn" onClick={() => onExample(2)}>
            Investigate WISE 0855
          </button>
        </div>
        <div className="m-demo">
          <SkyCanvas
            frame={frame}
            mode="blink"
            contrast={1}
            palette="mono"
            scale={scale}
            point={null}
            caption={
              frame && (
                <>
                  <strong>WISE 0855−0714</strong>
                  <span className="num">{frame.metadata.date.slice(0, 10)}</span>
                  <span
                    className="band"
                    style={band(wavelengthColor(frame.metadata.wavelengthCenter))}
                  >
                    D{frame.metadata.detector},{" "}
                    {fmt(frame.metadata.wavelengthCenter, 3)} µm
                  </span>
                </>
              )
            }
          />
          <div className="m-demo-controls">
            <div className="seg" role="group" aria-label="Observation date">
              {frames.map((item, index) => (
                <button
                  key={item.provenance.sourceUrl}
                  aria-pressed={index === active}
                  onClick={() => setActive(index)}
                >
                  {date(item.metadata.mjd)}
                </button>
              ))}
            </div>
            {frame && (
              <a
                className="inline-link"
                href={frame.provenance.sourceUrl}
                target="_blank"
                rel="noreferrer"
              >
                Original FITS file
              </a>
            )}
          </div>
        </div>
      </section>

      <section className="m-section" aria-labelledby="tools-title">
        <header className="m-head">
          <h2 id="tools-title">What you can do here</h2>
          <p>
            Eleven tools share one field. Load a position once and carry it
            from the viewer to the search, the spectrum and your notes.
          </p>
        </header>
        <ul className="m-tools">
          {TOOLS.map(([page, name, text]) => (
            <li key={page}>
              <button onClick={() => onNavigate(page)}>
                <strong>{name}</strong>
                <span>{text}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="m-section m-telescope" aria-labelledby="scope-title">
        <header className="m-head">
          <h2 id="scope-title">The telescope behind the pixels</h2>
          <p>
            SPHEREx is a NASA space telescope that photographs the whole sky
            every six months. Each exposure lands on six detectors at once. A
            filter over each detector changes gradually from one edge to the
            other, so every pixel sees a slightly different infrared
            wavelength: 102 of them between 0.75 and 5.0 microns.
          </p>
        </header>
        <div className="m-telescope-grid">
          <figure className="figure m-scope-main">
            <img
              src="/images/spherex-observatory.webp"
              alt="The SPHEREx spacecraft lying on its side in a clean room, its three nested mirror-finish cones facing the camera under red and blue light."
              width={1536}
              height={1024}
              loading="lazy"
            />
            <figcaption>
              <strong>
                The observatory after environmental testing, November 2024. Its
                three nested cones shade the telescope from the Sun and Earth.
              </strong>{" "}
              <a
                href="https://images.nasa.gov/details/PIA26536"
                target="_blank"
                rel="noreferrer"
              >
                NASA/JPL-Caltech/BAE Systems
              </a>
            </figcaption>
          </figure>
          <figure className="figure">
            <img
              src="/images/spherex-first-light.webp"
              alt="Six square star fields in a three by two grid, tinted violet, blue, green, yellow-green, gold and red."
              width={1600}
              height={1036}
              loading="lazy"
            />
            <figcaption>
              <strong>
                One exposure, six detectors, 27 March 2025. The tints stand for
                infrared wavelengths, shortest at top left.
              </strong>{" "}
              <a
                href="https://images.nasa.gov/details/PIA26280"
                target="_blank"
                rel="noreferrer"
              >
                NASA/JPL-Caltech
              </a>
            </figcaption>
          </figure>
          <div className="m-bands">
            <h3 className="title-module">Why every exposure carries a colour</h3>
            <p>
              Two exposures of the same star can differ only because they were
              taken at different wavelengths. SLOWTRACE X marks each exposure
              with the colour of its band, taken from the tints above, so you
              can tell a real change from a change of filter.
            </p>
            <dl className="kv">
              {DETECTORS.map((range, index) => (
                <div key={range}>
                  <dt>
                    <span className="band" style={band(BAND_COLORS[index])}>
                      Detector {index + 1}
                    </span>
                  </dt>
                  <dd>{range} µm</dd>
                </div>
              ))}
            </dl>
          </div>
          <figure className="figure">
            <img
              src="/images/spherex-filters.webp"
              alt="Three iridescent rectangular filters mounted in a metal frame on a blue background."
              width={1280}
              height={959}
              loading="lazy"
            />
            <figcaption>
              <strong>
                The filters that sit over the detectors. Each is about the size
                of a cracker.
              </strong>{" "}
              <a
                href="https://images.nasa.gov/details/PIA25788"
                target="_blank"
                rel="noreferrer"
              >
                NASA/JPL-Caltech
              </a>
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="m-section m-survey" aria-label="Published survey">
        <header className="m-head">
          <h2>{survey?.label ?? "Published survey"}</h2>
          <p>
            An automated run of the same search over archive fields.
            {survey && ` Published ${date(survey.generatedAt)}.`} Its trial
            peaks are measurements to check, not discoveries.
          </p>
        </header>
        <dl className="m-figures">
          <div>
            <dd>{metrics?.fieldsAnalyzed?.toLocaleString() ?? "—"}</dd>
            <dt>Fields analyzed</dt>
          </div>
          <div>
            <dd>{metrics?.uniqueExposuresAnalyzed?.toLocaleString() ?? "—"}</dd>
            <dt>Distinct exposures</dt>
          </div>
          <div>
            <dd>{metrics?.candidates?.toLocaleString() ?? "—"}</dd>
            <dt>Trial peaks retained</dt>
          </div>
        </dl>
        <div className="m-actions">
          <button className="btn" onClick={() => onNavigate("survey")}>
            Browse the discoveries
          </button>
          <button className="btn" onClick={() => onNavigate("stats")}>
            View the statistics
          </button>
        </div>
      </section>

      <section className="m-close" aria-labelledby="close-title">
        <figure className="figure">
          <img
            src="/images/spherex-vela.webp"
            alt="A wide star field crowded with blue, green and red stars, with a yellow-orange nebula at the right."
            width={1600}
            height={791}
            loading="lazy"
          />
          <figcaption>
            <strong>
              The Vela Molecular Ridge, from SPHEREx’s first public data
              release in July 2025.
            </strong>{" "}
            <a
              href="https://images.nasa.gov/details/PIA26354"
              target="_blank"
              rel="noreferrer"
            >
              NASA/JPL-Caltech
            </a>
          </figcaption>
        </figure>
        <div className="m-close-copy">
          <h2 id="close-title">Pick a patch of sky</h2>
          <p>
            Start from a named target, a place on the atlas, or coordinates of
            your own.
          </p>
          <div className="m-actions">
            <button
              className="btn btn-primary"
              onClick={() => onNavigate("observe")}
            >
              Open the blink viewer
            </button>
            <button className="btn" onClick={() => onNavigate("atlas")}>
              Explore the sky atlas
            </button>
          </div>
        </div>
      </section>
    </div>
  );
}
