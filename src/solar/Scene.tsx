import { useEffect, useRef } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  BODY_COLORS,
  positionAt,
  skyVector,
  type CandidateDirection,
  type SolarEphemerides,
  type Vector,
} from "./ephemeris";

export type SolarView = "inner" | "outer" | "direction";
type RenderState = {
  jd: number;
  selected: string;
  paths: boolean;
  labels: boolean;
};
type Stage = {
  update: (state: RenderState) => void;
  zoom: (change: number) => void;
  reset: () => void;
};
const toScene = ([x, y, z]: Vector) => new THREE.Vector3(x, z, -y);

function circle(radius: number, angle = 0) {
  return Array.from({ length: 97 }, (_, i) => {
    const theta = (i * Math.PI) / 48;
    return new THREE.Vector3(
      radius * Math.cos(theta),
      radius * Math.sin(theta) * Math.sin(angle),
      radius * Math.sin(theta) * Math.cos(angle),
    );
  });
}

export default function Scene({
  data,
  view,
  focus,
  state,
  onSelect,
  onFail,
  zoomSignal,
  resetSignal,
}: {
  data: SolarEphemerides;
  view: SolarView;
  focus?: CandidateDirection;
  state: RenderState;
  onSelect: (id: string) => void;
  onFail: () => void;
  zoomSignal: { count: number; amount: number };
  resetSignal: number;
}) {
  const host = useRef<HTMLDivElement>(null);
  const callbacks = useRef({ onSelect, onFail });
  const initialState = useRef(state);
  const stage = useRef<Stage | null>(null);
  useEffect(() => {
    callbacks.current = { onSelect, onFail };
  }, [onSelect, onFail]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      callbacks.current.onFail();
      return;
    }
    renderer.domElement.setAttribute("aria-hidden", "true");
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(42, 1, 0.01, 1500);
    const controls = new OrbitControls(camera, renderer.domElement);
    const reducedMotion = matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    controls.enableDamping = !reducedMotion;
    controls.dampingFactor = 0.12;
    controls.minDistance = view === "direction" ? 1.6 : 0.22;
    controls.maxDistance = view === "direction" ? 8 : 250;
    controls.enablePan = view !== "direction";
    controls.rotateSpeed = 0.6;
    controls.zoomSpeed = 0.8;

    const tags: {
      key: string;
      node: HTMLDivElement;
      anchor: THREE.Vector3;
      marker?: THREE.Mesh;
    }[] = [];
    const markers = new Map<string, THREE.Mesh>();
    const tracks = new Map<
      string,
      THREE.Line<THREE.BufferGeometry, THREE.LineBasicMaterial>
    >();
    const grid = new THREE.Group();
    scene.add(grid);

    function addLine(
      points: THREE.Vector3[],
      color: string,
      opacity: number,
      group: THREE.Object3D = grid,
    ) {
      const geometry = new THREE.BufferGeometry().setFromPoints(points);
      const material = new THREE.LineBasicMaterial({
        color,
        transparent: true,
        opacity,
        depthWrite: false,
      });
      const line = new THREE.Line(geometry, material);
      group.add(line);
      return line;
    }
    function addTag(
      key: string,
      name: string,
      anchor: THREE.Vector3,
      marker?: THREE.Mesh,
    ) {
      const node = document.createElement("div");
      node.className = `solar-plot-label ${marker ? "body" : "axis"}`;
      node.textContent = name;
      node.setAttribute("aria-hidden", "true");
      element?.appendChild(node);
      tags.push({ key, node, anchor, marker });
    }
    function addMarker(key: string, name: string, position: THREE.Vector3) {
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(1, 18, 12),
        new THREE.MeshBasicMaterial({ color: BODY_COLORS[key] ?? "#8ceaff" }),
      );
      marker.userData.key = key;
      marker.position.copy(position);
      markers.set(key, marker);
      scene.add(marker);
      addTag(key, name, marker.position, marker);
      return marker;
    }

    if (view === "direction" && focus) {
      addLine(circle(1), "#7899c4", 0.34);
      addLine(circle(1, Math.PI / 2), "#7899c4", 0.34);
      addLine(
        circle(1, Math.PI / 2).map((p) =>
          p.applyAxisAngle(new THREE.Vector3(0, 1, 0), Math.PI / 2),
        ),
        "#7899c4",
        0.26,
      );
      addTag("ra0", "0h RA", new THREE.Vector3(1.08, 0, 0));
      addTag("north", "+90° Dec", new THREE.Vector3(0, 1.08, 0));
      const unit = toScene(skyVector(focus.ra, focus.dec));
      const ray = new THREE.ArrowHelper(
        unit,
        new THREE.Vector3(),
        1,
        0x76ebf7,
        0.12,
        0.065,
      );
      scene.add(ray);
      addMarker("earth", "Earth · direction origin", new THREE.Vector3());
      addMarker(
        "direction",
        focus.label || focus.id || "Selected sky direction",
        unit,
      );
    } else {
      const rings = view === "inner" ? [1, 2, 3, 5] : [5, 10, 20, 30];
      for (const r of rings) {
        addLine(circle(r), "#3b6388", 0.22);
        addTag(`ring-${r}`, `${r} au`, new THREE.Vector3(-r, 0, 0));
      }
      for (let i = 0; i < 8; i++) {
        const angle = (i * Math.PI) / 4,
          reach = rings[rings.length - 1];
        addLine(
          [
            new THREE.Vector3(),
            new THREE.Vector3(
              Math.cos(angle) * reach,
              0,
              Math.sin(angle) * reach,
            ),
          ],
          "#244567",
          0.22,
        );
      }
      addMarker("sun", "Sun", new THREE.Vector3());
      for (const [key, body] of Object.entries(data.bodies)) {
        addMarker(key, body.name, new THREE.Vector3());
        tracks.set(
          key,
          addLine(
            body.samples.map(([, x, y, z]) => toScene([x, y, z])),
            BODY_COLORS[key] ?? "#8ceaff",
            0.35,
            scene,
          ),
        );
      }
    }

    let current = initialState.current;
    let animation = 0;
    let hovered: string | null = null;
    let disposed = false;
    function draw() {
      animation = 0;
      if (disposed || !element) return;
      controls.update();
      const markerDistance = camera.position.distanceTo(controls.target);
      const width = element.clientWidth,
        height = element.clientHeight;
      if (width === 0 || height === 0) return;
      for (const [id, marker] of markers) {
        const multiplier =
          id === current.selected || id === hovered || id === "direction"
            ? 1.35
            : id === "sun"
              ? 1.6
              : 1;
        marker.scale.setScalar(markerDistance * 0.008 * multiplier);
      }
      renderer.render(scene, camera);
      for (const tag of tags) {
        const point = tag.anchor.clone().project(camera);
        const visible =
          tag.marker?.visible !== false &&
          point.z > -1 &&
          point.z < 1 &&
          Math.abs(point.x) < 0.98 &&
          Math.abs(point.y) < 0.91;
        const highlighted =
          tag.key === current.selected ||
          tag.key === hovered ||
          tag.key === "direction";
        tag.node.hidden = !visible || (!current.labels && !highlighted);
        if (tag.node.hidden) continue;
        tag.node.dataset.highlighted = String(highlighted);
        tag.node.style.transform = `translate(${((point.x + 1) * 0.5 * width + 9).toFixed(1)}px,${((1 - point.y) * 0.5 * height - 9).toFixed(1)}px)`;
      }
    }
    function invalidate() {
      if (!animation && !disposed) animation = requestAnimationFrame(draw);
    }
    function reset() {
      const reach = view === "direction" ? 1.45 : view === "inner" ? 5.25 : 26;
      controls.target.set(0, 0, 0);
      camera.position.set(reach * 0.82, reach * 1.14, reach * 1.45);
      controls.update();
      invalidate();
    }
    function update(next: RenderState) {
      current = next;
      if (view !== "direction") {
        for (const [id, body] of Object.entries(data.bodies)) {
          const marker = markers.get(id);
          const track = tracks.get(id);
          if (!marker || !track) continue;
          const position = positionAt(body.samples, next.jd);
          marker.visible = Boolean(position);
          if (position) marker.position.copy(toScene(position));
          track.visible = next.paths;
          track.material.opacity = id === next.selected ? 0.87 : 0.26;
        }
      }
      invalidate();
    }
    function resize() {
      if (!element || !element.clientHeight) return;
      renderer.setSize(element.clientWidth, element.clientHeight, false);
      camera.aspect = element.clientWidth / element.clientHeight;
      camera.updateProjectionMatrix();
      invalidate();
    }
    function zoom(change: number) {
      const distance = camera.position.distanceTo(controls.target);
      const target = THREE.MathUtils.clamp(
        distance * change,
        controls.minDistance,
        controls.maxDistance,
      );
      camera.position
        .sub(controls.target)
        .setLength(target)
        .add(controls.target);
      controls.update();
      invalidate();
    }
    const canvas = renderer.domElement;
    const pointer = new THREE.Vector2(),
      raycaster = new THREE.Raycaster();
    function hit(event: PointerEvent) {
      const box = canvas.getBoundingClientRect();
      pointer.set(
        (2 * (event.clientX - box.left)) / box.width - 1,
        1 - (2 * (event.clientY - box.top)) / box.height,
      );
      raycaster.setFromCamera(pointer, camera);
      const result = raycaster.intersectObjects(
        [...markers.values()].filter((m) => m.visible),
        false,
      )[0];
      return result ? String(result.object.userData.key) : null;
    }
    function move(event: PointerEvent) {
      const next = event.buttons ? null : hit(event);
      if (next === hovered) return;
      hovered = next;
      canvas.style.cursor = next ? "pointer" : "grab";
      invalidate();
    }
    let start: { x: number; y: number } | null = null;
    function down(event: PointerEvent) {
      start = { x: event.clientX, y: event.clientY };
    }
    function up(event: PointerEvent) {
      if (
        !start ||
        Math.hypot(start.x - event.clientX, start.y - event.clientY) > 6
      )
        return;
      const id = hit(event);
      if (id && view !== "direction") callbacks.current.onSelect(id);
      start = null;
    }
    function leave() {
      hovered = null;
      invalidate();
    }
    function fail(event: Event) {
      event.preventDefault();
      callbacks.current.onFail();
    }
    canvas.addEventListener("pointermove", move);
    canvas.addEventListener("pointerdown", down);
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointerleave", leave);
    canvas.addEventListener("webglcontextlost", fail);
    controls.addEventListener("change", invalidate);
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    stage.current = { update, reset, zoom };
    reset();
    resize();
    update(initialState.current);

    return () => {
      disposed = true;
      stage.current = null;
      if (animation) cancelAnimationFrame(animation);
      observer.disconnect();
      controls.removeEventListener("change", invalidate);
      controls.dispose();
      canvas.removeEventListener("pointermove", move);
      canvas.removeEventListener("pointerdown", down);
      canvas.removeEventListener("pointerup", up);
      canvas.removeEventListener("pointerleave", leave);
      canvas.removeEventListener("webglcontextlost", fail);
      scene.traverse((obj) => {
        if (!(obj instanceof THREE.Mesh || obj instanceof THREE.Line)) return;
        obj.geometry.dispose();
        for (const mat of Array.isArray(obj.material)
          ? obj.material
          : [obj.material])
          mat.dispose();
      });
      renderer.dispose();
      canvas.remove();
      tags.forEach((tag) => tag.node.remove());
    };
  }, [data, view, focus]);

  useEffect(() => {
    initialState.current = state;
    stage.current?.update(state);
  }, [state]);
  useEffect(() => {
    if (zoomSignal.count) stage.current?.zoom(zoomSignal.amount);
  }, [zoomSignal]);
  useEffect(() => {
    if (resetSignal) stage.current?.reset();
  }, [resetSignal]);
  return <div className="solar-canvas" ref={host} />;
}
