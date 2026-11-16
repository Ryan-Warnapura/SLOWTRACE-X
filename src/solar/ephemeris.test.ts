import { describe, expect, it } from "vitest";
import type { Candidate } from "../surveyTypes";
import { solarAssociation, type SolarEphemerides } from "./ephemeris";

const link = (target: string, origin = "https://ssd.jpl.nasa.gov") =>
  `${origin}/api/horizons.api?COMMAND=${encodeURIComponent(`'${target}'`)}`;

const bodies: SolarEphemerides["bodies"] = {
  ceres: {
    name: "Ceres",
    classification: "Dwarf planet",
    target: "1 Ceres",
    source: link("1;"),
    samples: [],
  },
  interstellar: {
    name: "3I/ATLAS",
    classification: "Comet",
    target: "3I/ATLAS",
    source: link("DES=3I;"),
    samples: [],
  },
};

function track(command: string, observerRobust = true, source = link(command)) {
  return {
    name: command,
    url: source,
    status: "ok",
    withinTolerance: 2,
    samples: [
      { mjd: 61003, observerRobust },
      { mjd: 61004, observerRobust },
    ],
  };
}

function candidate(
  tracks: ReturnType<typeof track>[],
  classification = "catalog-consistent",
): Candidate {
  return {
    id: "test-candidate",
    fieldId: "test-field",
    analysisId: "test-analysis",
    ra: 10,
    dec: 20,
    referenceMjd: 61003,
    detector: 1,
    fov: 5,
    classification,
    observations: [],
    evidence: {},
    catalogInvestigation: {
      classification,
      jpl: { status: "ok", horizons: tracks },
    },
  };
}

describe("published solar catalog associations", () => {
  it("selects the correct existing vector series by official Horizons target", () => {
    expect(solarAssociation(candidate([track("1;")]), bodies)?.bodyId).toBe(
      "ceres",
    );
    expect(
      solarAssociation(candidate([track("DES=C/2025 N1;CAP;NOFRAG")]), bodies)
        ?.bodyId,
    ).toBe("interstellar");
  });

  it("exposes official JPL measurements without inventing a physical position", () => {
    const found = solarAssociation(candidate([track("4;")]), bodies);
    expect(found?.bodyId).toBeUndefined();
    expect(found?.evidenceUrl).toBe(link("4;"));
  });

  it("keeps ambiguous, observer-dependent, and unresolved records direction-only", () => {
    expect(
      solarAssociation(candidate([track("1;"), track("4;")]), bodies),
    ).toBeNull();
    expect(
      solarAssociation(candidate([track("1;", false)]), bodies),
    ).toBeNull();
    expect(
      solarAssociation(
        candidate([track("1;")], "insufficient-evidence"),
        bodies,
      ),
    ).toBeNull();
    expect(
      solarAssociation(
        candidate([track("1;", true, link("1;", "https://example.com"))]),
        bodies,
      ),
    ).toBeNull();
  });
});
