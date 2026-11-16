import { useEffect, useMemo, useRef, useState } from "react";
import { Crosshair } from "lucide-react";
import { fmt, quantile } from "./lib";

type Values = (number | null)[];
type Peak = {
  x: number;
  y: number;
  nominalSnr?: number;
  snrGainOverStatic?: number | null;
  velocityWestArcsecDay?: number;
  velocitySouthArcsecDay?: number;
};
type Maps = {
  width: number;
  height: number;
  stack?: Values;
  difference?: Values;
  searchSnr?: Values;
  candidates?: Peak[];
};
const PLANES = [
  { key: "stack", label: "Stationary stack", unit: "MJy/sr" },
  { key: "difference", label: "First-to-last difference", unit: "MJy/sr" },
  { key: "searchSnr", label: "Best trial S/N", unit: "nominal S/N" },
] as const;

export default function EvidenceMaps({
  analysis,
  onPeak,
}: {
  analysis: Maps;
  onPeak?: (peak: Peak) => void;
}) {
  const [selected, setSelected] =
    useState<(typeof PLANES)[number]["key"]>("searchSnr");
  const [hover, setHover] = useState<{ x: number; y: number } | null>(null);
  const [peakIndex, setPeakIndex] = useState<number | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const values = analysis[selected];
  const plane = PLANES.find((item) => item.key === selected)!;
  const peaks = analysis.candidates ?? [];
  const peak = peakIndex === null ? null : peaks[peakIndex];
  const domain = useMemo(() => {
    if (!values) return [0, 1];
    const finite = values.filter(
      (v): v is number => typeof v === "number" && Number.isFinite(v),
    );
    if (selected === "difference") {
      const maximum = quantile(finite.map(Math.abs), 0.985) || 1;
      return [-maximum, maximum];
    }
    return [quantile(finite, 0.02), quantile(finite, 0.99)];
  }, [selected, values]);
  useEffect(() => {
    const ctx = canvas.current?.getContext("2d");
    if (!ctx || !values) return;
    const { width, height } = analysis;
    const image = ctx.createImageData(width, height);
    for (let i = 0; i < width * height; i++) {
      const v = values[i];
      let red = 9,
        green = 10,
        blue = 12;
      if (v !== null && Number.isFinite(v)) {
        const t = Math.max(
          0,
          Math.min(1, (v - domain[0]) / (domain[1] - domain[0] || 1)),
        );
        if (selected === "difference") {
          const a = Math.abs(2 * t - 1);
          red = 30 + a * (t < 0.5 ? 39 : 216);
          green = 32 + a * (t < 0.5 ? 114 : 107);
          blue = 35 + a * (t < 0.5 ? 220 : 51);
        } else {
          const a = Math.pow(t, selected === "stack" ? 0.45 : 0.85);
          red = a * 239;
          green = a * 237;
          blue = a * 230;
        }
      }
      image.data.set([red, green, blue, 255], 4 * i);
    }
    ctx.putImageData(image, 0, 0);
  }, [analysis.width, analysis.height, domain, selected, values]);
  if (!values || !analysis.width || !analysis.height) return null;
  return (
    <section
      className="evidence-map"
      aria-label="DeepTrace processed image layers"
    >
      <div className="segmented" aria-label="Processed image layer">
        {PLANES.filter((p) => analysis[p.key]).map((p) => (
          <button
            key={p.key}
            className={selected === p.key ? "selected" : ""}
            aria-pressed={selected === p.key}
            onClick={() => setSelected(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>
      <div className="evidence-map-layout">
        <figure>
          <div className="evidence-raster">
            <canvas
              ref={canvas}
              width={analysis.width}
              height={analysis.height}
              aria-label={plane.label}
              onPointerMove={(e) => {
                const bounds = e.currentTarget.getBoundingClientRect();
                setHover({
                  x: Math.min(
                    analysis.width - 1,
                    Math.max(
                      0,
                      Math.floor(
                        ((e.clientX - bounds.left) * analysis.width) /
                          bounds.width,
                      ),
                    ),
                  ),
                  y: Math.min(
                    analysis.height - 1,
                    Math.max(
                      0,
                      Math.floor(
                        ((e.clientY - bounds.top) * analysis.height) /
                          bounds.height,
                      ),
                    ),
                  ),
                });
              }}
              onPointerLeave={() => setHover(null)}
            />
            {peaks.map((p, index) => (
              <button
                key={index}
                className="map-peak"
                style={{
                  left: `${((p.x + 0.5) * 100) / analysis.width}%`,
                  top: `${((p.y + 0.5) * 100) / analysis.height}%`,
                }}
                aria-label={`Select peak ${index + 1}`}
                aria-pressed={peakIndex === index}
                onClick={() => setPeakIndex(index)}
              >
                <span>{index + 1}</span>
              </button>
            ))}
          </div>
          <div
            className={`evidence-scale ${selected === "difference" ? "diverging" : ""}`}
            aria-hidden="true"
          />
          <figcaption>
            {fmt(domain[0], 2)} <span>{plane.unit}</span> {fmt(domain[1], 2)}
          </figcaption>
        </figure>
        <div className="evidence-readout">
          <h4 className="title-module">{plane.label}</h4>
          <p>
            {selected === "searchSnr"
              ? "Each pixel displays the strongest nominal signal-to-noise among the velocities tested."
              : selected === "difference"
                ? "Last minus first compatible exposure. PSF and wavelength differences can leave residuals."
                : "Variance-weighted combination at zero trial velocity."}
          </p>
          {hover && (
            <p className="caption">
              Pixel {hover.x}, {hover.y}:{" "}
              {fmt(values[hover.y * analysis.width + hover.x], 3)} {plane.unit}
            </p>
          )}
          {peaks.length > 0 && (
            <label className="stacked-label">
              Inspect a peak
              <select
                value={peakIndex ?? ""}
                onChange={(e) =>
                  setPeakIndex(
                    e.target.value === "" ? null : Number(e.target.value),
                  )
                }
              >
                <option value="">Choose a peak</option>
                {peaks.map((p, i) => (
                  <option key={i} value={i}>
                    Peak {i + 1}, S/N {fmt(p.nominalSnr, 1)}
                  </option>
                ))}
              </select>
            </label>
          )}
          {peak && (
            <>
              <dl className="metadata">
                <div>
                  <dt>Gain over stationary</dt>
                  <dd>{fmt(peak.snrGainOverStatic, 2)}</dd>
                </div>
                <div>
                  <dt>Trial west / south</dt>
                  <dd>
                    {fmt(peak.velocityWestArcsecDay, 3)} /{" "}
                    {fmt(peak.velocitySouthArcsecDay, 3)} ″/day
                  </dd>
                </div>
              </dl>
              {onPeak && (
                <button className="secondary" onClick={() => onPeak(peak)}>
                  Investigate selected peak
                </button>
              )}
            </>
          )}
          <p className="caption">
            Display stretch only. Nominal S/N omits the trials correction and
            correlated noise.
          </p>
        </div>
      </div>
    </section>
  );
}
