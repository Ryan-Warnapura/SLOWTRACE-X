import { parseCoordinate } from "../observation";
import type { Candidate, SurveyField } from "../surveyTypes";
import type { Target } from "../types";
import { arc, direction, unit } from "./geometry";
import type { Sky } from "./geometry";

export type Mark = Sky & {
  id: string;
  name: string;
  kind: "target" | "star" | "object" | "candidate" | "field" | "position";
  note?: string;
  status?: string;
  alias?: string;
  source?: string;
  candidate?: Candidate;
  field?: SurveyField;
};
const simbad = (id: string) =>
  `https://simbad.cds.unistra.fr/simbad/sim-id?Ident=${encodeURIComponent(id)}`;
function catalog(
  kind: "star" | "object",
  name: string,
  ra: number,
  dec: number,
  note?: string,
  alias?: string,
): Mark {
  return {
    id: `catalog-${name}`,
    name,
    ra,
    dec,
    note,
    kind,
    alias,
    source: simbad(alias ?? name),
  };
}

// Rounded J2000 positions of bright navigational landmarks and deep-sky objects.
// Each marker links to its individual CDS SIMBAD record, where full precision is available.
const stars = [
  catalog("star", "Sirius", 101.2872, -16.7161, "A1V star · Canis Major"),
  catalog("star", "Canopus", 95.988, -52.6957, "Bright star · Carina"),
  catalog("star", "Arcturus", 213.9153, 19.1824, "K giant · Boötes"),
  catalog("star", "Vega", 279.2347, 38.7837, "A0V star · Lyra"),
  catalog("star", "Capella", 79.1723, 45.998, "Multiple-star system · Auriga"),
  catalog("star", "Rigel", 78.6345, -8.2016, "Blue supergiant · Orion"),
  catalog("star", "Betelgeuse", 88.7929, 7.4071, "Red supergiant · Orion"),
  catalog("star", "Altair", 297.6958, 8.8683, "A-type star · Aquila"),
  catalog("star", "Aldebaran", 68.9802, 16.5093, "K giant · Taurus"),
  catalog("star", "Antares", 247.3519, -26.432, "Red supergiant · Scorpius"),
  catalog("star", "Spica", 201.2983, -11.1613, "Binary star · Virgo"),
  catalog("star", "Deneb", 310.358, 45.2803, "A-type supergiant · Cygnus"),
  catalog("star", "Polaris", 37.9546, 89.2641, "Cepheid variable · Ursa Minor"),
  catalog(
    "star",
    "Alpha Centauri",
    219.9021,
    -60.8339,
    "Nearby multiple-star system",
  ),
  catalog(
    "star",
    "Fomalhaut",
    344.4127,
    -29.6222,
    "A-type star · Piscis Austrinus",
  ),
  catalog("star", "Achernar", 24.4285, -57.2368, "B-type star · Eridanus"),
  catalog("star", "Acrux", 186.6496, -63.0991, "Multiple-star system · Crux"),
  catalog("star", "Regulus", 152.0929, 11.9672, "Multiple-star system · Leo"),
];

const deepSky = [
  catalog(
    "object",
    "Andromeda Galaxy",
    10.6847,
    41.2688,
    "Nearby spiral galaxy",
    "M31",
  ),
  catalog(
    "object",
    "Orion Nebula",
    83.8221,
    -5.3911,
    "Star-forming nebula",
    "M42",
  ),
  catalog("object", "Pleiades", 56.75, 24.1167, "Open star cluster", "M45"),
  catalog(
    "object",
    "Omega Centauri",
    201.697,
    -47.4795,
    "Globular star cluster",
    "NGC 5139",
  ),
  catalog(
    "object",
    "Galactic Centre",
    266.4168,
    -29.0078,
    "Radio source at the Milky Way centre",
    "Sgr A*",
  ),
  catalog(
    "object",
    "Whirlpool Galaxy",
    202.4696,
    47.1952,
    "Interacting spiral galaxy",
    "M51",
  ),
  catalog(
    "object",
    "Large Magellanic Cloud",
    80.8942,
    -69.7561,
    "Satellite galaxy",
    "LMC",
  ),
  catalog(
    "object",
    "Small Magellanic Cloud",
    13.1875,
    -72.8286,
    "Satellite galaxy",
    "SMC",
  ),
];
export const fixedMarks = [...deepSky, ...stars];

export function targetMark(target: Target): Mark {
  return {
    ...target,
    id: `target-${target.name}`,
    kind: "target",
    note: `${target.type}. ${target.note}`,
  };
}
export function candidateMark(candidate: Candidate): Mark {
  return {
    ra: candidate.ra,
    dec: candidate.dec,
    id: candidate.id,
    name: candidate.id,
    kind: "candidate",
    status: candidate.classification,
    candidate,
  };
}
export function fieldMark(field: SurveyField): Mark {
  return {
    ra: field.ra,
    dec: field.dec,
    id: field.id,
    name: field.label,
    kind: "field",
    status: field.status,
    field,
  };
}
export function freeMark(position: Sky): Mark {
  return {
    ...position,
    id: "coordinate",
    name: "Selected sky position",
    kind: "position",
  };
}

export function coordinateText(text: string): Sky | null {
  const normalized = text.trim().replaceAll("−", "-");
  const parts = normalized.includes(",")
    ? normalized.split(",")
    : normalized.split(/\s+/);
  if (parts.length !== 2) return null;
  try {
    return {
      ra: parseCoordinate(parts[0], "ra"),
      dec: parseCoordinate(parts[1], "dec"),
    };
  } catch {
    return null;
  }
}

const connected: Record<string, [number, number][][]> = {
  Orion: [
    [
      [88.793, 7.407],
      [81.283, 6.35],
      [81.119, -2.397],
      [78.634, -8.202],
      [86.939, -9.67],
      [85.19, -1.943],
      [88.793, 7.407],
    ],
    [
      [81.119, -2.397],
      [84.053, -1.202],
      [85.19, -1.943],
    ],
  ],
  "Ursa Major": [
    [
      [165.46, 56.382],
      [165.932, 61.751],
      [178.458, 53.695],
      [183.856, 57.033],
      [193.507, 55.96],
      [200.981, 54.925],
      [206.885, 49.313],
    ],
    [
      [178.458, 53.695],
      [165.46, 56.382],
    ],
  ],
  Cassiopeia: [
    [
      [2.295, 59.15],
      [10.127, 56.537],
      [14.177, 60.717],
      [21.454, 60.235],
      [28.599, 63.67],
    ],
  ],
  Cygnus: [
    [
      [310.358, 45.28],
      [305.557, 40.257],
      [292.68, 27.96],
    ],
    [
      [296.244, 45.131],
      [305.557, 40.257],
      [311.553, 33.97],
    ],
  ],
  Crux: [
    [
      [186.65, -63.099],
      [187.791, -57.113],
    ],
    [
      [183.786, -58.749],
      [191.93, -59.689],
    ],
  ],
  Taurus: [
    [
      [81.573, 28.608],
      [67.165, 15.871],
      [64.948, 15.628],
      [65.734, 17.543],
      [68.98, 16.509],
      [84.411, 21.142],
    ],
  ],
  Scorpius: [
    [
      [241.359, -19.806],
      [245.297, -25.593],
      [247.352, -26.432],
      [248.971, -28.216],
      [252.968, -38.047],
      [253.498, -42.362],
      [258.038, -43.239],
      [264.33, -42.998],
      [265.622, -39.03],
      [263.402, -37.104],
    ],
  ],
  Leo: [
    [
      [152.093, 11.967],
      [151.833, 16.763],
      [154.993, 19.842],
      [154.173, 23.417],
      [148.191, 26.007],
      [146.462, 23.774],
    ],
    [
      [152.093, 11.967],
      [168.56, 15.43],
      [177.265, 14.572],
      [168.527, 20.524],
      [168.56, 15.43],
    ],
  ],
};

export const asterisms = Object.entries(connected).map(([name, groups]) => {
  const stars = groups.flat().map(([ra, dec]) => ({ ra, dec }));
  const sum = stars
    .map(unit)
    .reduce((a, b): [number, number, number] => [
      a[0] + b[0],
      a[1] + b[1],
      a[2] + b[2],
    ]);
  return {
    name,
    centroid: direction(sum),
    paths: groups.map((group) =>
      group.flatMap(([ra, dec], i) =>
        i
          ? arc({ ra: group[i - 1][0], dec: group[i - 1][1] }, { ra, dec })
          : [{ ra, dec }],
      ),
    ),
  };
});
