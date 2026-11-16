import { describe, expect, it } from "vitest";
import { pixelSky, skyPixel } from "./lib";
import { archiveFitsUrls, compareFrames, parseCoordinate } from "./observation";
import type { Frame } from "./types";

describe("TAN image coordinates", () => {
  const field = { ra: 359.99, dec: 32, fov: 5, detector: 1 };

  it("maps the geometric centre to the requested ICRS position", () => {
    const sky = pixelSky(47.5, 47.5, 96, 96, field);
    expect(sky.ra).toBeCloseTo(field.ra, 10);
    expect(sky.dec).toBeCloseTo(field.dec, 10);
  });

  it("wraps RA at zero with east left and north up", () => {
    const northwestInImage = pixelSky(0, 0, 96, 96, field);
    expect(northwestInImage.ra).toBeGreaterThan(0);
    expect(northwestInImage.ra).toBeLessThan(0.1);
    expect(northwestInImage.dec).toBeGreaterThan(field.dec);
    const southeastInImage = pixelSky(95, 95, 96, 96, field);
    expect(southeastInImage.ra).toBeLessThan(field.ra);
    expect(southeastInImage.dec).toBeLessThan(field.dec);
  });

  it("finds the original pixel for sky coordinates across zero RA", () => {
    const sky = pixelSky(13, 72, 96, 96, field);
    expect(skyPixel(sky.ra, sky.dec, 96, 96, field)).toEqual({ x: 13, y: 72 });
  });
});

describe("coordinate entry and comparison safety", () => {
  it("converts the official WISE coordinate without changing the sign", () => {
    expect(parseCoordinate("08h55m10.831s", "ra")).toBeCloseTo(133.79512917, 7);
    expect(parseCoordinate("−07d14m42.53s", "dec")).toBeCloseTo(-7.24514722, 7);
    expect(parseCoordinate("−00:30:00", "dec")).toBe(-0.5);
    expect(() => parseCoordinate("24:00:00", "ra")).toThrow();
    expect(() => parseCoordinate("+90:00:01", "dec")).toThrow();
  });

  it("prevents subtraction when band or processing is incompatible", () => {
    const a = {
      width: 96,
      height: 96,
      metadata: {
        pixelArcsec: 3,
        center: { ra: 10, dec: 5 },
        detector: 1,
        unit: "MJy/sr",
        zodiSubtracted: true,
        wavelengthCenter: 0.9,
      },
      provenance: { sourceUrl: "a" },
    } as Frame;
    const b = {
      ...a,
      metadata: { ...a.metadata, wavelengthCenter: 0.91 },
      provenance: { ...a.provenance, sourceUrl: "b" },
    };
    expect(compareFrames(a, b).eligible).toBe(true);
    expect(
      compareFrames(a, {
        ...b,
        metadata: { ...b.metadata, wavelengthCenter: 1 },
      }).eligible,
    ).toBe(false);
    expect(
      compareFrames(a, {
        ...b,
        metadata: { ...b.metadata, zodiSubtracted: false },
      }).eligible,
    ).toBe(false);
    expect(compareFrames(a, a).eligible).toBe(false);
  });

  it("only accepts whitelisted original FITS paths for manual cutouts", () => {
    const official =
      "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/example.fits";
    expect(archiveFitsUrls(`${official}\n${official}`)).toEqual([official]);
    expect(() =>
      archiveFitsUrls("https://unrelated.example/dr1.fits"),
    ).toThrow();
    expect(() => archiveFitsUrls(`${official}?center=5,5`)).toThrow();
  });
});
