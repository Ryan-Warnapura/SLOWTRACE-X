export type Sky = { ra: number; dec: number };
export type View = "globe" | "map" | "accessible";
export type Camera = Sky & { zoom: number };
export type Vec3 = [number, number, number];
export type Point = { x: number; y: number };
const radians = Math.PI / 180;
const hWidth = Math.sqrt(8);
const hHeight = Math.sqrt(2);
export const wrap = (value: number) => ((value % 360) + 360) % 360;
export const relative = (value: number) => wrap(value + 180) - 180;
export const clamp = (value: number, low: number, high: number) =>
  Math.min(high, Math.max(low, value));
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

export function unit({ ra, dec }: Sky): Vec3 {
  const a = ra * radians,
    d = dec * radians;
  return [Math.cos(d) * Math.cos(a), Math.sin(d), Math.cos(d) * Math.sin(a)];
}

export function direction([x, y, z]: Vec3): Sky {
  return {
    ra: wrap(Math.atan2(z, x) / radians),
    dec: Math.atan2(y, Math.hypot(x, z)) / radians,
  };
}

export function basis(position: Sky) {
  const a = position.ra * radians,
    d = position.dec * radians;
  return {
    forward: unit(position),
    right: [Math.sin(a), 0, -Math.cos(a)] as Vec3,
    up: [
      -Math.cos(a) * Math.sin(d),
      Math.cos(d),
      -Math.sin(a) * Math.sin(d),
    ] as Vec3,
  };
}

export function viewport(
  width: number,
  height: number,
  view: View,
  zoom: number,
) {
  const radius = Math.min(width * 0.445, height * 0.415) * zoom;
  const horizontal =
    Math.min(width * 0.465, height * 0.87) * (view === "accessible" ? 1 : zoom);
  const vertical = view === "globe" ? radius : horizontal / 2;
  return {
    x: width / 2,
    y: height / 2,
    rx: view === "globe" ? radius : horizontal,
    ry: vertical,
  };
}

export function project(
  sky: Sky,
  camera: Camera,
  view: View,
  width: number,
  height: number,
): Point | null {
  const area = viewport(width, height, view, camera.zoom);
  if (view === "globe") {
    const axes = basis(camera),
      vector = unit(sky);
    if (dot(axes.forward, vector) < 0.001) return null;
    return {
      x: area.x + dot(axes.right, vector) * area.rx,
      y: area.y - dot(axes.up, vector) * area.ry,
    };
  }
  const lon =
    view === "accessible" ? -relative(sky.ra) : -relative(sky.ra - camera.ra);
  if (view === "accessible")
    return {
      x: area.x + (lon / 180) * area.rx,
      y: area.y - (sky.dec / 90) * area.ry,
    };
  const a = lon * radians,
    d = sky.dec * radians;
  const scale = Math.sqrt(1 + Math.cos(d) * Math.cos(a / 2));
  return {
    x: area.x + ((Math.cos(d) * Math.sin(a / 2)) / scale) * area.rx,
    y: area.y - (Math.sin(d) / scale) * area.ry,
  };
}

export function unproject(
  point: Point,
  camera: Camera,
  view: View,
  width: number,
  height: number,
): Sky | null {
  const area = viewport(width, height, view, camera.zoom);
  const x = (point.x - area.x) / area.rx,
    y = (area.y - point.y) / area.ry;
  if (view === "accessible")
    return Math.abs(x) <= 1 && Math.abs(y) <= 1
      ? { ra: wrap(-x * 180), dec: y * 90 }
      : null;
  const r2 = x * x + y * y;
  if (r2 > 1) return null;
  if (view === "globe") {
    const axes = basis(camera),
      z = Math.sqrt(1 - r2);
    return direction(
      [0, 1, 2].map(
        (i) => axes.right[i] * x + axes.up[i] * y + axes.forward[i] * z,
      ) as Vec3,
    );
  }
  const a = x * hWidth,
    b = y * hHeight;
  const z = Math.sqrt(Math.max(0, 1 - (a * a) / 16 - (b * b) / 4));
  const lon = 2 * Math.atan2(z * a, 2 * (2 * z * z - 1));
  return {
    ra: wrap(camera.ra - lon / radians),
    dec: Math.asin(clamp(z * b, -1, 1)) / radians,
  };
}

export function arc(a: Sky, b: Sky, count = 12): Sky[] {
  const u = unit(a),
    v = unit(b),
    omega = Math.acos(clamp(dot(u, v), -1, 1));
  if (omega < 1e-7) return [a, b];
  return Array.from({ length: count + 1 }, (_, i) => {
    const t = i / count;
    const p = Math.sin((1 - t) * omega) / Math.sin(omega),
      q = Math.sin(t * omega) / Math.sin(omega);
    return direction([
      p * u[0] + q * v[0],
      p * u[1] + q * v[1],
      p * u[2] + q * v[2],
    ]);
  });
}

export const ecliptic = Array.from({ length: 361 }, (_, longitude) => {
  const a = longitude * radians,
    e = 23.4392911 * radians;
  return direction([
    Math.cos(a),
    Math.sin(a) * Math.sin(e),
    Math.sin(a) * Math.cos(e),
  ]);
});
export const galacticPlane = Array.from({ length: 361 }, (_, longitude) => {
  const a = longitude * radians,
    c = Math.cos(a),
    s = Math.sin(a);
  // Transpose of the ICRS → Galactic rotation, x,z are equatorial axes and y is the pole.
  return direction([
    -0.0548755604 * c + 0.4941094279 * s,
    -0.4838350155 * c + 0.7469822445 * s,
    -0.8734370902 * c - 0.44482963 * s,
  ]);
});
export const graticule = [
  ...[-60, -30, 0, 30, 60].map((dec) =>
    Array.from({ length: 181 }, (_, i) => ({ ra: i * 2, dec })),
  ),
  ...Array.from({ length: 12 }, (_, i) =>
    Array.from({ length: 91 }, (_j, j) => ({ ra: i * 30, dec: -90 + j * 2 })),
  ),
];
