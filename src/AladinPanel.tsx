import { useEffect, useRef, useState } from "react";

const SCRIPT =
  "https://aladin.cds.unistra.fr/AladinLite/api/v3/latest/aladin.js";
const SURVEYS = [
  { id: "CDS/P/allWISE/color", label: "AllWISE color" },
  { id: "CDS/P/2MASS/color", label: "2MASS" },
  { id: "CDS/P/DSS2/color", label: "DSS2" },
];
const CATALOGS = {
  gaia: { id: "I/355/gaiadr3", label: "Gaia DR3", color: "#f5a524" },
  wise: { id: "II/328/allwise", label: "AllWISE", color: "#e6e6e6" },
} as const;
type CatalogKey = keyof typeof CATALOGS;
type AladinApi = any;

let loader: Promise<AladinApi> | undefined;
function loadAladin(): Promise<AladinApi> {
  loader ??= new Promise<AladinApi>((resolve, reject) => {
    const ready = () => {
      const A = (window as any).A;
      if (!A) return reject(new Error("Aladin Lite did not load."));
      Promise.resolve(A.init).then(() => resolve(A), reject);
    };
    if ((window as any).A) return ready();
    const script = document.createElement("script");
    script.src = SCRIPT;
    script.async = true;
    script.onload = ready;
    script.onerror = () => reject(new Error("Aladin Lite is unreachable."));
    document.head.appendChild(script);
  }).catch((error) => {
    loader = undefined;
    throw error;
  });
  return loader;
}

export default function AladinPanel({
  ra,
  dec,
  fovArcmin,
}: {
  ra: number;
  dec: number;
  fovArcmin: number;
}) {
  const [open, setOpen] = useState(false);
  const [survey, setSurvey] = useState(SURVEYS[0].id);
  const [shown, setShown] = useState<Record<CatalogKey, boolean>>({
    gaia: false,
    wise: false,
  });
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">(
    "idle",
  );
  const holder = useRef<HTMLDivElement>(null);
  const view = useRef<AladinApi>(null);
  const api = useRef<AladinApi>(null);
  const layers = useRef<Partial<Record<CatalogKey, AladinApi>>>({});
  const fov = fovArcmin / 60;

  useEffect(() => {
    if (!open || view.current || !holder.current) return;
    let cancelled = false;
    setState("loading");
    loadAladin()
      .then((A) => {
        if (cancelled || !holder.current) return;
        api.current = A;
        view.current = A.aladin(holder.current, {
          survey,
          target: `${ra} ${dec}`,
          fov,
          cooFrame: "ICRSd",
          showReticle: true,
          showFullscreenControl: false,
          showLayersControl: false,
          showGotoControl: false,
          showProjectionControl: false,
          showFrame: false,
        });
        setState("ready");
      })
      .catch(() => !cancelled && setState("error"));
    return () => {
      cancelled = true;
    };
    // Created once per open; later changes are applied by the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  useEffect(() => {
    if (state !== "ready") return;
    try {
      view.current.gotoRaDec(ra, dec);
      view.current.setFoV(fov);
    } catch {
      setState("error");
    }
  }, [ra, dec, fov, state]);

  useEffect(() => {
    if (state !== "ready") return;
    try {
      view.current.setImageSurvey(survey);
    } catch {
      setState("error");
    }
  }, [survey, state]);

  useEffect(() => {
    if (state !== "ready") return;
    try {
      for (const key of Object.keys(CATALOGS) as CatalogKey[]) {
        const existing = layers.current[key];
        if (existing) {
          if (shown[key]) existing.show();
          else existing.hide();
        } else if (shown[key]) {
          const layer = api.current.catalogFromVizieR(
            CATALOGS[key].id,
            `${ra} ${dec}`,
            Math.max(fov, 0.05),
            { onClick: "showTable", color: CATALOGS[key].color, sourceSize: 10 },
          );
          view.current.addCatalog(layer);
          layers.current[key] = layer;
        }
      }
    } catch {
      setState("error");
    }
    // Catalogs are fetched around the position that was current when enabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shown, state]);

  useEffect(() => {
    // A new field needs fresh catalog queries.
    for (const layer of Object.values(layers.current)) {
      try {
        layer?.hide();
      } catch {
        /* layer already gone */
      }
    }
    layers.current = {};
    setShown({ gaia: false, wise: false });
  }, [ra, dec]);

  return (
    <details
      className="sky-context"
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary>Sky context</summary>
      <div className="sky-context-controls">
        <select
          aria-label="Background survey"
          value={survey}
          onChange={(e) => setSurvey(e.target.value)}
        >
          {SURVEYS.map((s) => (
            <option key={s.id} value={s.id}>
              {s.label}
            </option>
          ))}
        </select>
        {(Object.keys(CATALOGS) as CatalogKey[]).map((key) => (
          <label key={key} className="ob-check">
            <input
              type="checkbox"
              checked={shown[key]}
              disabled={state !== "ready"}
              onChange={(e) =>
                setShown((current) => ({ ...current, [key]: e.target.checked }))
              }
            />
            {CATALOGS[key].label}
          </label>
        ))}
      </div>
      {state === "error" ? (
        <p className="ob-note">
          Sky context is unavailable (could not reach the CDS Aladin service).
          The SPHEREx viewer is unaffected.
        </p>
      ) : (
        <div className="sky-context-view" ref={holder}>
          {state === "loading" && <span className="ob-note">Loading…</span>}
        </div>
      )}
    </details>
  );
}
