import type { Frame } from "./types";

export const EXAMPLE_PATHS = [
  "/starter.json",
  "/examples/epsindib.json",
  "/examples/wise0855.json",
  "/examples/rwaur.json",
  "/examples/rdra.json",
];
const RESOLVING_POWER = [39, 41, 41, 35, 112, 128];

export function parseCoordinate(value: string, axis: "ra" | "dec") {
  const text = value.trim().replaceAll("−", "-").toLowerCase();
  if (!text) throw new Error("Enter both sky coordinates.");
  if (/^[+-]?(?:\d+(?:\.\d*)?|\.\d+)°?$/.test(text)) {
    const degrees = Number(text.replace("°", ""));
    if (axis === "ra" ? degrees >= 0 && degrees < 360 : Math.abs(degrees) <= 90)
      return degrees;
  } else {
    const match =
      /^([+-]?)(\d{1,3})\s*([hd°:]|\s)\s*(\d{1,2})\s*(?:[m′':]|\s)\s*(\d{1,2}(?:\.\d+)?)\s*[s″"]?$/.exec(
        text,
      );
    if (match) {
      const [, sign, first, separator, minutes, seconds] = match;
      const base =
        Number(first) + Number(minutes) / 60 + Number(seconds) / 3600;
      if (Number(minutes) < 60 && Number(seconds) < 60) {
        if (
          axis === "ra" &&
          separator !== "d" &&
          separator !== "°" &&
          sign !== "-" &&
          base < 24
        )
          return base * 15;
        if (axis === "dec" && separator !== "h" && base <= 90)
          return (sign === "-" ? -1 : 1) * base;
      }
    }
  }
  throw new Error(
    axis === "ra"
      ? "Use right ascension in degrees from 0 to <360, or hours as 08h55m10.831s."
      : "Use declination from −90° to +90°, or signed degrees as −07d14m42.53s.",
  );
}

export function compareFrames(a?: Frame, b?: Frame) {
  if (!a || !b)
    return {
      eligible: false,
      reason: "Load two observations to compare them.",
    };
  if (a.provenance.sourceUrl === b.provenance.sourceUrl)
    return {
      eligible: false,
      reason: "Select a different observation from the reference.",
    };
  if (
    a.width !== b.width ||
    a.height !== b.height ||
    a.metadata.pixelArcsec !== b.metadata.pixelArcsec ||
    JSON.stringify(a.metadata.center) !== JSON.stringify(b.metadata.center)
  )
    return {
      eligible: false,
      reason: "The two frames do not share a celestial grid.",
    };
  if (
    a.metadata.detector !== b.metadata.detector ||
    a.metadata.unit !== b.metadata.unit ||
    a.metadata.zodiSubtracted !== b.metadata.zodiSubtracted
  )
    return {
      eligible: false,
      reason:
        "Detector, brightness units or zodiacal-light processing differ. Use side-by-side comparison.",
    };
  const wa = a.metadata.wavelengthCenter;
  const wb = b.metadata.wavelengthCenter;
  const resolvingPower = RESOLVING_POWER[a.metadata.detector - 1];
  if (
    typeof wa !== "number" ||
    typeof wb !== "number" ||
    !(wa > 0 && wb > 0) ||
    !resolvingPower
  )
    return {
      eligible: false,
      reason:
        "A local wavelength estimate is unavailable. Use side-by-side comparison.",
    };
  if (Math.max(wa, wb) / Math.min(wa, wb) > 1 + 1 / resolvingPower)
    return {
      eligible: false,
      reason:
        "The centre wavelengths differ by more than one nominal resolution element. Blink and side by side remain available.",
    };
  if (a.metadata.calibrationVersion !== b.metadata.calibrationVersion)
    return {
      eligible: false,
      reason: "Calibration versions differ. Use side-by-side comparison.",
    };
  return {
    eligible: true,
    reason:
      "Approximate wavelength match at field centre. The detector PSFs are not matched. A residual can be instrumental.",
  };
}

export function archiveFitsUrls(input: string) {
  const urls = [...new Set(input.trim().split(/\s+/).filter(Boolean))];
  if (!urls.length || urls.length > 8)
    throw new Error("Enter one to eight distinct official Level 2 FITS URLs.");
  for (const link of urls) {
    const url = new URL(link);
    if (
      url.origin !== "https://irsa.ipac.caltech.edu" ||
      !/^\/ibe\/data\/spherex\/(?:dr1|qr3)\/level2\/[A-Za-z0-9_./-]+\.fits$/.test(
        url.pathname,
      ) ||
      url.search ||
      url.hash ||
      url.username ||
      url.password
    ) {
      throw new Error(
        "Use full original DR1 or QR3 FITS URLs from the NASA/IPAC IRSA archive.",
      );
    }
  }
  return urls;
}
