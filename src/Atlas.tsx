import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent, PointerEvent } from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  Bookmark,
  Check,
  ChevronRight,
  Compass,
  Crosshair,
  Focus,
  Globe2,
  Layers3,
  Map,
  Minus,
  Plus,
  Search,
  X,
} from "lucide-react";
import AtlasBackground from "./atlas/AtlasBackground";
import type { Backdrop } from "./atlas/AtlasBackground";
import {
  asterisms,
  candidateMark,
  coordinateText,
  fieldMark,
  fixedMarks,
  freeMark,
  targetMark,
} from "./atlas/catalog";
import type { Mark } from "./atlas/catalog";
import {
  arc,
  clamp,
  ecliptic,
  galacticPlane,
  graticule,
  project,
  relative,
  unproject,
  viewport,
  wrap,
} from "./atlas/geometry";
import type { Camera, Point, Sky, View } from "./atlas/geometry";
import type { Query, Target } from "./types";
import type { SurveySnapshot } from "./surveyTypes";
import { useBulkSurvey } from "./bulkSurvey";
import "./atlas.css";

const opticalSource = "https://svs.gsfc.nasa.gov/4851/";
const infraredSource =
  "https://irsa.ipac.caltech.edu/data/hips/SPHEREx/spherex_allsky_cube/properties";
const bookmarkKey = "slowtrace-atlas-bookmarks-v1";
const navLayers = {
  coordinates: { label: "ICRS grid", defaultOn: true },
  constellations: { label: "Constellation lines", defaultOn: true },
  ecliptic: { label: "Ecliptic", defaultOn: false },
  galactic: { label: "Galactic plane", defaultOn: false },
  targets: { label: "Challenge targets", defaultOn: true },
  objects: { label: "Catalog landmarks", defaultOn: true },
  fields: { label: "DeepTrace fields", defaultOn: false },
  bulk: { label: "Processed image footprints", defaultOn: true },
  candidates: { label: "Survey candidates", defaultOn: false },
  tracks: { label: "Candidate epoch positions", defaultOn: false },
} as const;
type Layer = keyof typeof navLayers;
type Layers = Record<Layer, boolean>;
type Props = {
  query: Query;
  targets: Target[];
  onNavigate: (ra: number, dec: number) => void;
  focus?: Sky & { label?: string };
  onCandidate?: (id: string) => void;
};
const initialLayers = Object.fromEntries(
  Object.entries(navLayers).map(([key, value]) => [key, value.defaultOn]),
) as Layers;
const labels: Record<Mark["kind"], string> = {
  target: "Challenge target",
  star: "Catalog star",
  object: "Catalog landmark",
  candidate: "Survey candidate",
  field: "Survey field",
  position: "ICRS position",
};
const displayStatus = (status?: string) => status?.replaceAll(/[-_]/g, " ");
const displayDegree = (coordinate: number, signed = false) =>
  `${signed && coordinate >= 0 ? "+" : ""}${coordinate.toFixed(4)}°`;
const closePosition = (a: Sky, b: Sky) =>
  Math.abs(relative(a.ra - b.ra)) < 1e-4 && Math.abs(a.dec - b.dec) < 1e-4;
const trail = (points: Sky[]) =>
  points.flatMap((point, i) => (i ? arc(points[i - 1], point, 3) : [point]));
const retrieveBookmarks = (): Mark[] => {
  try {
    const saved = JSON.parse(localStorage.getItem(bookmarkKey) ?? "[]");
    if (!Array.isArray(saved)) return [];
    return saved
      .filter(
        (item) =>
          item &&
          typeof item.name === "string" &&
          Number.isFinite(item.ra) &&
          Number.isFinite(item.dec),
      )
      .slice(0, 30);
  } catch {
    return [];
  }
};

function drawPath(
  points: Sky[],
  projection: (point: Sky) => Point | null,
  width: number,
) {
  let last: Point | null = null;
  let path = "";
  for (const point of points) {
    const p = projection(point);
    if (p)
      path += `${last && Math.abs(last.x - p.x) < width * 0.36 ? "L" : "M"}${p.x.toFixed(1)},${p.y.toFixed(1)}`;
    last = p;
  }
  return path;
}

function MarkSymbol({ kind }: { kind: Mark["kind"] }) {
  if (kind === "candidate") return <path d="M0 -5 5 0 0 5 -5 0Z" />;
  if (kind === "field")
    return <rect x="-3" y="-3" width="6" height="6" rx=".65" />;
  if (kind === "target")
    return (
      <>
        <circle r="5.5" />
        <circle r="1.6" className="sky-atlas-solid" />
      </>
    );
  if (kind === "star") return <path d="M0 -4V4M-4 0H4" fill="none" />;
  return <circle r="3" />;
}

export default function Atlas({
  query,
  targets,
  onNavigate,
  focus,
  onCandidate,
}: Props) {
  const start = focus ?? query;
  const [view, setView] = useState<View>("globe");
  const [camera, setCamera] = useState<Camera>({
    ra: start.ra,
    dec: start.dec,
    zoom: 1,
  });
  const [selected, setSelected] = useState<Mark>(
    focus?.label ? { ...freeMark(start), name: focus.label } : freeMark(start),
  );
  const [layers, setLayers] = useState<Layers>(initialLayers);
  const bulk = useBulkSurvey(layers.bulk);
  const [backdrop, setBackdrop] = useState<Backdrop>("optical");
  const [stars, setStars] = useState(true);
  const [milkyWay, setMilkyWay] = useState(true);
  const [size, setSize] = useState({ width: 900, height: 650 });
  const [search, setSearch] = useState("");
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [layersOpen, setLayersOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<SurveySnapshot | null>(null);
  const [snapshotUnavailable, setSnapshotUnavailable] = useState(false);
  const [textureErrors, setTextureErrors] = useState<string[]>([]);
  const [hover, setHover] = useState<(Point & { mark: Mark }) | null>(null);
  const [dragging, setDragging] = useState(false);
  const [bookmarks, setBookmarks] = useState<Mark[]>(retrieveBookmarks);
  const stage = useRef<HTMLDivElement>(null);
  const readout = useRef<HTMLSpanElement>(null);
  const animation = useRef(0);
  const cameraRef = useRef(camera);
  const searchBox = useRef<HTMLDivElement>(null);
  const layerBox = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    id: number;
    x: number;
    y: number;
    moved: boolean;
    camera: Camera;
  } | null>(null);
  cameraRef.current = camera;

  const targetMarks = useMemo(() => targets.map(targetMark), [targets]);
  const candidateMarks = useMemo(
    () => snapshot?.candidates.map(candidateMark) ?? [],
    [snapshot],
  );
  const fieldMarks = useMemo(
    () => snapshot?.fields.map(fieldMark) ?? [],
    [snapshot],
  );
  const findable = useMemo(
    () => [...targetMarks, ...fixedMarks, ...candidateMarks, ...fieldMarks],
    [targetMarks, candidateMarks, fieldMarks],
  );
  const visibleMarks = useMemo(
    () => [
      ...(layers.targets ? targetMarks : []),
      ...(layers.objects ? fixedMarks : []),
      ...(layers.fields ? fieldMarks : []),
      ...(layers.candidates ? candidateMarks : []),
    ],
    [layers, targetMarks, fieldMarks, candidateMarks],
  );
  const centerLabel = search.trim().toLowerCase();
  const exactCoordinates = coordinateText(search);
  const matches = centerLabel
    ? findable
        .filter((mark) =>
          `${mark.name} ${mark.alias ?? ""} ${mark.note ?? ""}`
            .toLowerCase()
            .includes(centerLabel),
        )
        .slice(0, 7)
    : targetMarks;

  useEffect(() => {
    if (!stage.current) return;
    const resize = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) setSize({ width, height });
    });
    resize.observe(stage.current);
    return () => resize.disconnect();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    fetch("/survey.json", { signal: controller.signal })
      .then((result) => {
        if (!result.ok) throw new Error("Survey snapshot unavailable");
        return result.json() as Promise<SurveySnapshot>;
      })
      .then(setSnapshot)
      .catch(() => {
        if (!controller.signal.aborted) setSnapshotUnavailable(true);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    function closePopovers(event: globalThis.PointerEvent) {
      if (event.target instanceof Node) {
        if (!searchBox.current?.contains(event.target)) setSearchOpen(false);
        if (!layerBox.current?.contains(event.target)) setLayersOpen(false);
      }
    }
    document.addEventListener("pointerdown", closePopovers);
    return () => document.removeEventListener("pointerdown", closePopovers);
  }, []);

  const changeZoom = useCallback((delta: number) => {
    cancelAnimationFrame(animation.current);
    setCamera((value) => ({
      ...value,
      zoom: clamp(value.zoom * delta, 0.68, 3.8),
    }));
  }, []);
  useEffect(() => {
    const element = stage.current;
    if (!element || view === "accessible") return;
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      event.preventDefault();
      changeZoom(Math.exp(-clamp(event.deltaY, -120, 120) * 0.0018));
    };
    element.addEventListener("wheel", wheel, { passive: false });
    return () => element.removeEventListener("wheel", wheel);
  }, [changeZoom, view]);

  const aim = useCallback((position: Sky) => {
    cancelAnimationFrame(animation.current);
    const from = cameraRef.current;
    const target = {
      ra: wrap(position.ra),
      dec: clamp(position.dec, -90, 90),
      zoom: from.zoom,
    };
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setCamera(target);
      return;
    }
    const start = performance.now();
    const delta = relative(target.ra - from.ra);
    const turn = (time: number) => {
      const progress = Math.min((time - start) / 250, 1);
      const eased = 1 - Math.pow(1 - progress, 3);
      setCamera({
        ra: wrap(from.ra + delta * eased),
        dec: from.dec + (target.dec - from.dec) * eased,
        zoom: from.zoom,
      });
      if (progress < 1) animation.current = requestAnimationFrame(turn);
    };
    animation.current = requestAnimationFrame(turn);
  }, []);
  const select = useCallback(
    (mark: Mark, recenter = false) => {
      setSelected(mark);
      setHover(null);
      if (recenter) aim(mark);
      if (mark.kind === "candidate" || mark.kind === "field")
        setLayers((value) => ({
          ...value,
          [mark.kind === "candidate" ? "candidates" : "fields"]: true,
        }));
    },
    [aim],
  );
  useEffect(() => () => cancelAnimationFrame(animation.current), []);

  const focusRa = focus?.ra,
    focusDec = focus?.dec,
    focusLabel = focus?.label;
  useEffect(() => {
    if (focusRa == null || focusDec == null) return;
    const position = { ra: focusRa, dec: focusDec };
    const existing = findable.find(
      (mark) =>
        closePosition(mark, position) &&
        (!focusLabel || focusLabel === mark.name),
    );
    select(
      existing ?? {
        ...freeMark(position),
        name: focusLabel ?? "Selected sky position",
      },
      true,
    );
  }, [focusRa, focusDec, focusLabel, findable, select]);

  const unavailable = useCallback(() => setView("accessible"), []);
  const textureError = useCallback((name: string) => {
    setTextureErrors((errors) =>
      errors.includes(name) ? errors : [...errors, name],
    );
  }, []);
  const activeTexture =
    backdrop === "infrared"
      ? "spherex-dr1-frame42"
      : stars && milkyWay
        ? "star-map"
        : stars
          ? "bright-stars"
          : milkyWay
            ? "milkyway"
            : null;
  const textureFailed = Boolean(
    backdrop !== "none" &&
    activeTexture &&
    textureErrors.includes(activeTexture),
  );
  const { width, height } = size;
  const projection = useCallback(
    (point: Sky) => project(point, camera, view, width, height),
    [camera, view, width, height],
  );
  const projectedMarks = visibleMarks.flatMap((mark) => {
    const p = projection(mark);
    return p && p.x >= 0 && p.y >= 0 && p.x <= width && p.y <= height
      ? [{ ...p, mark }]
      : [];
  });
  const outlines = useMemo(
    () => ({
      coords: layers.coordinates
        ? graticule
            .map((series) => drawPath(series, projection, width))
            .join("")
        : "",
      constellations: layers.constellations
        ? asterisms.map((group) => ({
            ...group,
            path: group.paths
              .map((series) => drawPath(series, projection, width))
              .join(""),
            point: projection(group.centroid),
          }))
        : [],
      ecliptic: layers.ecliptic ? drawPath(ecliptic, projection, width) : "",
      galactic: layers.galactic
        ? drawPath(galacticPlane, projection, width)
        : "",
      tracks: layers.tracks
        ? candidateMarks.flatMap((mark) => {
            const samples = mark.candidate?.evidence.epochMeasurements;
            return samples && samples.length >= 2
              ? [
                  {
                    id: mark.id,
                    path: drawPath(
                      trail([...samples].sort((a, b) => a.mjd - b.mjd)),
                      projection,
                      width,
                    ),
                  },
                ]
              : [];
          })
        : [],
    }),
    [candidateMarks, layers, projection, width],
  );
  const footprintPath = useMemo(
    () =>
      layers.bulk
        ? (bulk.snapshot?.footprints ?? [])
            .slice(0, 1000)
            .map((footprint) => {
              const first = footprint.boundary[0];
              return first
                ? drawPath([...footprint.boundary, first], projection, width)
                : "";
            })
            .join("")
        : "",
    [bulk.snapshot, layers.bulk, projection, width],
  );
  const gridLabels = layers.coordinates
    ? Array.from({ length: 12 }, (_, index) => {
        const ra = index * 30;
        return { text: `${index * 2}h`, point: projection({ ra, dec: 0 }) };
      })
    : [];
  const selectedPoint = projection(selected);
  const hoverPosition = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  };
  const findMark = (p: Point) =>
    projectedMarks
      .map((entry) => ({
        entry,
        distance: (entry.x - p.x) ** 2 + (entry.y - p.y) ** 2,
      }))
      .filter(({ distance }) => distance < 17 ** 2)
      .sort((a, b) => a.distance - b.distance)[0]?.entry;
  function beginPan(event: PointerEvent<HTMLDivElement>) {
    if (event.button !== 0) return;
    cancelAnimationFrame(animation.current);
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      moved: false,
      camera: cameraRef.current,
    };
    setHover(null);
  }
  function movePan(event: PointerEvent<HTMLDivElement>) {
    const moving = drag.current;
    if (moving?.id === event.pointerId) {
      const dx = event.clientX - moving.x,
        dy = event.clientY - moving.y;
      if (Math.hypot(dx, dy) > 4) moving.moved = true;
      if (moving.moved && view !== "accessible") {
        const area = viewport(width, height, view, moving.camera.zoom);
        setDragging(true);
        setCamera({
          ...moving.camera,
          ra: wrap(
            moving.camera.ra + (dx * (view === "globe" ? 62 : 148)) / area.rx,
          ),
          dec:
            view === "globe"
              ? clamp(moving.camera.dec + (dy * 65) / area.ry, -90, 90)
              : moving.camera.dec,
        });
      }
      return;
    }
    const point = hoverPosition(event);
    const position = unproject(point, camera, view, width, height);
    if (readout.current)
      readout.current.textContent = position
        ? `${displayDegree(position.ra)}  /  ${displayDegree(position.dec, true)}`
        : "Outside map";
    const match = findMark(point);
    setHover(match ?? null);
  }
  function endPan(event: PointerEvent<HTMLDivElement>) {
    const moving = drag.current;
    drag.current = null;
    setDragging(false);
    if (!moving || moving.moved) return;
    const point = hoverPosition(event);
    const mark = findMark(point);
    const sky = mark ? null : unproject(point, camera, view, width, height);
    if (mark) select(mark.mark);
    if (sky) select(freeMark(sky));
  }
  function searchResult(mark: Mark) {
    select(mark, true);
    setSearch("");
    setSearchOpen(false);
    setSearchError("");
  }
  function handleSearch(event: FormEvent) {
    event.preventDefault();
    if (exactCoordinates) {
      searchResult(freeMark(exactCoordinates));
      return;
    }
    if (centerLabel && matches[0]) {
      searchResult(matches[0]);
      return;
    }
    setSearchError(
      "Enter a landmark name, or RA and Dec separated by a comma.",
    );
  }
  const isSaved = bookmarks.some((mark) => closePosition(mark, selected));
  const toggleBookmark = () => {
    const next = isSaved
      ? bookmarks.filter((mark) => !closePosition(mark, selected))
      : [...bookmarks.slice(-29), selected];
    setBookmarks(next);
    try {
      localStorage.setItem(
        bookmarkKey,
        JSON.stringify(
          next.map(({ id, kind, name, ra, dec, note, source, status }) => ({
            id,
            kind,
            name,
            ra,
            dec,
            note,
            source,
            status,
          })),
        ),
      );
    } catch {
      /* Session bookmarks stay available if local storage is disabled. */
    }
  };
  const restoreBookmark = (mark: Mark) =>
    select(findable.find((item) => item.id === mark.id) ?? mark, true);
  const layersCount = Object.values(layers).filter(Boolean).length;
  const frame = viewport(width, height, view, camera.zoom);
  const field = selected.field;
  const candidate = selected.candidate;
  const fillBackdrop = useMemo(
    () => ({
      left: frame.x - frame.rx,
      top: frame.y - frame.ry,
      width: frame.rx * 2,
      height: frame.ry * 2,
    }),
    [frame.x, frame.y, frame.rx, frame.ry],
  );

  return (
    <section className="sky-atlas" aria-labelledby="sky-atlas-title">
      <header className="sky-atlas-header">
        <div>
          <h1 id="sky-atlas-title" className="title-page">
            Sky Atlas
          </h1>
          <p className="lede">
            Find a position in the sky and open the real SPHEREx observations
            behind it.
          </p>
        </div>
        <span className="sky-atlas-reference">
          ICRS coordinates, J2000 axes
        </span>
      </header>
      <div className="sky-atlas-shell">
        <div className="sky-atlas-map">
          <div className="sky-atlas-tools">
            <div className="sky-atlas-search" ref={searchBox}>
              <form
                onSubmit={handleSearch}
                role="search"
                aria-label="Sky atlas"
              >
                <button type="submit" aria-label="Find object">
                  <Search size={16} />
                </button>
                <input
                  aria-label="Object name or RA and Dec"
                  value={search}
                  placeholder="Find a star, target, or RA, Dec"
                  onFocus={() => setSearchOpen(true)}
                  onChange={(event) => {
                    setSearch(event.target.value);
                    setSearchError("");
                    setSearchOpen(true);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      setSearchOpen(false);
                      event.stopPropagation();
                    }
                  }}
                />
                {search && (
                  <button
                    type="button"
                    onClick={() => {
                      setSearch("");
                      setSearchError("");
                    }}
                    aria-label="Clear sky search"
                  >
                    <X size={13} />
                  </button>
                )}
              </form>
              {searchOpen && (
                <div className="sky-atlas-popover sky-atlas-search-results">
                  {searchError && <p role="status">{searchError}</p>}
                  {exactCoordinates && (
                    <button
                      onClick={() => searchResult(freeMark(exactCoordinates))}
                    >
                      <Crosshair size={15} />
                      <span>Go to coordinates</span>
                      <ChevronRight size={13} />
                    </button>
                  )}
                  <span className="sky-atlas-menu-head">
                    {centerLabel
                      ? "Matching landmarks and survey records"
                      : "Challenge targets"}
                  </span>
                  {matches.map((mark) => (
                    <button key={mark.id} onClick={() => searchResult(mark)}>
                      <i className={`sky-atlas-dot ${mark.kind}`} />
                      <span>
                        {mark.name}
                        <small>{labels[mark.kind]}</small>
                      </span>
                      <ChevronRight size={13} />
                    </button>
                  ))}
                  {!matches.length && !exactCoordinates && (
                    <p>
                      No matching landmark. Try coordinates such as{" "}
                      <code>269.4462, +4.7688</code>.
                    </p>
                  )}
                </div>
              )}
            </div>
            <div className="sky-atlas-controls">
              {view !== "accessible" && (
                <div className="sky-atlas-segment" aria-label="Sky projection">
                  <button
                    type="button"
                    aria-pressed={view === "globe"}
                    title="Celestial globe"
                    onClick={() => {
                      setView("globe");
                      setHover(null);
                    }}
                  >
                    <Globe2 size={16} />
                    <span>Globe</span>
                  </button>
                  <button
                    type="button"
                    aria-pressed={view === "map"}
                    title="Hammer all-sky map"
                    onClick={() => {
                      setView("map");
                      setHover(null);
                    }}
                  >
                    <Map size={16} />
                    <span>Map</span>
                  </button>
                </div>
              )}
              <div className="sky-atlas-layers" ref={layerBox}>
                <button
                  className="sky-atlas-layers-trigger"
                  type="button"
                  aria-expanded={layersOpen}
                  onClick={() => setLayersOpen(!layersOpen)}
                >
                  <Layers3 size={16} />
                  <span>Layers</span>
                  <small>{layersCount}</small>
                </button>
                {layersOpen && (
                  <div
                    className="sky-atlas-popover sky-atlas-layer-list"
                    onKeyDown={(event) => {
                      if (event.key === "Escape") setLayersOpen(false);
                    }}
                  >
                    <label
                      htmlFor="sky-atlas-background"
                      className="sky-atlas-menu-head"
                    >
                      Sky imagery
                    </label>
                    <select
                      id="sky-atlas-background"
                      value={backdrop}
                      onChange={(event) =>
                        setBackdrop(event.target.value as Backdrop)
                      }
                    >
                      <option value="optical">Optical, NASA SVS</option>
                      <option value="infrared">Infrared, SPHEREx DR1</option>
                      <option value="none">Coordinate guide only</option>
                    </select>
                    {backdrop === "optical" && (
                      <>
                        <label>
                          <input
                            type="checkbox"
                            checked={stars}
                            onChange={() => setStars(!stars)}
                          />{" "}
                          Bright stars
                        </label>
                        <label>
                          <input
                            type="checkbox"
                            checked={milkyWay}
                            onChange={() => setMilkyWay(!milkyWay)}
                          />{" "}
                          Milky Way imagery
                        </label>
                      </>
                    )}
                    <span className="sky-atlas-menu-head">Overlays</span>
                    {(Object.keys(navLayers) as Layer[]).map((layer) => (
                      <label key={layer}>
                        <input
                          type="checkbox"
                          checked={layers[layer]}
                          onChange={() =>
                            setLayers((value) => ({
                              ...value,
                              [layer]: !value[layer],
                            }))
                          }
                        />{" "}
                        {navLayers[layer].label}
                      </label>
                    ))}
                    {snapshotUnavailable && (
                      <p>Recorded survey records are unavailable.</p>
                    )}
                    {layers.bulk && bulk.unavailable && !bulk.snapshot && (
                      <p>Processed image footprints are unavailable.</p>
                    )}
                    {layers.fields && (
                      <p>
                        DeepTrace fields: cyan for completed, grey for waiting
                        or empty, lavender for incomplete, coral for error.
                      </p>
                    )}
                    {layers.tracks && (
                      <p>
                        Positions saved by the survey may be trial-track
                        samples. Check each candidate’s evidence.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
          <div
            className={`sky-atlas-stage ${dragging ? "is-dragging" : ""}`}
            ref={stage}
            tabIndex={0}
            role="region"
            aria-label="Interactive celestial coordinate map"
            aria-describedby="sky-atlas-help"
            onPointerDown={beginPan}
            onPointerMove={movePan}
            onPointerUp={endPan}
            onPointerCancel={() => {
              drag.current = null;
              setDragging(false);
            }}
            onPointerLeave={() => {
              setHover(null);
              if (readout.current) readout.current.textContent = "—";
            }}
            onKeyDown={(event) => {
              const delta = 5 / Math.max(camera.zoom, 0.68);
              if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                if (view === "accessible")
                  select(
                    freeMark({
                      ...selected,
                      ra: wrap(
                        selected.ra +
                          (event.key === "ArrowLeft" ? delta : -delta),
                      ),
                    }),
                  );
                else
                  aim({
                    ...camera,
                    ra:
                      camera.ra + (event.key === "ArrowLeft" ? delta : -delta),
                  });
              }
              if (event.key === "ArrowUp" || event.key === "ArrowDown") {
                event.preventDefault();
                const step = event.key === "ArrowUp" ? delta : -delta;
                if (view !== "globe")
                  select(
                    freeMark({
                      ...selected,
                      dec: clamp(selected.dec + step, -90, 90),
                    }),
                  );
                else aim({ ...camera, dec: camera.dec + step });
              }
              if (event.key === "+" || event.key === "=") {
                event.preventDefault();
                changeZoom(1.25);
              }
              if (event.key === "-") {
                event.preventDefault();
                changeZoom(0.8);
              }
              if (event.key === "Enter" && view !== "accessible") {
                event.preventDefault();
                select(
                  freeMark(view === "map" ? { ra: camera.ra, dec: 0 } : camera),
                );
              }
            }}
          >
            {view !== "accessible" ? (
              <AtlasBackground
                width={width}
                height={height}
                camera={camera}
                view={view}
                backdrop={textureFailed ? "none" : backdrop}
                stars={stars}
                milkyWay={milkyWay}
                onUnavailable={unavailable}
                onTextureError={textureError}
              />
            ) : (
              <div className="sky-atlas-flat-image" style={fillBackdrop}>
                {backdrop !== "none" && activeTexture && !textureFailed && (
                  <img
                    src={`/atlas/${activeTexture}.webp`}
                    alt=""
                    onError={() => textureError(activeTexture)}
                  />
                )}
              </div>
            )}
            <svg
              className="sky-atlas-overlay"
              width={width}
              height={height}
              viewBox={`0 0 ${width} ${height}`}
              aria-hidden="true"
            >
              {outlines.coords && (
                <path className="sky-atlas-grid" d={outlines.coords} />
              )}
              {gridLabels.map(
                ({ text, point }) =>
                  point && (
                    <text
                      className="sky-atlas-grid-label"
                      key={text}
                      x={point.x + 3}
                      y={point.y + 11}
                    >
                      {text}
                    </text>
                  ),
              )}
              {outlines.constellations.map((group) => (
                <g key={group.name}>
                  <path className="sky-atlas-constellation" d={group.path} />
                  {group.point && (
                    <text
                      className="sky-atlas-constellation-name"
                      x={group.point.x}
                      y={group.point.y - 15}
                    >
                      {group.name}
                    </text>
                  )}
                </g>
              ))}
              {outlines.ecliptic && (
                <path className="sky-atlas-ecliptic" d={outlines.ecliptic} />
              )}
              {outlines.galactic && (
                <path className="sky-atlas-galactic" d={outlines.galactic} />
              )}
              {footprintPath && (
                <path className="sky-atlas-bulk" d={footprintPath} />
              )}
              {outlines.tracks.map(({ id, path }) => (
                <path className="sky-atlas-track" key={id} d={path} />
              ))}
              {projectedMarks.map(({ x, y, mark }) => (
                <g
                  key={mark.id}
                  transform={`translate(${x},${y})`}
                  className={`sky-atlas-mark ${mark.kind}`}
                  data-status={mark.kind === "field" ? mark.status : undefined}
                >
                  <MarkSymbol kind={mark.kind} />
                  {mark.kind === "target" && !closePosition(mark, selected) && (
                    <text x="10" y="-8">
                      {mark.name}
                    </text>
                  )}
                </g>
              ))}
              {selectedPoint && (
                <g
                  transform={`translate(${selectedPoint.x},${selectedPoint.y})`}
                  className="sky-atlas-reticle"
                >
                  <circle r="12" />
                  <path d="M0 -18V-11 M0 11V18 M-18 0H-11 M11 0H18" />
                  <circle r="2.4" className="sky-atlas-solid" />
                  <text x="17" y="-14">
                    {selected.kind === "position" &&
                    selected.name === "Selected sky position"
                      ? "Selected position"
                      : selected.name}
                  </text>
                </g>
              )}
            </svg>
            {hover && (
              <span
                className="sky-atlas-tooltip"
                style={{
                  left: Math.min(hover.x + 13, width - 146),
                  top: Math.max(hover.y - 36, 6),
                }}
              >
                {hover.mark.name}
                {hover.mark.kind === "field" &&
                  hover.mark.status &&
                  `, ${displayStatus(hover.mark.status)}`}
              </span>
            )}
            <span id="sky-atlas-help" className="sky-atlas-visually-hidden">
              Use arrow keys to move, plus and minus to zoom, and Enter to
              select the centre. Object search and the challenge targets provide
              direct access to marked locations. The Open observations button
              searches SPHEREx at the selected position.
            </span>
          </div>
          {view !== "accessible" && (
            <div className="sky-atlas-zoom">
              <button
                type="button"
                aria-label="Centre on selection"
                title="Centre on selection"
                onClick={() => aim(selected)}
              >
                <Focus size={17} />
              </button>
              <button
                type="button"
                aria-label="Zoom in"
                title="Zoom in"
                disabled={camera.zoom >= 3.8}
                onClick={() => changeZoom(1.25)}
              >
                <Plus size={18} />
              </button>
              <button
                type="button"
                aria-label="Zoom out"
                title="Zoom out"
                disabled={camera.zoom <= 0.68}
                onClick={() => changeZoom(0.8)}
              >
                <Minus size={18} />
              </button>
            </div>
          )}
          <div className="sky-atlas-map-info">
            <span className="sky-atlas-projection">
              <span />
              {view === "globe"
                ? "Orthographic globe"
                : view === "map"
                  ? "Hammer equal-area map"
                  : "Equatorial flat map"}
            </span>
            <span className="sky-atlas-pointer" ref={readout}>
              —
            </span>
            <span className="sky-atlas-orientation">
              North up, RA increases left
            </span>
          </div>
        </div>
        <aside className="sky-atlas-sidebar" aria-label="Selected sky field">
          <div className="sky-atlas-selection" aria-live="polite">
            <div className="sky-atlas-rail-label">Active field</div>
            <div className="sky-atlas-selection-title">
              <h2>{selected.name}</h2>
              <button
                className="sky-atlas-bookmark"
                type="button"
                onClick={toggleBookmark}
                aria-label={isSaved ? "Remove saved field" : "Save field"}
                aria-pressed={isSaved}
              >
                {isSaved ? <Check size={16} /> : <Bookmark size={16} />}
              </button>
            </div>
            <span className="sky-atlas-classification">
              {selected.status
                ? displayStatus(selected.status)
                : labels[selected.kind]}
            </span>
            <dl className="sky-atlas-coordinates">
              <div>
                <dt>Right ascension</dt>
                <dd>{displayDegree(selected.ra)}</dd>
              </div>
              <div>
                <dt>Declination</dt>
                <dd>{displayDegree(selected.dec, true)}</dd>
              </div>
            </dl>
            {selected.note && <p>{selected.note}</p>}
            {field && (
              <p>
                {field.latest?.observationsAnalyzed ?? 0} observations analyzed
                for detector {field.detector || "auto"} in the published survey
                record.{field.latest?.message ? ` ${field.latest.message}` : ""}
              </p>
            )}
            {candidate && (
              <p>
                {candidate.observations.length} source observations on record
                {Number.isFinite(candidate.evidence.nominalSnr)
                  ? `, nominal S/N ${candidate.evidence.nominalSnr?.toFixed(2)}`
                  : ""}
                .
              </p>
            )}
            <button
              className="sky-atlas-open"
              type="button"
              onClick={() => onNavigate(selected.ra, selected.dec)}
            >
              Open observations <ArrowUpRight size={16} />
            </button>
            {candidate && onCandidate && (
              <button
                className="sky-atlas-secondary"
                type="button"
                onClick={() => onCandidate(candidate.id)}
              >
                Investigate candidate <ArrowDownRight size={14} />
              </button>
            )}
            {selected.source && (
              <a
                className="sky-atlas-source"
                href={selected.source}
                target="_blank"
                rel="noreferrer"
              >
                Catalog record <ArrowUpRight size={12} />
              </a>
            )}
          </div>
          <div className="sky-atlas-targets">
            <div className="sky-atlas-rail-label">Challenge targets</div>
            {targetMarks.map((mark) => (
              <button
                key={mark.id}
                type="button"
                className={selected.id === mark.id ? "is-selected" : ""}
                onClick={() => select(mark, true)}
              >
                <span className="sky-atlas-dot target" />
                <span>{mark.name}</span>
                <ChevronRight size={14} />
              </button>
            ))}
          </div>
          {bookmarks.length > 0 && (
            <div className="sky-atlas-targets sky-atlas-saved">
              <div className="sky-atlas-rail-label">Saved fields</div>
              {bookmarks.map((mark) => (
                <button
                  key={`${mark.id}-${mark.ra}-${mark.dec}`}
                  type="button"
                  onClick={() => restoreBookmark(mark)}
                >
                  <Bookmark size={12} />
                  <span>
                    {mark.name === "Selected sky position"
                      ? `${displayDegree(mark.ra)} / ${displayDegree(mark.dec, true)}`
                      : mark.name}
                  </span>
                  <ChevronRight size={14} />
                </button>
              ))}
            </div>
          )}
        </aside>
      </div>
      <footer className="sky-atlas-footer">
        <div>
          <span className="sky-atlas-credit">
            {view === "accessible"
              ? "WebGL unavailable. Interactive equatorial map. "
              : ""}
            {textureFailed ? (
              "Sky imagery unavailable. Coordinates and overlays remain usable. "
            ) : backdrop === "infrared" ? (
              <>
                Infrared:{" "}
                <a href={infraredSource} target="_blank" rel="noreferrer">
                  SPHEREx DR1 HiPS frame 42
                </a>
                , NASA/IPAC IRSA. Display preview.
              </>
            ) : backdrop === "optical" ? (
              <>
                Optical:{" "}
                <a href={opticalSource} target="_blank" rel="noreferrer">
                  Deep Star Maps
                </a>
                , NASA SVS, from Gaia DR2, Hipparcos and Tycho.
              </>
            ) : (
              "ICRS coordinates. Imagery off."
            )}
          </span>
          {layers.bulk && bulk.snapshot && (
            <span className="sky-atlas-survey-note">
              <span className="sky-atlas-bulk-key" />
              {Math.min(
                bulk.snapshot.footprints.length,
                1000,
              ).toLocaleString()}{" "}
              detector footprints shown
              {(bulk.snapshot.coverage.footprintsTruncated ||
                bulk.snapshot.footprints.length > 1000) &&
                ", map subset"}
              {", WCS image outlines. "}
              <a href="/?page=stats">Survey area and methods</a>
            </span>
          )}
          {snapshot && (layers.fields || layers.candidates) && (
            <span className="sky-atlas-survey-note">
              Published snapshot {snapshot.generatedAt.slice(0, 10)}:{" "}
              {snapshot.fields.length} recorded fields,{" "}
              {snapshot.candidates.length} recorded candidates
            </span>
          )}
        </div>
        <span className="sky-atlas-help">
          {view === "accessible"
            ? "Select a position to inspect"
            : "Drag to pan, scroll to zoom, click to select"}
        </span>
      </footer>
    </section>
  );
}
