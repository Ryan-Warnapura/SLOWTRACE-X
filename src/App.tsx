import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  CircleHelp,
  Compass,
  Crosshair,
  ExternalLink,
  FlaskConical,
  Globe2,
  Layers3,
  LoaderCircle,
  Menu,
  NotebookPen,
  Pause,
  Play,
  ScanLine,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Telescope,
  Waves,
  X,
} from "lucide-react";
import { Tooltip } from "@base-ui/react/tooltip";
import { toast } from "sonner";
import SkyCanvas from "./SkyCanvas";
const SpectrumChart = lazy(() =>
  import("./Charts").then((m) => ({ default: m.SpectrumChart })),
);
const PlannerChart = lazy(() =>
  import("./Charts").then((m) => ({ default: m.PlannerChart })),
);
import Atlas from "./Atlas";
import {
  aperture,
  date,
  download,
  fmt,
  pixelSky,
  post,
  quantile,
  request,
} from "./lib";
import { DETECTORS, TARGETS } from "./types";
import type { Frame, Observation, Query, SearchResult } from "./types";

type Page =
  | "observe"
  | "atlas"
  | "trace"
  | "spectra"
  | "lab"
  | "notebook"
  | "planner"
  | "methods";
type Note = {
  id: string;
  created: string;
  ra: number;
  dec: number;
  text: string;
  classification: string;
  sourceIds: string[];
};
type Result = Record<string, any>;
const NAV = [
  { id: "observe", label: "Observation desk", icon: Telescope },
  { id: "atlas", label: "Sky atlas", icon: Globe2 },
  { id: "trace", label: "DeepTrace search", icon: ScanLine },
  { id: "spectra", label: "Spectral explorer", icon: Waves },
  { id: "lab", label: "Experiment lab", icon: FlaskConical },
  { id: "notebook", label: "Research notebook", icon: NotebookPen },
  { id: "planner", label: "Follow-up planner", icon: Compass },
] as const;
const TITLES: Record<Page, [string, string]> = {
  observe: [
    "Watch the universe change.",
    "An observation is a beginning. Follow what moves.",
  ],
  atlas: [
    "A sky full of possibilities.",
    "Explore coordinates. Open a field. Start an investigation.",
  ],
  trace: [
    "Look closer. Then test it.",
    "Search for coherent motion in the observations you have loaded.",
  ],
  spectra: [
    "Beyond visible light.",
    "Explore the infrared measurements that make every source different.",
  ],
  lab: [
    "Evidence earns confidence.",
    "Inject known signals into real backgrounds. Measure what comes back.",
  ],
  notebook: [
    "Follow the evidence.",
    "Keep your observations, questions, and next steps together.",
  ],
  planner: [
    "Know when to look again.",
    "Calculate visibility for your selected sky position and observing site.",
  ],
  methods: [
    "Science, with a paper trail.",
    "Every observation has a source. Every calculation has limits.",
  ],
};
function initialQuery(): Query {
  const p = new URLSearchParams(location.search);
  const ra = Number(p.get("ra") ?? TARGETS[0].ra),
    dec = Number(p.get("dec") ?? TARGETS[0].dec),
    fov = Number(p.get("fov") ?? 5),
    detector = Number(p.get("detector") ?? 1);
  return {
    ra: Number.isFinite(ra) && ra >= 0 && ra < 360 ? ra : TARGETS[0].ra,
    dec: Number.isFinite(dec) && Math.abs(dec) <= 90 ? dec : TARGETS[0].dec,
    fov: Number.isFinite(fov) && fov >= 2 && fov <= 30 ? fov : 5,
    detector:
      Number.isInteger(detector) && detector >= 1 && detector <= 6
        ? detector
        : 1,
  };
}
function Hint({
  label,
  children,
  onClick,
}: {
  label: string;
  children: React.ReactNode;
  onClick?: () => void;
}) {
  return (
    <Tooltip.Root>
      <Tooltip.Trigger
        render={
          <button
            className="icon-button"
            aria-label={label}
            onClick={onClick}
          />
        }
      >
        {children}
      </Tooltip.Trigger>
      <Tooltip.Portal>
        <Tooltip.Positioner sideOffset={8}>
          <Tooltip.Popup className="tooltip">{label}</Tooltip.Popup>
        </Tooltip.Positioner>
      </Tooltip.Portal>
    </Tooltip.Root>
  );
}
function Notice({
  children,
  tone = "info",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return (
    <div className={`notice ${tone}`}>
      <CircleHelp size={16} />
      <div>{children}</div>
    </div>
  );
}

export default function App() {
  const [page, setPage] = useState<Page>("observe"),
    [mobile, setMobile] = useState(false),
    [query, setQuery] = useState<Query>(initialQuery),
    [draft, setDraft] = useState<Query>(initialQuery),
    [search, setSearch] = useState<SearchResult | null>(null),
    [frames, setFrames] = useState<Frame[]>([]),
    [loading, setLoading] = useState(false),
    [progress, setProgress] = useState(""),
    [error, setError] = useState(""),
    [failures, setFailures] = useState<string[]>([]),
    [active, setActive] = useState(0),
    [playing, setPlaying] = useState(false),
    [speed, setSpeed] = useState(900),
    [mode, setMode] = useState("blink"),
    [contrast, setContrast] = useState(1),
    [palette, setPalette] = useState("ice"),
    [point, setPoint] = useState<{ x: number; y: number } | null>(null),
    [result, setResult] = useState<Result | null>(null),
    [experiment, setExperiment] = useState<Result | null>(null),
    [working, setWorking] = useState(""),
    [maxSpeed, setMaxSpeed] = useState(0.15),
    [seed, setSeed] = useState(42),
    [injectionSnr, setInjectionSnr] = useState(3),
    [threshold, setThreshold] = useState(5),
    [note, setNote] = useState(""),
    [classification, setClassification] = useState("Needs investigation"),
    [notes, setNotes] = useState<Note[]>(() => {
      try {
        return JSON.parse(localStorage.getItem("slowtrace-notes") || "[]");
      } catch {
        return [];
      }
    }),
    [plan, setPlan] = useState<Result | null>(null),
    [lat, setLat] = useState(43.6532),
    [lon, setLon] = useState(-79.3832),
    [planDate, setPlanDate] = useState(new Date().toISOString().slice(0, 10)),
    [spectralAxis, setSpectralAxis] = useState("wavelength");
  const serial = useRef(0),
    controller = useRef<AbortController | null>(null);
  const frame = frames[active];
  const reference = frames[0];
  const commonStretch = useMemo<[number, number] | undefined>(() => {
    if (!frames.length) return;
    const values = frames.flatMap((f) =>
      f.data.filter((v): v is number => v !== null && Number.isFinite(v)),
    );
    return [quantile(values, 0.02), quantile(values, 0.995)];
  }, [frames]);
  const selected =
    point && frame
      ? pixelSky(point.x, point.y, frame.width, frame.height, query)
      : { ra: query.ra, dec: query.dec };
  const target = TARGETS.find(
    (t) =>
      Math.abs(t.ra - query.ra) < 0.001 && Math.abs(t.dec - query.dec) < 0.001,
  );
  const fieldName = target?.name || "Custom sky field";
  const load = useCallback(async (q: Query) => {
    controller.current?.abort();
    const c = new AbortController();
    controller.current = c;
    const job = ++serial.current;
    setLoading(true);
    setError("");
    setFailures([]);
    setFrames([]);
    setSearch(null);
    setActive(0);
    setPoint(null);
    setResult(null);
    setExperiment(null);
    setPlan(null);
    setPlaying(false);
    setQuery(q);
    setDraft(q);
    setProgress("Searching DR1 + QR3 at NASA/IPAC IRSA…");
    history.replaceState(
      null,
      "",
      `?${new URLSearchParams(Object.entries(q).map(([k, v]) => [k, String(v)]))}`,
    );
    try {
      const s = await request<SearchResult>(
        `/api/search?${new URLSearchParams({ ...Object.fromEntries(Object.entries(q).map(([k, v]) => [k, String(v)])), limit: "8" })}`,
        { signal: c.signal },
      );
      if (job !== serial.current) return;
      setSearch(s);
      if (!s.observations.length) {
        setProgress(
          "No matching observations returned. Try another detector or field.",
        );
        return;
      }
      let cursor = 0,
        done = 0;
      const worker = async () => {
        while (cursor < s.observations.length) {
          const o = s.observations[cursor++];
          if (c.signal.aborted) return;
          try {
            const f = await request<Frame>(
              `/api/frame?${new URLSearchParams({ url: o.url, ...(o.cloudUrl ? { cloudUrl: o.cloudUrl } : {}), ra: String(q.ra), dec: String(q.dec), fov: String(q.fov), pixels: "96" })}`,
              { signal: c.signal },
            );
            if (job !== serial.current) return;
            setFrames((v) =>
              [...v, f].sort((a, b) => a.metadata.mjd - b.metadata.mjd),
            );
          } catch (e) {
            if (!c.signal.aborted)
              setFailures((v) => [...v, `${o.id}: ${(e as Error).message}`]);
          }
          done++;
          if (job === serial.current)
            setProgress(
              `Processed ${done} of ${s.observations.length} observations`,
            );
        }
      };
      await Promise.all([worker(), worker()]);
    } catch (e) {
      if (!c.signal.aborted) setError((e as Error).message);
    } finally {
      if (job === serial.current) setLoading(false);
    }
  }, []);
  useEffect(() => {
    if (location.search) {
      void load(initialQuery());
      return () => controller.current?.abort();
    }
    const starter = new AbortController();
    request<{ search: SearchResult; frames: Frame[] }>("/starter.json", {
      signal: starter.signal,
    })
      .then((payload) => {
        if (
          !starter.signal.aborted &&
          serial.current === 0 &&
          payload.frames.length
        ) {
          setSearch(payload.search);
          setFrames(payload.frames);
        }
      })
      .catch(() => {
        if (!starter.signal.aborted && serial.current === 0)
          void load(initialQuery());
      });
    return () => {
      starter.abort();
      controller.current?.abort();
    };
  }, [load]);
  useEffect(() => {
    if (!playing || frames.length < 2) return;
    const t = setInterval(
      () => setActive((v) => (v + 1) % frames.length),
      speed,
    );
    return () => clearInterval(t);
  }, [playing, frames.length, speed]);
  useEffect(() => {
    try {
      localStorage.setItem("slowtrace-notes", JSON.stringify(notes));
    } catch {
      toast.error(
        "Your browser could not save the notebook. Export it to keep a copy.",
      );
    }
  }, [notes]);
  const measurements = useMemo(
    () =>
      frames
        .map((f) =>
          aperture(
            f,
            point?.x ?? Math.floor(f.width / 2),
            point?.y ?? Math.floor(f.height / 2),
          ),
        )
        .filter((v) => v.value !== null),
    [frames, point],
  );
  function navigate(p: Page) {
    setPage(p);
    setMobile(false);
    setPlaying(false);
  }
  function chooseTarget(i: number) {
    const t = TARGETS[i];
    void load({
      ...draft,
      fov: i === 2 ? Math.max(5, draft.fov) : draft.fov,
      ra: t.ra,
      dec: t.dec,
    });
    setPage("observe");
  }
  function saveNote() {
    if (!note.trim()) {
      toast.error("Write an observation first.");
      return;
    }
    setNotes((n) => [
      {
        id: crypto.randomUUID(),
        created: new Date().toISOString(),
        ...selected,
        text: note.trim(),
        classification,
        sourceIds: frames.map((f) => f.metadata.id),
      },
      ...n,
    ]);
    setNote("");
    toast.success("Saved in your local research notebook");
  }
  function report() {
    const r = {
      schemaVersion: "slowtrace-x/1.0",
      createdAt: new Date().toISOString(),
      kind: "preliminary-research-record",
      query,
      selection: selected,
      archive: search,
      observations: frames.map((f) => ({
        metadata: f.metadata,
        provenance: f.provenance,
        warnings: f.warnings,
      })),
      apertureMeasurements: measurements,
      analysis: result,
      experiment,
      notes,
      followup: plan,
      limitations: [
        "Candidate scores are exploratory measurements, not discovery probabilities.",
        "WCS-WAVE wavelengths and aperture measurements are for exploratory visualization.",
        "No confirmed discovery, calibrated spectrum, or orbital solution is claimed.",
      ],
    };
    download("slowtrace-x-evidence.json", r);
    toast.success("Evidence report exported with source provenance");
  }
  async function run(kind: "analyze" | "experiment") {
    setWorking(kind);
    const job = serial.current;
    try {
      const baseline = frames.at(-1)!.metadata.mjd - frames[0].metadata.mjd;
      const bound = Math.min(
        maxSpeed,
        (query.fov * 60) / (3.1 * Math.max(0.01, baseline)),
      );
      const steps = [-bound, -bound / 2, 0, bound / 2, bound];
      const velocities = steps.flatMap((y) => steps.map((x) => [x, y]));
      const payload = {
        ...query,
        urls: frames.map((f) => f.provenance.sourceUrl),
        pixels: frame.width,
        threshold,
        seed,
        velocities,
        injectedSnr: injectionSnr,
        motion: [bound, 0],
      };
      const r = await post<Result>(`/api/${kind}`, payload);
      if (job !== serial.current) return;
      if (kind === "analyze")
        setResult({
          ...r,
          candidates: r.candidates.map((c: Result) => ({
            ...c,
            ...pixelSky(c.x, c.y, r.width, r.height, query),
          })),
        });
      else setExperiment(r);
      toast.success(
        kind === "analyze" ? "Analysis complete" : "Experiment complete",
      );
    } catch (e) {
      toast.error((e as Error).message, { duration: 9000 });
    } finally {
      setWorking("");
    }
  }
  async function calculatePlan() {
    setWorking("plan");
    try {
      setPlan(
        await post<Result>("/api/plan", {
          ra: selected.ra,
          dec: selected.dec,
          latitude: lat,
          longitude: lon,
          date: planDate,
        }),
      );
    } catch (e) {
      toast.error((e as Error).message);
    } finally {
      setWorking("");
    }
  }
  const warnings = [...(search?.warnings || []), ...(frame?.warnings || [])];
  return (
    <Tooltip.Provider>
      <a className="skip-link" href="#main">
        Skip to research workspace
      </a>
      <div className="app-shell">
        <aside className={`sidebar ${mobile ? "open" : ""}`}>
          <a className="brand" href="/" aria-label="SLOWTRACE X home">
            <img src="/mark.svg" alt="" />
            <span>
              SLOWTRACE <b>X</b>
              <small>THE CHANGING UNIVERSE</small>
            </span>
          </a>
          <div className="workspace-label">
            <span className="signal-dot" /> PUBLIC RESEARCH WORKSPACE
          </div>
          <nav aria-label="Research tools">
            {NAV.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                className={page === id ? "active" : ""}
                aria-current={page === id ? "page" : undefined}
                onClick={() => navigate(id)}
              >
                <Icon size={18} />
                {label}
                {id === "observe" && <span className="nav-dot" />}
              </button>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="mission-card">
              <div className="orbit-symbol" />
              <span className="eyebrow">ONE SKY. MANY DISCOVERIES.</span>
              <p>
                Make the invisible
                <br />
                worth investigating.
              </p>
              <span>NASA Space Apps Challenge 2026</span>
            </div>
            <button
              className={`method-link ${page === "methods" ? "active" : ""}`}
              onClick={() => navigate("methods")}
            >
              <BookOpen size={17} /> Methods & provenance{" "}
              <ArrowUpRight size={15} />
            </button>
            <a
              className="source-link"
              href="https://github.com/katz1nskyy/Novaryn"
              target="_blank"
              rel="noreferrer"
            >
              GitHub repository <ExternalLink size={13} />
            </a>
          </div>
        </aside>
        <div className="workspace">
          <header className="topbar">
            <button
              className="mobile-menu icon-button"
              aria-label="Open navigation"
              onClick={() => setMobile(!mobile)}
            >
              {mobile ? <X size={20} /> : <Menu size={20} />}
            </button>
            <div className="breadcrumb">
              WORKSPACE <span>/</span>
              <strong>
                {NAV.find((n) => n.id === page)?.label ||
                  "Methods & provenance"}
              </strong>
            </div>
            <div className="topbar-right">
              <span className="archive-status">
                <span className="signal-dot" /> NASA OPEN DATA
              </span>
              <button className="text-button" onClick={report}>
                <ArrowDownToLine size={15} /> Export evidence
              </button>
            </div>
          </header>
          <main id="main">
            <div className="page-heading">
              <div>
                <div className="eyebrow">
                  <span className="mini-cross">✦</span> SPHEREx / PLANET X
                  RESEARCH
                </div>
                <h1>{TITLES[page][0]}</h1>
                <p>{TITLES[page][1]}</p>
              </div>
              <div className="round-help">
                <Hint
                  label="Methods and limitations"
                  onClick={() => navigate("methods")}
                >
                  <CircleHelp size={20} />
                </Hint>
              </div>
            </div>
            <form
              className="query-bar"
              onSubmit={(e) => {
                e.preventDefault();
                void load(draft);
                navigate("observe");
              }}
            >
              <div className="query-icon">
                <Crosshair size={21} />
              </div>
              <label>
                RIGHT ASCENSION{" "}
                <div className="input-unit">
                  <input
                    aria-label="Right ascension in degrees"
                    type="number"
                    min="0"
                    max="359.999999"
                    step="any"
                    required
                    value={Number.isFinite(draft.ra) ? draft.ra : ""}
                    onChange={(e) =>
                      setDraft({ ...draft, ra: e.target.valueAsNumber })
                    }
                  />
                  <span>deg</span>
                </div>
              </label>
              <label>
                DECLINATION{" "}
                <div className="input-unit">
                  <input
                    aria-label="Declination in degrees"
                    type="number"
                    min="-90"
                    max="90"
                    step="any"
                    required
                    value={Number.isFinite(draft.dec) ? draft.dec : ""}
                    onChange={(e) =>
                      setDraft({ ...draft, dec: e.target.valueAsNumber })
                    }
                  />
                  <span>deg</span>
                </div>
              </label>
              <label className="fov-input">
                FIELD OF VIEW
                <select
                  aria-label="Field of view"
                  value={draft.fov}
                  onChange={(e) =>
                    setDraft({ ...draft, fov: Number(e.target.value) })
                  }
                >
                  {[2, 5, 10, 15, 30].map((n) => (
                    <option key={n} value={n}>
                      {n} arcmin
                    </option>
                  ))}
                </select>
              </label>
              <label className="detector-input">
                DETECTOR
                <select
                  aria-label="Detector"
                  value={draft.detector}
                  onChange={(e) =>
                    setDraft({ ...draft, detector: Number(e.target.value) })
                  }
                >
                  {DETECTORS.map((d, i) => (
                    <option key={d} value={i + 1}>
                      D{i + 1} · {d} µm
                    </option>
                  ))}
                </select>
              </label>
              <button type="submit" className="primary" disabled={loading}>
                {loading ? (
                  <LoaderCircle className="spinner" size={17} />
                ) : (
                  <Search size={17} />
                )}{" "}
                {loading
                  ? "Retrieving"
                  : search?.status === "recorded-observations"
                    ? "Search live archive"
                    : "Explore field"}
              </button>
            </form>
            <div className="target-row">
              <span>START WITH A KNOWN OBJECT</span>
              {TARGETS.map((t, i) => (
                <button
                  key={t.name}
                  className={target?.name === t.name ? "selected" : ""}
                  onClick={() => chooseTarget(i)}
                >
                  {t.name}
                  <ArrowUpRight size={11} />
                </button>
              ))}
            </div>
            {!loading && !error && search && frames.length === 0 && (
              <div className="load-status" role="status">
                <CircleHelp size={15} />
                {search.observations.length
                  ? "None of the selected frames could be retrieved. Check data notes or try another detector."
                  : "No matching observations returned. Try another detector or field."}
              </div>
            )}
            {(loading || error) && (
              <div
                className={`load-status ${error ? "error" : ""}`}
                role="status"
              >
                {loading ? (
                  <LoaderCircle className="spinner" size={15} />
                ) : (
                  <CircleHelp size={15} />
                )}
                <span>{error || progress}</span>
                {loading && (
                  <button
                    onClick={() => {
                      controller.current?.abort();
                      setLoading(false);
                      setProgress("Retrieval stopped");
                    }}
                  >
                    Stop retrieval
                  </button>
                )}
              </div>
            )}
            {page === "observe" && (
              <>
                <div className="research-grid">
                  <section className="viewer panel">
                    <div className="viewer-heading">
                      <div className="field-title">
                        <span className="field-icon">
                          <Telescope size={18} />
                        </span>
                        <div>
                          <h2>{fieldName}</h2>
                          <span>
                            {fmt(query.ra, 5)}° <i>/</i> {fmt(query.dec, 5)}°{" "}
                            <i>·</i> ICRS
                          </span>
                        </div>
                      </div>
                      <span className="tag">
                        <span className="signal-dot" />
                        {frame
                          ? search?.status === "recorded-observations"
                            ? "RECORDED NASA DATA"
                            : "REAL OBSERVATION"
                          : "AWAITING DATA"}
                      </span>
                    </div>
                    <div className="viewer-toolbar">
                      <div className="segmented" aria-label="Comparison mode">
                        {["blink", "difference", "split"].map((m) => (
                          <button
                            key={m}
                            className={mode === m ? "selected" : ""}
                            onClick={() => {
                              setMode(m);
                              setPlaying(false);
                            }}
                          >
                            {m === "blink"
                              ? "Blink"
                              : m === "difference"
                                ? "Difference"
                                : "Side by side"}
                          </button>
                        ))}
                      </div>
                      <div className="toolbar-trailing">
                        <Layers3 size={14} />
                        <span>D{query.detector}</span>
                        <select
                          aria-label="Colour palette"
                          value={palette}
                          onChange={(e) => setPalette(e.target.value)}
                        >
                          <option value="ice">Infrared ice</option>
                          <option value="mono">Grayscale</option>
                        </select>
                      </div>
                    </div>
                    <div className={mode === "split" ? "split-view" : ""}>
                      {mode === "split" && (
                        <div>
                          <SkyCanvas
                            frame={reference}
                            mode="blink"
                            contrast={contrast}
                            palette={palette}
                            scale={commonStretch}
                            point={point}
                            onPoint={setPoint}
                          />
                          <div className="split-label">
                            Reference ·{" "}
                            {reference ? date(reference.metadata.mjd) : "—"}
                          </div>
                        </div>
                      )}
                      <div>
                        <SkyCanvas
                          frame={frame}
                          reference={reference}
                          mode={mode}
                          contrast={contrast}
                          palette={palette}
                          scale={commonStretch}
                          point={point}
                          onPoint={setPoint}
                        />
                        {mode === "split" && (
                          <div className="split-label">
                            Selected · {frame ? date(frame.metadata.mjd) : "—"}
                          </div>
                        )}
                      </div>
                    </div>
                    <div className="playback">
                      <button
                        className="play-button"
                        aria-label={playing ? "Pause blink" : "Play blink"}
                        disabled={frames.length < 2}
                        onClick={() => setPlaying(!playing)}
                      >
                        {playing ? <Pause size={18} /> : <Play size={18} />}
                      </button>
                      <div className="epoch-readout">
                        <span>
                          OBSERVATION {frames.length ? active + 1 : 0}{" "}
                          <i>/ {frames.length}</i>
                        </span>
                        <strong>
                          {frame ? date(frame.metadata.mjd) : "No epoch loaded"}
                        </strong>
                      </div>
                      <input
                        className="timeline"
                        aria-label="Observation epoch"
                        type="range"
                        min="0"
                        max={Math.max(0, frames.length - 1)}
                        value={active}
                        disabled={!frames.length}
                        onChange={(e) => {
                          setActive(Number(e.target.value));
                          setPlaying(false);
                        }}
                      />
                      <div className="epoch-step">
                        <button
                          aria-label="Previous epoch"
                          disabled={!frames.length}
                          onClick={() =>
                            setActive(
                              (v) => (v - 1 + frames.length) % frames.length,
                            )
                          }
                        >
                          <ChevronLeft size={17} />
                        </button>
                        <button
                          aria-label="Next epoch"
                          disabled={!frames.length}
                          onClick={() =>
                            setActive((v) => (v + 1) % frames.length)
                          }
                        >
                          <ChevronRight size={17} />
                        </button>
                      </div>
                      <select
                        aria-label="Blink speed"
                        value={speed}
                        onChange={(e) => setSpeed(Number(e.target.value))}
                      >
                        <option value={1400}>Slow</option>
                        <option value={900}>Normal</option>
                        <option value={400}>Fast</option>
                      </select>
                    </div>
                    {mode === "difference" && frame && reference && (
                      <div className="comparison-note">
                        Selected minus first · {date(frame.metadata.mjd)} −{" "}
                        {date(reference.metadata.mjd)} · approximate centre
                        wavelengths{" "}
                        {fmt(Number(frame.metadata.wavelengthCenter), 3)} and{" "}
                        {fmt(Number(reference.metadata.wavelengthCenter), 3)}{" "}
                        µm. Instrument and wavelength differences can leave
                        residuals.
                      </div>
                    )}
                    <div className="viewer-footer">
                      <span>
                        <ShieldCheck size={13} /> WCS aligned · shared stretch ·
                        north up
                      </span>
                      <label>
                        <SlidersHorizontal size={13} /> Stretch{" "}
                        <input
                          aria-label="Display stretch"
                          type="range"
                          min=".4"
                          max="3"
                          step=".1"
                          value={contrast}
                          onChange={(e) => setContrast(Number(e.target.value))}
                        />
                      </label>
                    </div>
                  </section>
                  <aside className="inspector">
                    <section className="panel observation-card">
                      <div className="section-title">
                        <span className="eyebrow">
                          OBSERVATION INTELLIGENCE
                        </span>
                        <Activity size={16} />
                      </div>
                      <h3>
                        The evidence,
                        <br />
                        at a glance.
                      </h3>
                      <div className="metric-grid">
                        <div>
                          <strong>
                            {frames.length.toString().padStart(2, "0")}
                          </strong>
                          <span>Loaded epochs</span>
                        </div>
                        <div>
                          <strong>
                            {frames.length > 1
                              ? fmt(
                                  frames.at(-1)!.metadata.mjd -
                                    frames[0].metadata.mjd,
                                  0,
                                )
                              : "—"}
                            <small> d</small>
                          </strong>
                          <span>Time baseline</span>
                        </div>
                      </div>
                      <dl className="metadata">
                        <div>
                          <dt>Archive release</dt>
                          <dd>
                            {search?.observations.length
                              ? [
                                  ...new Set(
                                    search.observations.map((o) =>
                                      o.collection
                                        .replace("spherex_", "")
                                        .toUpperCase(),
                                    ),
                                  ),
                                ].join(" + ")
                              : "DR1 + QR3"}
                          </dd>
                        </div>
                        <div>
                          <dt>Detector band</dt>
                          <dd>{DETECTORS[query.detector - 1]} µm</dd>
                        </div>
                        <div>
                          <dt>Local wavelength</dt>
                          <dd>
                            {frame
                              ? `${fmt(frame.metadata.wavelengthMin, 3)}–${fmt(frame.metadata.wavelengthMax, 3)} µm`
                              : "—"}
                          </dd>
                        </div>
                        <div>
                          <dt>Valid pixels</dt>
                          <dd>
                            {frame
                              ? `${fmt((1 - frame.metadata.badFraction) * 100, 1)}%`
                              : "—"}
                          </dd>
                        </div>
                        <div>
                          <dt>Zodiacal model</dt>
                          <dd>
                            {frame
                              ? frame.metadata.zodiSubtracted
                                ? "Subtracted"
                                : "Not subtracted"
                              : "—"}
                          </dd>
                        </div>
                        <div>
                          <dt>Output pixel scale</dt>
                          <dd>
                            {frame
                              ? `${fmt(frame.metadata.pixelArcsec)}″`
                              : "—"}
                          </dd>
                        </div>
                      </dl>
                      <button
                        className="secondary full-width"
                        onClick={() => navigate("trace")}
                        disabled={frames.length < 2}
                      >
                        <ScanLine size={16} /> Investigate this field{" "}
                        <ArrowRight size={15} />
                      </button>
                    </section>
                    <section className="insight-card">
                      <span className="eyebrow">
                        <Sparkles size={13} /> FIELD NOTES
                      </span>
                      <h4>
                        {target?.type || "Your next question starts here."}
                      </h4>
                      <p>
                        {target?.note ||
                          "Select a point in an observation to inspect its infrared measurements or record something worth following up."}
                      </p>
                      <button
                        className="inline-link"
                        onClick={() => navigate("spectra")}
                      >
                        Explore its measurements <ArrowUpRight size={14} />
                      </button>
                    </section>
                  </aside>
                </div>
                <div className="below-grid">
                  <section className="panel provenance-panel">
                    <div className="section-title">
                      <h3>
                        <ShieldCheck size={17} /> Traceable by design
                      </h3>
                      <span className="tag small">OBSERVATION → EVIDENCE</span>
                    </div>
                    <p>
                      These are telescope measurements, with flagged pixels
                      excluded. Display stretch changes visibility, not the
                      underlying data. Differences can reflect wavelength,
                      calibration, or artifacts as well as real change.
                    </p>
                    {frame && (
                      <a
                        className="source-file"
                        href={
                          frame.provenance.cutoutUrl ||
                          frame.provenance.sourceUrl
                        }
                        target="_blank"
                        rel="noreferrer"
                      >
                        <ArrowDownToLine size={16} />
                        <span>
                          {frame.metadata.id}
                          <small>Open original NASA FITS data</small>
                        </span>
                        <ArrowUpRight size={16} />
                      </a>
                    )}
                  </section>
                  <section className="panel citizen-panel">
                    <div className="section-title">
                      <h3>
                        <Crosshair size={17} /> Notice something?
                      </h3>
                      <span className="tag small">CITIZEN SCIENCE</span>
                    </div>
                    <p>
                      Click a source in the image, compare epochs, then record
                      what you see. An unusual signal is a question, not a
                      discovery.
                    </p>
                    <button
                      className="secondary"
                      onClick={() => navigate("notebook")}
                    >
                      Record an observation <ArrowRight size={15} />
                    </button>
                  </section>
                </div>
              </>
            )}
            {page === "atlas" && (
              <Atlas
                query={query}
                targets={TARGETS}
                onNavigate={(ra, dec) => {
                  void load({ ...query, ra, dec });
                  navigate("observe");
                }}
              />
            )}
            {page === "spectra" && (
              <section className="panel tool-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">
                      102-CHANNEL MISSION / AVAILABLE SAMPLES
                    </span>
                    <h2>A spectrum begins with measurements.</h2>
                  </div>
                  <div className="segmented">
                    <button
                      className={
                        spectralAxis === "wavelength" ? "selected" : ""
                      }
                      onClick={() => setSpectralAxis("wavelength")}
                    >
                      Wavelength
                    </button>
                    <button
                      className={spectralAxis === "mjd" ? "selected" : ""}
                      onClick={() => setSpectralAxis("mjd")}
                    >
                      Time
                    </button>
                  </div>
                </div>
                <Notice>
                  Showing {measurements.length} measured samples from the loaded
                  detector, not a fabricated 102-point spectrum. WCS-WAVE
                  wavelengths are approximate. Aperture means are
                  local-background subtracted; errors omit pixel covariance and
                  calibration systematics.
                </Notice>
                {measurements.length ? (
                  <Suspense fallback={<div className="chart" />}>
                    <SpectrumChart
                      data={measurements.filter(
                        (m) =>
                          spectralAxis !== "wavelength" ||
                          m.wavelength !== null,
                      )}
                      axis={spectralAxis}
                    />
                  </Suspense>
                ) : (
                  <Empty
                    icon={<Waves size={32} />}
                    text="Load observations to measure the selected sky position."
                  />
                )}
                <div className="tool-footer">
                  <span>
                    Position {fmt(selected.ra, 5)}°, {fmt(selected.dec, 5)}° ·
                    radius 2 output pixels
                  </span>
                  <button
                    className="secondary"
                    onClick={() =>
                      download("slowtrace-spectral-samples.json", {
                        query,
                        selection: selected,
                        measurements,
                        method:
                          "Radius-2-pixel aperture mean minus median annulus (r=4–7); approximate errors.",
                      })
                    }
                    disabled={!measurements.length}
                  >
                    <ArrowDownToLine size={15} /> Export measurements
                  </button>
                </div>
                <p className="caption">
                  Select a source at the observation desk. Choose another
                  detector above to inspect a different infrared range. Changes
                  between different wavelengths are not a light curve.
                </p>
              </section>
            )}
            {page === "trace" && (
              <section className="panel tool-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">
                      DEEPTRACE / EXPERIMENTAL SEARCH
                    </span>
                    <h2>Make coherent motion stand out.</h2>
                  </div>
                  <span className="tag">
                    Measured evidence · no discovery probability
                  </span>
                </div>
                <p className="tool-intro">
                  Weight aligned exposures by inverse variance and combine them
                  along trial motion vectors. Compare each peak against a
                  stationary stack. The search ranks residual peaks using
                  noise-weighted evidence and checks whether the observations
                  are comparable.
                </p>
                <div className="control-grid">
                  <label>
                    Maximum trial motion
                    <input
                      type="number"
                      min=".01"
                      max="20"
                      step=".1"
                      value={maxSpeed}
                      onChange={(e) => setMaxSpeed(e.target.valueAsNumber)}
                    />
                    <small>arcsec / day, each axis</small>
                  </label>
                  <label>
                    Detection threshold
                    <input
                      type="number"
                      min="3"
                      max="12"
                      step=".5"
                      value={threshold}
                      onChange={(e) => setThreshold(e.target.valueAsNumber)}
                    />
                    <small>nominal signal-to-noise</small>
                  </label>
                  <div className="control-action">
                    <button
                      className="primary"
                      disabled={frames.length < 2 || !!working}
                      onClick={() => void run("analyze")}
                    >
                      {working === "analyze" ? (
                        <LoaderCircle className="spinner" size={17} />
                      ) : (
                        <ScanLine size={17} />
                      )}{" "}
                      Run DeepTrace
                    </button>
                    <small>
                      {frames.length} real exposures available · at least 2
                      required
                    </small>
                  </div>
                </div>
                {result ? (
                  <ScientificResult result={result} />
                ) : (
                  <Empty
                    icon={<ScanLine size={32} />}
                    text="No search has been run on this field yet."
                  />
                )}
                <Notice>
                  A residual can be a star, a detector artifact, a bandpass
                  mismatch, or a moving source. Gaussian filtering is an
                  approximation to the instrument PSF. Trial searches and
                  resampling affect significance; the displayed S/N is not a
                  false-alarm probability.
                </Notice>
                <div className="tool-footer">
                  <button
                    className="text-button"
                    onClick={() => navigate("lab")}
                  >
                    <FlaskConical size={16} /> Test recovery on these images{" "}
                    <ArrowRight size={14} />
                  </button>
                  <button
                    className="secondary"
                    disabled={!result}
                    onClick={() => download("slowtrace-analysis.json", result)}
                  >
                    <ArrowDownToLine size={15} /> Export analysis
                  </button>
                </div>
              </section>
            )}
            {page === "lab" && (
              <section className="panel tool-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">
                      CONTROLLED EXPERIMENT / REAL BACKGROUNDS
                    </span>
                    <h2>Put the search to the test.</h2>
                  </div>
                  <span className="tag amber">
                    Synthetic injections clearly identified
                  </span>
                </div>
                <p className="tool-intro">
                  Inject artificial moving sources into the loaded NASA
                  observations. Compare motion-aware recovery with a
                  stationary-stack baseline using the same positions, noise, and
                  detection thresholds.
                </p>
                <div className="control-grid">
                  <label>
                    Random seed
                    <input
                      type="number"
                      min="0"
                      max="2147483647"
                      value={seed}
                      onChange={(e) => setSeed(e.target.valueAsNumber)}
                    />
                    <small>Repeat the same controlled trial</small>
                  </label>
                  <label>
                    Trial speed range
                    <input
                      type="number"
                      min=".01"
                      max="20"
                      step=".1"
                      value={maxSpeed}
                      onChange={(e) => setMaxSpeed(e.target.valueAsNumber)}
                    />
                    <small>arcsec / day</small>
                  </label>
                  <label>
                    Injected signal-to-noise
                    <input
                      type="number"
                      min=".5"
                      max="15"
                      step=".5"
                      value={injectionSnr}
                      onChange={(e) => setInjectionSnr(e.target.valueAsNumber)}
                    />
                    <small>Approximate single-exposure S/N</small>
                  </label>
                  <div className="control-action">
                    <button
                      className="primary"
                      disabled={frames.length < 2 || !!working}
                      onClick={() => void run("experiment")}
                    >
                      {working === "experiment" ? (
                        <LoaderCircle className="spinner" size={17} />
                      ) : (
                        <FlaskConical size={17} />
                      )}{" "}
                      Run recovery experiment
                    </button>
                    <small>Measured outcomes, including failures</small>
                  </div>
                </div>
                {experiment ? (
                  <ScientificResult result={experiment} />
                ) : (
                  <Empty
                    icon={<FlaskConical size={32} />}
                    text="Your experiment results will appear after the calculation."
                  />
                )}
                <Notice>
                  Injected objects are synthetic; the image backgrounds are
                  real. This small conditional experiment is not a blind survey
                  benchmark. Improvements are reported only when measured in
                  this run.
                </Notice>
                <div className="tool-footer">
                  <span>
                    Recorded seed, parameters, controls, and source provenance
                  </span>
                  <button
                    className="secondary"
                    disabled={!experiment}
                    onClick={() =>
                      download("slowtrace-experiment.json", experiment)
                    }
                  >
                    <ArrowDownToLine size={15} /> Export reproducible run
                  </button>
                </div>
              </section>
            )}
            {page === "notebook" && (
              <div className="notebook-grid">
                <section className="panel tool-panel">
                  <span className="eyebrow">
                    A HUMAN LOOK IS PART OF THE METHOD
                  </span>
                  <h2>Record what you see.</h2>
                  <p className="muted">
                    Selected position: {fmt(selected.ra, 6)}°,{" "}
                    {fmt(selected.dec, 6)}°. Records are saved in this browser,
                    with source IDs attached.
                  </p>
                  <label className="stacked-label">
                    Observation type
                    <select
                      value={classification}
                      onChange={(e) => setClassification(e.target.value)}
                    >
                      {[
                        "Needs investigation",
                        "Possible motion",
                        "Brightness change",
                        "Likely artifact",
                        "No visible change",
                      ].map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  </label>
                  <label className="stacked-label">
                    Your observation
                    <textarea
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      placeholder="Which epochs did you compare? What changed? What might explain it?"
                      rows={5}
                    />
                  </label>
                  <button className="primary" onClick={saveNote}>
                    <NotebookPen size={16} /> Save observation
                  </button>
                  <Notice>
                    These are personal research notes. They are not submitted to
                    NASA, the Minor Planet Center, or a public review network.
                  </Notice>
                </section>
                <section className="panel tool-panel">
                  <div className="section-title">
                    <h2>
                      Research log <span className="count">{notes.length}</span>
                    </h2>
                    <button
                      className="icon-button"
                      aria-label="Export notebook"
                      onClick={() => download("slowtrace-notebook.json", notes)}
                    >
                      <ArrowDownToLine size={18} />
                    </button>
                  </div>
                  {!notes.length ? (
                    <Empty
                      icon={<NotebookPen size={29} />}
                      text="A good question is worth keeping."
                    />
                  ) : (
                    notes.map((n) => (
                      <article className="note" key={n.id}>
                        <span className="tag small">{n.classification}</span>
                        <p>{n.text}</p>
                        <small>
                          {date(n.created)} · {fmt(n.ra, 4)}°, {fmt(n.dec, 4)}°
                          · {n.sourceIds.length} source files
                        </small>
                        <button
                          className="text-button"
                          onClick={() => {
                            setNotes((v) => v.filter((x) => x.id !== n.id));
                            toast("Observation removed", {
                              action: {
                                label: "Undo",
                                onClick: () => setNotes((v) => [n, ...v]),
                              },
                            });
                          }}
                        >
                          Remove
                        </button>
                      </article>
                    ))
                  )}
                </section>
              </div>
            )}
            {page === "planner" && (
              <section className="panel tool-panel">
                <div className="panel-heading">
                  <div>
                    <span className="eyebrow">
                      FOLLOW-UP / FIXED SKY POSITION
                    </span>
                    <h2>Find a window to observe.</h2>
                  </div>
                  <Compass size={26} />
                </div>
                <div className="control-grid four">
                  <label>
                    Latitude, degrees
                    <input
                      type="number"
                      min="-90"
                      max="90"
                      step="any"
                      value={lat}
                      onChange={(e) => setLat(e.target.valueAsNumber)}
                    />
                  </label>
                  <label>
                    Longitude, east positive
                    <input
                      type="number"
                      min="-180"
                      max="180"
                      step="any"
                      value={lon}
                      onChange={(e) => setLon(e.target.valueAsNumber)}
                    />
                  </label>
                  <label>
                    UTC date
                    <input
                      type="date"
                      value={planDate}
                      onChange={(e) => setPlanDate(e.target.value)}
                    />
                  </label>
                  <button
                    className="primary"
                    disabled={!!working}
                    onClick={() => void calculatePlan()}
                  >
                    {working === "plan" ? (
                      <LoaderCircle className="spinner" size={16} />
                    ) : (
                      <Compass size={16} />
                    )}{" "}
                    Calculate visibility
                  </button>
                </div>
                {plan && (
                  <>
                    <Suspense fallback={<div className="chart" />}>
                      <PlannerChart
                        data={plan.samples.map((p: Result) => ({
                          time: p.time.slice(11, 16),
                          altitude: p.altitude,
                          sun: p.sunAltitude,
                        }))}
                      />
                    </Suspense>
                    <div className="window-list">
                      {plan.windows.length ? (
                        plan.windows.map((w: Result, i: number) => (
                          <div key={i}>
                            <span className="signal-dot" />
                            <strong>
                              {w.start.slice(11, 16)}–{w.end.slice(11, 16)} UTC
                            </strong>
                            <span>
                              {w.durationMinutes} min · altitude ≥30° · Sun
                              ≤−18°
                            </span>
                          </div>
                        ))
                      ) : (
                        <Notice>
                          No qualifying dark-sky window at this location on this
                          UTC date.
                        </Notice>
                      )}
                    </div>
                  </>
                )}
                <Notice>
                  Calculated for a fixed ICRS position, without refraction,
                  weather, horizon obstructions, or object-motion prediction.
                  This is a visibility aid, not an orbit solution or guarantee
                  of detectability.
                </Notice>
              </section>
            )}
            {page === "methods" && <Methods />}
            {(warnings.length > 0 || failures.length > 0) && (
              <details className="warnings">
                <summary>
                  <CircleHelp size={14} /> Data notes and retrieval details{" "}
                  <span>{warnings.length + failures.length}</span>
                  <ChevronDown size={15} />
                </summary>
                {[...new Set(warnings)].map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
                {failures.map((w, i) => (
                  <p key={`f${i}`}>{w}</p>
                ))}
              </details>
            )}
            <footer className="page-footer">
              <span>
                <span className="signal-dot" /> REAL DATA. OPEN QUESTIONS.
              </span>
              <span>
                NASA/IPAC IRSA · SPHEREx · Independent Space Apps project
              </span>
              <a
                href="https://irsa.ipac.caltech.edu/Missions/spherex.html"
                target="_blank"
                rel="noreferrer"
              >
                Explore the mission <ArrowUpRight size={12} />
              </a>
            </footer>
          </main>
        </div>
      </div>
    </Tooltip.Provider>
  );
}
function Empty({ icon, text }: { icon: React.ReactNode; text: string }) {
  return (
    <div className="empty-state">
      {icon}
      <p>{text}</p>
    </div>
  );
}
function ScientificResult({ result }: { result: Result }) {
  const candidates = result.candidates || result.search?.candidates || [];
  const rows = result.measurements || [];
  return (
    <div className="scientific-result">
      <div className="section-title">
        <h3>
          <Check size={17} /> Calculation returned
        </h3>
        <span className="tag">{result.kind || "Preliminary"}</span>
      </div>
      {result.message && <p>{result.message}</p>}
      {result.selectedFrameIndices && (
        <p className="caption">
          {result.selectedFrameIndices.length} wavelength-compatible exposures ·{" "}
          {fmt(result.baselineDays)} days ·{" "}
          {result.excludedFrameIndices?.length || 0} excluded
        </p>
      )}
      {result.recovered && (
        <div className="recovery-grid">
          {[
            ["Shift and stack", "shiftStack"],
            ["Stationary stack", "staticStack"],
            ["Best single frame", "bestSingleFrame"],
          ].map(([label, k]) => (
            <div key={k}>
              <strong>
                {result.recovered[k]}/{result.trials}
              </strong>
              <span>{label}</span>
            </div>
          ))}
          <div>
            <strong>
              {result.unInjectedControlPeaks} / {result.negativeControlPeaks}
            </strong>
            <span>
              Control peaks, capped at {result.controlPeakCountCappedAt}
            </span>
          </div>
        </div>
      )}
      {(result.notes || result.warnings || result.limitations || []).map(
        (w: string, i: number) => (
          <p className="caption" key={i}>
            {w}
          </p>
        ),
      )}
      {candidates.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Nominal S/N</th>
                <th>Static S/N</th>
                <th>ICRS RA / Dec</th>
                <th>Trial motion</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {candidates.slice(0, 20).map((c: Result, i: number) => (
                <tr key={i}>
                  <td>STX-{String(i + 1).padStart(3, "0")}</td>
                  <td>{fmt(c.nominalSnr)}</td>
                  <td>{fmt(c.staticSnr)}</td>
                  <td>
                    {fmt(c.ra, 6)}° / {fmt(c.dec, 6)}°
                  </td>
                  <td>
                    {fmt(c.velocityWestArcsecDay, 3)},{" "}
                    {fmt(c.velocitySouthArcsecDay, 3)} ″/d
                  </td>
                  <td>{c.velocityWestArcsecDay || c.velocitySouthArcsecDay ? "Motion trial peak" : "Stationary trial peak"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                {Object.keys(rows[0])
                  .filter((k) => typeof rows[0][k] !== "object")
                  .slice(0, 8)
                  .map((k) => (
                    <th key={k}>{k.replaceAll("_", " ")}</th>
                  ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 36).map((r: Result, i: number) => (
                <tr key={i}>
                  {Object.entries(r)
                    .filter(([, v]) => typeof v !== "object")
                    .slice(0, 8)
                    .map(([k, v]) => (
                      <td key={k}>
                        {typeof v === "number" ? fmt(v, 3) : String(v)}
                      </td>
                    ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <details className="raw-result">
        <summary>Full measured results and parameters</summary>
        <pre>
          {JSON.stringify(
            result,
            (_k, v) =>
              Array.isArray(v) && v.length > 200
                ? `[${v.length} values — full array in export]`
                : v,
            2,
          )}
        </pre>
      </details>
    </div>
  );
}
function Methods() {
  return (
    <div className="methods-grid">
      <section className="panel tool-panel">
        <span className="eyebrow">THE SCIENTIFIC CONTRACT</span>
        <h2>Inspect. Compare. Question.</h2>
        <p>
          Every displayed observation comes from NASA/IPAC IRSA SPHEREx Level 2
          data. Search covers DR1 and QR3. If a stored archive index is used
          during an outage, the response identifies it. Retrieval errors are
          shown; an empty result is not replaced with a synthetic sky.
        </p>
        <h3>What the viewer does</h3>
        <p>
          Reads IMAGE, VARIANCE, FLAGS, and available ZODI and WCS-WAVE
          extensions. Reprojects images to a common celestial grid, excludes
          selected bad-pixel flags, subtracts the supplied zodiacal-light model
          when available, and applies a display-only stretch.
        </p>
        <h3>What a difference means</h3>
        <p>
          Same detector does not mean same wavelength. Optical response,
          background, flags, sampling and wavelength can change between visits.
          A difference is exploratory until those explanations are tested.
          Reprojection correlates noise; nominal errors do not include all
          systematics.
        </p>
        <h3>Search and experiments</h3>
        <p>
          DeepTrace is an experimental numerical search, not a trained discovery
          classifier. It compares trial motion stacks with a stationary stack.
          The laboratory adds labeled synthetic sources to real backgrounds and
          reports measured recovery and controls. No population-wide performance
          or Planet X discovery is claimed.
        </p>
        <h3>What remains research work</h3>
        <p>
          Calibrated 102-channel source spectra, detector ePSF fitting,
          validated machine-learning artifact classification, full catalog
          verification, orbit fitting, blind survey benchmarking, and shared
          citizen-science review require further development. The tool does not
          label an unmatched residual a new astronomical object.
        </p>
      </section>
      <section className="panel tool-panel">
        <span className="eyebrow">DATA, METHODS & CREDIT</span>
        <h2>Follow the source.</h2>
        {[
          [
            "SPHEREx at NASA/IPAC IRSA",
            "https://irsa.ipac.caltech.edu/Missions/spherex.html",
          ],
          [
            "Data access: DR1 + QR3",
            "https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-access/",
          ],
          [
            "Data products and calibration",
            "https://irsa.ipac.caltech.edu/spherex-archive-documentation/spherex-data-products/",
          ],
          [
            "Official tutorial notebooks",
            "https://caltech-ipac.github.io/irsa-tutorials/spherex/",
          ],
          [
            "JPL Horizons — independent follow-up",
            "https://ssd.jpl.nasa.gov/horizons/",
          ],
          [
            "Gaia DR3 archive",
            "https://archive.stsci.edu/missions-and-data/gaia",
          ],
          [
            "Source code & reproducibility",
            "/source.zip",
          ],
        ].map(([label, url]) => (
          <a
            key={url}
            className="resource-link"
            href={url}
            target="_blank"
            rel="noreferrer"
          >
            {label}
            <ArrowUpRight size={15} />
          </a>
        ))}
        <h3>Built with open research</h3>
        <p>
          Reference projects:{" "}
          <a href="https://github.com/Nsa-2026/skyshift">SkyShift</a>{" "}
          (Apache-2.0) and{" "}
          <a href="https://github.com/epsretriever/spherex-planet-x">
            Driftnet
          </a>{" "}
          (MIT). Reuse and modifications are documented in the repository.
          Development used AI assistance; calculations run in inspectable code.
        </p>
        <p className="caption">
          SPHEREx is a joint project of JPL and Caltech, funded by NASA. This
          independent challenge project is not endorsed by NASA. Mission data
          and their calibration limitations remain the basis of every
          investigation.
        </p>
      </section>
    </div>
  );
}
