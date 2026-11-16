export interface Query {
  ra: number;
  dec: number;
  fov: number;
  detector: number;
}
export interface Observation {
  id: string;
  collection: string;
  detector: number;
  mjd: number;
  date: string;
  url: string;
  cloudUrl?: string;
  startMjd?: number;
  endMjd?: number;
  footprint?: unknown;
  metadataSource?: string;
  metadataRetrievedAt?: string;
}
export interface SearchResult {
  query: Query;
  observations: Observation[];
  totalAvailable: number;
  truncated: boolean;
  queriedAt: string;
  source: string;
  status:
    | "live"
    | "partial-live"
    | "recorded-metadata"
    | "recorded-observations"
    | "specified-observations";
  warnings: string[];
  queryUrls: string[];
  archiveChecked?: string;
  searchCoverage?: Record<string, unknown>;
}
export interface Frame {
  width: number;
  height: number;
  data: (number | null)[];
  variance: (number | null)[];
  mask: number[];
  wavelength: (number | null)[];
  metadata: {
    id: string;
    detector: number;
    mjd: number;
    date: string;
    unit: string;
    pixelArcsec: number;
    center: { ra: number; dec: number } | number[];
    wavelengthMin: number | null;
    wavelengthMax: number | null;
    wavelengthCenter?: number | null;
    badFraction: number;
    saturatedFraction?: number;
    zodiSubtracted: boolean;
    calibrationVersion?: string;
    [key: string]: unknown;
  };
  provenance: {
    sourceUrl: string;
    cutoutUrl: string;
    retrievedAt: string;
    sha256: string;
    method: string;
    [key: string]: unknown;
  };
  warnings: string[];
}
export interface Target {
  name: string;
  ra: number;
  dec: number;
  type: string;
  note: string;
}
export const TARGETS: Target[] = [
  {
    name: "Barnard’s Star",
    ra: 269.4462,
    dec: 4.76883,
    type: "High proper motion star",
    note: "A nearby star with measurable motion. Coordinates are a field centre; motion and parallax change the source position.",
  },
  {
    name: "Epsilon Indi B",
    ra: 331.09668,
    dec: -56.80067,
    type: "Brown dwarf pair",
    note: "A nearby brown dwarf system. SPHEREx pixels cannot resolve the close binary.",
  },
  {
    name: "WISE 0855−0714",
    ra: 133.75969,
    dec: -7.24216,
    type: "Cold brown dwarf",
    note: "This cutout includes the challenge’s nominal coordinate (133.795129°, −7.245147°) at 5 arcmin or wider. A faint source may fall below the detection limit.",
  },
  {
    name: "RW Aurigae",
    ra: 76.95609,
    dec: 30.40113,
    type: "Variable young star",
    note: "Compare matched wavelengths before interpreting changes in brightness.",
  },
  {
    name: "R Draconis",
    ra: 248.16723,
    dec: 66.75502,
    type: "Long-period variable",
    note: "Inspect its infrared brightness over time. Wavelength and contamination affect the comparison.",
  },
];
export const DETECTORS = [
  "0.75–1.10",
  "1.10–1.64",
  "1.64–2.42",
  "2.42–3.82",
  "3.82–4.42",
  "4.42–5.00",
];
