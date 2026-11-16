import {
  CartesianGrid,
  Cell,
  ReferenceLine,
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
import { wavelengthColor } from "./wavelength";

const AXIS = "#8d8b85";
const GRID = "#363a40";
const TOOLTIP = {
  background: "#2b2e33",
  border: "1px solid #4f545c",
  borderRadius: 2,
  color: "#efede6",
  fontSize: 12,
};
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
          <CartesianGrid stroke={GRID} strokeDasharray="2 4" />
          <XAxis
            dataKey={axis}
            type="number"
            domain={["auto", "auto"]}
            tick={{ fill: AXIS, fontSize: 11 }}
            name={axis === "wavelength" ? "Wavelength (µm)" : "MJD"}
            label={{
              value:
                axis === "wavelength"
                  ? "Approximate wavelength (µm)"
                  : "Observation date (MJD)",
              position: "bottom",
              fill: AXIS,
              fontSize: 11,
            }}
          />
          <YAxis
            dataKey="value"
            type="number"
            tick={{ fill: AXIS, fontSize: 11 }}
            name="Surface brightness"
            unit=" MJy/sr"
            width={88}
          />
          <Tooltip
            cursor={{ strokeDasharray: "3 3" }}
            contentStyle={TOOLTIP}
          />
          <Scatter
            name="Aperture − local background"
            data={data}
            fill="#efede6"
          >
            {data.map((sample, index) => (
              <Cell
                key={index}
                fill={wavelengthColor(sample.wavelength as number | null)}
              />
            ))}
            <ErrorBar
              dataKey="error"
              width={4}
              stroke="#b6b4ad"
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
          <CartesianGrid stroke={GRID} strokeDasharray="2 4" />
          <XAxis dataKey="time" tick={{ fill: AXIS, fontSize: 11 }} />
          <YAxis
            domain={[-90, 90]}
            unit="°"
            tick={{ fill: AXIS, fontSize: 11 }}
          />
          <Tooltip
            contentStyle={TOOLTIP}
          />
          <Legend wrapperStyle={{ fontSize: 12, color: AXIS }} />
          <ReferenceLine y={30} stroke={GRID} strokeDasharray="6 4" />
          <ReferenceLine y={-18} stroke={GRID} strokeDasharray="6 4" />
          <Line
            dataKey="altitude"
            name="Target altitude"
            stroke="#efede6"
            dot={false}
            isAnimationActive={false}
          />
          <Line
            dataKey="sun"
            name="Sun altitude"
            stroke="#f2b84b"
            dot={false}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
