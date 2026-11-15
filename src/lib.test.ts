import { describe, expect, it } from "vitest";
import { pixelSky } from "./lib";

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
});
