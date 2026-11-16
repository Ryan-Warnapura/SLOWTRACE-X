import { useEffect, useRef } from "react";
import {
  ClampToEdgeWrapping,
  LinearFilter,
  Mesh,
  OrthographicCamera,
  PlaneGeometry,
  RepeatWrapping,
  Scene,
  ShaderMaterial,
  Texture,
  TextureLoader,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { basis, viewport } from "./geometry";
import type { Camera, View } from "./geometry";

export type Backdrop = "optical" | "infrared" | "none";
const vertex = `
varying vec2 screenUV;
void main() {
  screenUV = uv;
  gl_Position = vec4(position.xy, 0.0, 1.0);
}`;
const fragment = `
precision highp float;
uniform vec2 size;
uniform vec2 radius;
uniform vec3 forwardAxis;
uniform vec3 rightAxis;
uniform vec3 upAxis;
uniform float meridian;
uniform int projectionKind;
uniform int backdropKind;
uniform bool showStars;
uniform bool showMilkyWay;
uniform sampler2D opticalMap;
uniform sampler2D starsMap;
uniform sampler2D milkyWayMap;
uniform sampler2D infraredMap;
varying vec2 screenUV;
const float PI = 3.141592653589793;

vec2 skyUV(vec3 direction) {
  float ra = atan(direction.z, direction.x);
  float dec = asin(clamp(direction.y, -1.0, 1.0));
  return vec2(fract(0.5 - ra / (2.0 * PI)), 0.5 + dec / PI);
}

void main() {
  vec2 p = (screenUV - 0.5) * size / radius;
  float r2 = dot(p, p);
  if (r2 > 1.0) discard;

  vec3 direction;
  if (projectionKind == 0) {
    direction = rightAxis * p.x + upAxis * p.y + forwardAxis * sqrt(max(0.0, 1.0 - r2));
  } else {
    vec2 hammer = p * vec2(sqrt(8.0), sqrt(2.0));
    float z = sqrt(max(0.0, 1.0 - hammer.x*hammer.x/16.0 - hammer.y*hammer.y/4.0));
    float lon = 2.0 * atan(z * hammer.x, 2.0 * (2.0 * z*z - 1.0));
    float dec = asin(clamp(z * hammer.y, -1.0, 1.0));
    float ra = meridian - lon;
    direction = vec3(cos(dec)*cos(ra), sin(dec), cos(dec)*sin(ra));
  }
  vec2 sampleUV = skyUV(direction);
  vec3 light = vec3(0.0);
  if (backdropKind == 1) {
    light = texture2D(infraredMap, sampleUV).rgb;
    light = light * vec3(0.66, 0.81, 1.02);
  } else if (backdropKind == 0) {
    if (showStars && showMilkyWay) light = texture2D(opticalMap, sampleUV).rgb;
    else if (showStars) light = texture2D(starsMap, sampleUV).rgb;
    else if (showMilkyWay) light = texture2D(milkyWayMap, sampleUV).rgb;
    light = light * vec3(0.82, 0.9, 1.04);
  }
  float edge = smoothstep(0.77, 1.0, r2);
  float rim = smoothstep(0.988, 1.0, r2);
  vec3 base = vec3(0.016, 0.027, 0.053) + vec3(0.012, 0.022, 0.042) * (p.y * .5 + .5);
  vec3 color = base + light * (1.0 - edge * .42);
  color += vec3(.14, .34, .58) * rim * (0.65 + p.y * .25);
  gl_FragColor = vec4(color, 1.0);
}`;

type Props = {
  width: number;
  height: number;
  camera: Camera;
  view: Exclude<View, "accessible">;
  backdrop: Backdrop;
  stars: boolean;
  milkyWay: boolean;
  onUnavailable: () => void;
  onTextureError: (name: string) => void;
};

export default function AtlasBackground({
  width,
  height,
  camera,
  view,
  backdrop,
  stars,
  milkyWay,
  onUnavailable,
  onTextureError,
}: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const engine = useRef<{
    renderer: WebGLRenderer;
    material: ShaderMaterial;
    scene: Scene;
    camera: OrthographicCamera;
    draw: () => void;
    loadTexture: (name: string) => void;
  } | null>(null);
  const textureError = useRef(onTextureError);
  textureError.current = onTextureError;

  useEffect(() => {
    if (!canvas.current) return;
    let renderer: WebGLRenderer;
    try {
      renderer = new WebGLRenderer({
        canvas: canvas.current,
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      onUnavailable();
      return;
    }
    const displayCanvas = canvas.current;
    const onContextLost = (event: Event) => {
      event.preventDefault();
      onUnavailable();
    };
    displayCanvas.addEventListener("webglcontextlost", onContextLost);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    const blank = new Texture();
    const material = new ShaderMaterial({
      vertexShader: vertex,
      fragmentShader: fragment,
      transparent: true,
      depthTest: false,
      depthWrite: false,
      uniforms: {
        size: { value: new Vector2(1, 1) },
        radius: { value: new Vector2(1, 1) },
        forwardAxis: { value: new Vector3() },
        rightAxis: { value: new Vector3() },
        upAxis: { value: new Vector3() },
        meridian: { value: 0 },
        projectionKind: { value: 0 },
        backdropKind: { value: 0 },
        showStars: { value: true },
        showMilkyWay: { value: true },
        opticalMap: { value: blank },
        starsMap: { value: blank },
        milkyWayMap: { value: blank },
        infraredMap: { value: blank },
      },
    });
    const scene = new Scene();
    const quad = new PlaneGeometry(2, 2);
    scene.add(new Mesh(quad, material));
    const renderCamera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 10);
    renderCamera.position.z = 1;
    const loaded = new Map<string, Texture>();
    const loader = new TextureLoader();
    const files: Record<string, string> = {
      opticalMap: "star-map",
      starsMap: "bright-stars",
      milkyWayMap: "milkyway",
      infraredMap: "spherex-dr1-frame42",
    };
    let active = true;
    const draw = () => renderer.render(scene, renderCamera);
    const loadTexture = (name: string) => {
      if (loaded.has(name)) return;
      const file = files[name];
      const texture = loader.load(
        `/atlas/${file}.webp`,
        (ready) => {
          if (!active) return;
          material.uniforms[name].value = ready;
          draw();
        },
        undefined,
        () => {
          if (active) textureError.current(file);
        },
      );
      texture.minFilter = LinearFilter;
      texture.magFilter = LinearFilter;
      texture.wrapS = RepeatWrapping;
      texture.wrapT = ClampToEdgeWrapping;
      texture.generateMipmaps = false;
      loaded.set(name, texture);
    };
    engine.current = {
      renderer,
      material,
      scene,
      camera: renderCamera,
      draw,
      loadTexture,
    };
    return () => {
      active = false;
      engine.current = null;
      displayCanvas.removeEventListener("webglcontextlost", onContextLost);
      for (const texture of loaded.values()) texture.dispose();
      blank.dispose();
      material.dispose();
      quad.dispose();
      renderer.dispose();
    };
  }, [onUnavailable]);

  useEffect(() => {
    const active = engine.current;
    if (!active || width < 1 || height < 1) return;
    active.renderer.setSize(width, height, false);
  }, [width, height]);

  useEffect(() => {
    const active = engine.current;
    if (!active || width < 1 || height < 1) return;
    const axes = basis(camera);
    const area = viewport(width, height, view, camera.zoom);
    const uniform = active.material.uniforms;
    uniform.size.value.set(width, height);
    uniform.radius.value.set(area.rx, area.ry);
    uniform.forwardAxis.value.fromArray(axes.forward);
    uniform.rightAxis.value.fromArray(axes.right);
    uniform.upAxis.value.fromArray(axes.up);
    uniform.meridian.value = (camera.ra * Math.PI) / 180;
    uniform.projectionKind.value = view === "globe" ? 0 : 1;
    uniform.backdropKind.value =
      backdrop === "optical" ? 0 : backdrop === "infrared" ? 1 : 2;
    uniform.showStars.value = stars;
    uniform.showMilkyWay.value = milkyWay;
    if (backdrop === "infrared") active.loadTexture("infraredMap");
    if (backdrop === "optical") {
      if (stars && milkyWay) active.loadTexture("opticalMap");
      else if (stars) active.loadTexture("starsMap");
      else if (milkyWay) active.loadTexture("milkyWayMap");
    }
    active.draw();
  }, [camera, width, height, view, backdrop, stars, milkyWay]);

  return (
    <canvas className="sky-atlas-canvas" ref={canvas} aria-hidden="true" />
  );
}
