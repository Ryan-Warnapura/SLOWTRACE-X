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
  overlayOpacity = 0.45,
  quality = false,
  track,
}: {
  frame?: Frame;
  reference?: Frame;
  mode: string;
  contrast: number;
  palette: string;
  scale?: [number, number];
  point: { x: number; y: number } | null;
  onPoint?: (p: { x: number; y: number }) => void;
  overlayOpacity?: number;
  quality?: boolean;
  track?: { x: number; y: number }[];
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const overlay = useRef<HTMLCanvasElement>(null);
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
        quality,
      );
    if (overlay.current && reference)
      renderPixels(
        overlay.current,
        reference,
        contrast,
        palette,
        undefined,
        scale,
        quality,
      );
  }, [frame, reference, mode, contrast, palette, scale, quality]);
  return (
    <div className="sky-canvas" ref={holder}>
      {frame ? (
        <div className="image-plane" style={{ transform: `scale(${zoom})` }}>
          <canvas
            ref={canvas}
            aria-label={
              onPoint
                ? "NASA SPHEREx observation. Click or use arrow keys to select a pixel."
                : "NASA SPHEREx observation"
            }
            tabIndex={onPoint ? 0 : undefined}
            onKeyDown={(e) => {
              const movement: Record<string, [number, number]> = {
                ArrowUp: [0, -1],
                ArrowDown: [0, 1],
                ArrowLeft: [-1, 0],
                ArrowRight: [1, 0],
              };
              const direction = movement[e.key];
              if (!direction || !onPoint) return;
              e.preventDefault();
              const previous = point ?? {
                x: Math.floor(frame.width / 2),
                y: Math.floor(frame.height / 2),
              };
              onPoint({
                x: Math.max(
                  0,
                  Math.min(frame.width - 1, previous.x + direction[0]),
                ),
                y: Math.max(
                  0,
                  Math.min(frame.height - 1, previous.y + direction[1]),
                ),
              });
            }}
            onClick={(e) => {
              if (!onPoint) return;
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
          {mode === "overlay" && reference && (
            <canvas
              ref={overlay}
              className="blended-exposure"
              style={{ opacity: overlayOpacity }}
              aria-hidden="true"
            />
          )}
          {track && track.length > 1 && (
            <svg
              className="image-track"
              viewBox={`0 0 ${frame.width} ${frame.height}`}
              aria-hidden="true"
            >
              <polyline
                points={track.map((p) => `${p.x + 0.5},${p.y + 0.5}`).join(" ")}
                fill="none"
                stroke="#a5efff"
                strokeWidth=".4"
                strokeDasharray="1 1"
              />
              {track.map((p, index) => (
                <circle
                  key={index}
                  cx={p.x + 0.5}
                  cy={p.y + 0.5}
                  r="1.3"
                  stroke="#98f1ff"
                  strokeWidth=".34"
                  fill="#16315f"
                />
              ))}
            </svg>
          )}
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
        {frame
          ? mode === "difference"
            ? "Difference image"
            : mode === "overlay"
              ? "Blended exposures"
              : "SPHEREx exposure"
          : "No exposure loaded"}
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
