import type { Query, Target } from "./types";
export default function Atlas({
  query,
  targets,
  onNavigate,
}: {
  query: Query;
  targets: Target[];
  onNavigate: (ra: number, dec: number) => void;
}) {
  return (
    <div className="atlas">
      <div className="panel-heading">
        <div>
          <span className="eyebrow">ICRS COORDINATE ATLAS</span>
          <h2>Choose your next field.</h2>
        </div>
        <span className="tag">Click to investigate</span>
      </div>
      <svg
        viewBox="0 0 960 480"
        role="img"
        aria-label="Interactive sky coordinate grid. Click to search any sky position."
        onClick={(e) => {
          const r = e.currentTarget.getBoundingClientRect();
          onNavigate(
            360 * (1 - (e.clientX - r.left) / r.width),
            90 - (180 * (e.clientY - r.top)) / r.height,
          );
        }}
      >
        <rect width="960" height="480" fill="#0b1115" />
        {Array.from({ length: 13 }, (_, i) => (
          <g key={`v${i}`}>
            <path
              d={`M ${i * 80} 0 V480`}
              stroke="#273438"
              strokeDasharray="2 6"
            />
            {i > 0 && i < 12 && (
              <text x={i * 80 + 7} y="25" fill="#74888b" fontSize="11">
                {360 - i * 30}°
              </text>
            )}
          </g>
        ))}
        {Array.from({ length: 7 }, (_, i) => (
          <g key={`h${i}`}>
            <path
              d={`M0 ${i * 80} H960`}
              stroke={i === 3 ? "#4a5f5e" : "#273438"}
              strokeDasharray="2 6"
            />
            {i > 0 && i < 6 && (
              <text x="12" y={i * 80 - 9} fill="#74888b" fontSize="11">
                {90 - i * 30}°
              </text>
            )}
          </g>
        ))}
        {targets.map((t) => (
          <g
            key={t.name}
            transform={`translate(${((360 - t.ra) / 360) * 960} ${((90 - t.dec) / 180) * 480})`}
            onClick={(e) => {
              e.stopPropagation();
              onNavigate(t.ra, t.dec);
            }}
          >
            <circle r="17" fill="transparent" />
            <circle r="4" fill="#d7f49c" />
            <text x="11" y="4" fontSize="11" fill="#dbe5d2">
              {t.name}
            </text>
          </g>
        ))}
        <g
          transform={`translate(${((360 - query.ra) / 360) * 960} ${((90 - query.dec) / 180) * 480})`}
        >
          <circle r="14" fill="none" stroke="#d7f49c" />
          <path
            d="M-21 0 H-10 M10 0 H21 M0-21 V-10 M0 10 V21"
            stroke="#d7f49c"
          />
        </g>
      </svg>
      <p className="caption">
        An equatorial coordinate map, not an all-sky coverage claim. Points are
        the five official challenge targets. Every position opens a new archive
        query.
      </p>
    </div>
  );
}
