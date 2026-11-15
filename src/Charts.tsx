import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ErrorBar,
  Legend,
} from "recharts";
export function SpectrumChart({
  data,
  axis = "wavelength",
}: {
  data: Record<string, unknown>[];
  axis?: string;
}) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 20, right: 30, bottom: 20, left: 20 }}>
          <CartesianGrid stroke="#2a3236" strokeDasharray="3 5" />
          <XAxis
            dataKey={axis}
            type="number"
            domain={["auto", "auto"]}
            tick={{ fill: "#91a1a4", fontSize: 11 }}
            name={axis === "wavelength" ? "Wavelength (µm)" : "MJD"}
            label={{
              value:
                axis === "wavelength"
                  ? "Approximate wavelength · µm"
                  : "Observation epoch · MJD",
              position: "bottom",
              fill: "#91a1a4",
              fontSize: 11,
            }}
          />
          <YAxis
            dataKey="value"
            type="number"
            tick={{ fill: "#91a1a4", fontSize: 11 }}
            name="Surface brightness"
            unit=" MJy/sr"
            width={65}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={{
              background: "#1b2327",
              border: "1px solid #3c494b",
              borderRadius: 8,
              color: "#e8eee8",
            }}
          />
          <Scatter
            name="Aperture − local background"
            data={data}
            fill="#d7f49c"
          >
            <ErrorBar
              dataKey="error"
              width={4}
              stroke="#8ba968"
              direction="y"
            />
          </Scatter>
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  );
}
export function PlannerChart({ data }: { data: Record<string, unknown>[] }) {
  return (
    <div className="chart">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart
          data={data}
          margin={{ top: 15, right: 25, bottom: 15, left: 0 }}
        >
          <CartesianGrid stroke="#2a3236" strokeDasharray="3 5" />
          <XAxis dataKey="time" tick={{ fill: "#91a1a4", fontSize: 10 }} />
          <YAxis
            domain={[-90, 90]}
            unit="°"
            tick={{ fill: "#91a1a4", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{
              background: "#1b2327",
              border: "1px solid #3c494b",
              color: "#e8eee8",
            }}
          />
          <Legend />
          <Line
            dataKey="altitude"
            name="Target altitude"
            stroke="#d7f49c"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="sun"
            name="Sun altitude"
            stroke="#ce9270"
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
