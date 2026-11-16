import { useEffect, useMemo, useRef, useState } from "react";
import { RotateCcw } from "lucide-react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Candidate } from "../surveyTypes";
import { dateOfMjd, finite, tangentOffsets } from "./data";

function trackSamples(candidate: Candidate) {
  const samples = (candidate.evidence.epochMeasurements ?? [])
    .filter(
      (sample) => finite(sample.ra) && finite(sample.dec) && finite(sample.mjd),
    )
    .sort((a, b) => a.mjd - b.mjd);
  const firstMjd = samples[0]?.mjd ?? 0;
  return samples.flatMap((sample) => {
    const offsets = tangentOffsets(candidate.ra, candidate.dec, sample);
    return offsets
      ? [
          {
            ...sample,
            ...offsets,
            sampleValid: sample.sampleValid,
            elapsed: sample.mjd - firstMjd,
          },
        ]
      : [];
  });
}

export default function TrackSpace({ candidate }: { candidate: Candidate }) {
  const mount = useRef<HTMLDivElement>(null);
  const reset = useRef<() => void>(() => undefined);
  const highlight = useRef<(index: number) => void>(() => undefined);
  const [activeIndex, setActiveIndex] = useState(0);
  const [unavailable, setUnavailable] = useState(false);
  const samples = useMemo(() => trackSamples(candidate), [candidate]);
  const active = samples[Math.min(activeIndex, samples.length - 1)];

  useEffect(() => {
    const surface = mount.current;
    if (!surface || samples.length < 2) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setUnavailable(true);
      return;
    }
    setUnavailable(false);
    setActiveIndex(0);
    renderer.setClearColor(0x07111f, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    renderer.domElement.setAttribute("aria-hidden", "true");
    surface.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(37, 1, 0.05, 60);
    camera.position.set(4.2, 3.0, 5.1);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.minDistance = 2.5;
    controls.maxDistance = 13;
    controls.target.set(0, 0, 0);
    controls.enablePan = true;
    controls.update();
    controls.saveState();

    const angularRange = Math.max(
      0.01,
      ...samples.flatMap((sample) => [
        Math.abs(sample.east),
        Math.abs(sample.north),
      ]),
    );
    const timeRange = Math.max(0.01, samples[samples.length - 1].elapsed);
    const path = samples.map(
      (sample) =>
        new THREE.Vector3(
          sample.east / angularRange,
          sample.north / angularRange,
          (2 * sample.elapsed) / timeRange - 1,
        ),
    );
    const render = () => renderer.render(scene, camera);

    const grid = new THREE.GridHelper(2.4, 8, 0x2e5374, 0x1c324b);
    grid.position.y = -1.2;
    scene.add(grid);
    const line = (points: THREE.Vector3[], color: number, opacity = 1) => {
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const material = new THREE.LineBasicMaterial({
        color,
        transparent: opacity < 1,
        opacity,
      });
      const segment = new THREE.Line(geometry, material);
      scene.add(segment);
      return segment;
    };
    const origin = new THREE.Vector3(-1.2, -1.2, -1.2);
    line([origin, new THREE.Vector3(1.3, -1.2, -1.2)], 0x6cd3fb, 0.85);
    line([origin, new THREE.Vector3(-1.2, 1.3, -1.2)], 0xa7a1ff, 0.85);
    line([origin, new THREE.Vector3(-1.2, -1.2, 1.3)], 0xffad82, 0.85);
    line(path, 0x7ce4ff, 0.8);
    line(
      path.map((point) => new THREE.Vector3(point.x, -1.19, point.z)),
      0x456b90,
      0.7,
    );

    const geometry = new THREE.SphereGeometry(0.063, 16, 10);
    const markers = path.map((point, index) => {
      line([point, new THREE.Vector3(point.x, -1.19, point.z)], 0x6385ab, 0.36);
      const color = samples[index].sampleValid === false ? 0xffac82 : 0x87e6ff;
      const marker = new THREE.Mesh(
        geometry,
        new THREE.MeshBasicMaterial({ color }),
      );
      marker.position.copy(point);
      scene.add(marker);
      return marker;
    });
    highlight.current = (index) => {
      for (const [itemIndex, marker] of markers.entries())
        marker.scale.setScalar(index === itemIndex ? 1.6 : 1);
      render();
    };
    reset.current = () => {
      controls.reset();
      render();
    };

    const resize = new ResizeObserver(() => {
      const width = surface.clientWidth;
      const height = surface.clientHeight;
      if (!width || !height) return;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height, false);
      render();
    });
    resize.observe(surface);
    controls.addEventListener("change", render);
    const raycaster = new THREE.Raycaster();
    const pointer = new THREE.Vector2();
    const start = new THREE.Vector2();
    const pointerDown = (event: PointerEvent) => {
      start.set(event.clientX, event.clientY);
    };
    const pointerUp = (event: PointerEvent) => {
      if (start.distanceTo(new THREE.Vector2(event.clientX, event.clientY)) > 6)
        return;
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.set(
        (2 * (event.clientX - bounds.left)) / bounds.width - 1,
        1 - (2 * (event.clientY - bounds.top)) / bounds.height,
      );
      raycaster.setFromCamera(pointer, camera);
      const hit = raycaster.intersectObjects(markers, false)[0];
      if (hit)
        setActiveIndex(markers.indexOf(hit.object as (typeof markers)[number]));
    };
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    highlight.current(0);

    return () => {
      resize.disconnect();
      controls.removeEventListener("change", render);
      renderer.domElement.removeEventListener("pointerdown", pointerDown);
      renderer.domElement.removeEventListener("pointerup", pointerUp);
      controls.dispose();
      scene.traverse((item) => {
        if (!(item instanceof THREE.Mesh) && !(item instanceof THREE.Line))
          return;
        item.geometry.dispose();
        const materials = Array.isArray(item.material)
          ? item.material
          : [item.material];
        materials.forEach((material: THREE.Material) => material.dispose());
      });
      renderer.dispose();
      renderer.domElement.remove();
      reset.current = () => undefined;
      highlight.current = () => undefined;
    };
  }, [samples]);

  useEffect(() => {
    highlight.current(activeIndex);
  }, [activeIndex]);

  if (samples.length < 2)
    return (
      <div className="stats-chart-empty" role="status">
        At least two documented epochs are needed to show a track.
      </div>
    );
  return (
    <div className="stats-track">
      <div className="stats-track-view">
        <div ref={mount} className="stats-track-canvas" />
        {unavailable ? (
          <span className="stats-track-fallback" role="status">
            The 3D viewer is unavailable. Select an epoch to inspect its
            numerical position below.
          </span>
        ) : (
          <>
            <button
              className="stats-track-reset"
              type="button"
              title="Reset track camera"
              aria-label="Reset track camera"
              onClick={() => reset.current()}
            >
              <RotateCcw size={14} />
            </button>
            <span className="stats-track-help">
              Drag to orbit · scroll or pinch to zoom
            </span>
          </>
        )}
      </div>
      <div className="stats-legend">
        <span>
          <i style={{ background: "#6cd3fb" }} /> East (″)
        </span>
        <span>
          <i style={{ background: "#a7a1ff" }} /> North (″)
        </span>
        <span>
          <i style={{ background: "#ffad82" }} /> Time (days)
        </span>
      </div>
      <div className="stats-track-epochs" aria-label="Track observation epochs">
        {samples.map((sample, index) => (
          <button
            type="button"
            key={`${sample.mjd}-${index}`}
            aria-pressed={index === activeIndex}
            onClick={() => setActiveIndex(index)}
          >
            {dateOfMjd(sample.mjd)}
          </button>
        ))}
      </div>
      {active && (
        <p className="stats-track-current" aria-live="polite">
          Day {active.elapsed.toFixed(2)} · E {active.east.toFixed(2)}″ · N{" "}
          {active.north.toFixed(2)}″
          {active.sampleValid === false ? " · pixel rejected" : ""}
        </p>
      )}
      <p className="stats-plot-note">
        Angular axes share a scale. Time is scaled independently. Coordinates
        come from the motion trial and do not determine a distance or orbit.
      </p>
    </div>
  );
}
