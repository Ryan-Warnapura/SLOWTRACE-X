import { useEffect, useRef, useState } from "react";
import { Crosshair, Expand, Minus, Plus } from "lucide-react";
import type { Frame } from "./types";
import { renderPixels } from "./lib";
export default function SkyCanvas({
  frame,
  reference,
  mode,
  contrast,
  palette,
  scale,
  point,
  onPoint,
}: {
  frame?: Frame;
  reference?: Frame;
  mode: string;
  contrast: number;
  palette: string;
  scale?: [number, number];
  point: { x: number; y: number } | null;
  onPoint: (p: { x: number; y: number }) => void;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const holder = useRef<HTMLDivElement>(null);
  const [zoom, setZoom] = useState(1);
  useEffect(() => {
    if (canvas.current && frame)
      renderPixels(
        canvas.current,
        frame,
        contrast,
        palette,
        mode === "difference" ? reference : undefined,
        scale,
      );
  }, [frame, reference, mode, contrast, palette, scale]);
  return (
    <div className="sky-canvas" ref={holder}>
      {frame ? (
        <div className="image-plane" style={{ transform: `scale(${zoom})` }}>
          <canvas
            ref={canvas}
            aria-label="NASA SPHEREx observation. Click to select a position for measurement."
            onClick={(e) => {
              const r = e.currentTarget.getBoundingClientRect();
              onPoint({
                x: Math.min(
                  frame.width - 1,
                  Math.max(
                    0,
                    Math.floor(((e.clientX - r.left) / r.width) * frame.width),
                  ),
                ),
                y: Math.min(
                  frame.height - 1,
                  Math.max(
                    0,
                    Math.floor(((e.clientY - r.top) / r.height) * frame.height),
                  ),
                ),
              });
            }}
          />
          {point && (
            <div
              className="source-ring"
              style={{
                left: `${((point.x + 0.5) / frame.width) * 100}%`,
                top: `${((point.y + 0.5) / frame.height) * 100}%`,
              }}
            />
          )}
        </div>
      ) : (
        <div className="empty-sky">
          <div className="reticle">
            <Crosshair size={34} />
          </div>
          <p>Your window into the infrared.</p>
          <span>Load a field to see actual SPHEREx observations.</span>
        </div>
      )}
      <div className="canvas-grid" aria-hidden="true" />
      <div className="compass" aria-label="North up, east left">
        <span>N</span>
        <i />
        <b>E</b>
      </div>
      <div className="canvas-caption">
        <span className="signal-dot" />{" "}
        {frame
          ? "NASA / SPHEREx · " +
            (mode === "difference"
              ? "PROCESSED DIFFERENCE"
              : "OBSERVED INFRARED LIGHT")
          : "ICRS · CELESTIAL COORDINATES"}
      </div>
      <div className="canvas-tools">
        <button
          aria-label="Zoom out"
          onClick={() => setZoom((z) => Math.max(1, z - 0.5))}
        >
          <Minus size={16} />
        </button>
        <span>{zoom.toFixed(1)}×</span>
        <button
          aria-label="Zoom in"
          onClick={() => setZoom((z) => Math.min(4, z + 0.5))}
        >
          <Plus size={16} />
        </button>
        <button aria-label="Reset view" onClick={() => setZoom(1)}>
          <Crosshair size={16} />
        </button>
        <button
          aria-label="Full screen viewer"
          onClick={() => {
            void holder.current?.requestFullscreen();
          }}
        >
          <Expand size={16} />
        </button>
      </div>
    </div>
  );
}
