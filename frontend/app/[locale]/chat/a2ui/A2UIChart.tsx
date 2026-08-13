import React from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { Card } from "antd";

interface ChartProps {
  chartType: string;
  data: {
    labels: string[];
    datasets: Array<{
      label: string;
      data: number[];
      color?: string;
    }>;
  };
  options?: {
    xAxis?: string;
    yAxis?: string;
    title?: string;
  };
}

const COLORS = [
  "#1677ff",
  "#52c41a",
  "#faad14",
  "#f5222d",
  "#722ed1",
  "#13c2c2",
  "#eb2f96",
  "#fa541c",
];

export const A2UIChart: React.FC<ChartProps> = ({
  chartType,
  data,
  options,
}) => {
  const { labels = [], datasets = [] } = data || {};

  const chartData = labels.map((label, index) => {
    const point: Record<string, string | number> = { name: label };
    datasets.forEach((dataset) => {
      point[dataset.label] = dataset.data[index] ?? 0;
    });
    return point;
  });

  const pieData =
    chartType === "pie" && datasets[0]
      ? labels.map((label, index) => ({
          name: label,
          value: datasets[0].data[index] ?? 0,
        }))
      : [];

  const renderChart = () => {
    switch (chartType) {
      case "bar":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                label={options?.xAxis ? { value: options.xAxis, position: "insideBottom", offset: -5 } : undefined}
              />
              <YAxis
                label={options?.yAxis ? { value: options.yAxis, angle: -90, position: "insideLeft" } : undefined}
              />
              <Tooltip />
              <Legend />
              {datasets.map((dataset, index) => (
                <Bar
                  key={index}
                  dataKey={dataset.label}
                  fill={dataset.color || COLORS[index % COLORS.length]}
                  radius={[4, 4, 0, 0]}
                />
              ))}
            </BarChart>
          </ResponsiveContainer>
        );

      case "line":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                label={options?.xAxis ? { value: options.xAxis, position: "insideBottom", offset: -5 } : undefined}
              />
              <YAxis
                label={options?.yAxis ? { value: options.yAxis, angle: -90, position: "insideLeft" } : undefined}
              />
              <Tooltip />
              <Legend />
              {datasets.map((dataset, index) => (
                <Line
                  key={index}
                  type="monotone"
                  dataKey={dataset.label}
                  stroke={dataset.color || COLORS[index % COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 4 }}
                />
              ))}
            </LineChart>
          </ResponsiveContainer>
        );

      case "pie":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <PieChart>
              <Pie
                data={pieData}
                cx="50%"
                cy="50%"
                labelLine={false}
                label={({ name, percent }) =>
                  `${name}: ${(percent * 100).toFixed(0)}%`
                }
                outerRadius={100}
                fill="#8884d8"
                dataKey="value"
              >
                {pieData.map((_, index) => (
                  <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                ))}
              </Pie>
              <Tooltip />
              <Legend />
            </PieChart>
          </ResponsiveContainer>
        );

      case "area":
        return (
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={chartData}>
              <defs>
                {datasets.map((dataset, index) => (
                  <linearGradient
                    key={index}
                    id={`color${index}`}
                    x1="0"
                    y1="0"
                    x2="0"
                    y2="1"
                  >
                    <stop
                      offset="5%"
                      stopColor={dataset.color || COLORS[index % COLORS.length]}
                      stopOpacity={0.8}
                    />
                    <stop
                      offset="95%"
                      stopColor={dataset.color || COLORS[index % COLORS.length]}
                      stopOpacity={0.1}
                    />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="name"
                label={options?.xAxis ? { value: options.xAxis, position: "insideBottom", offset: -5 } : undefined}
              />
              <YAxis
                label={options?.yAxis ? { value: options.yAxis, angle: -90, position: "insideLeft" } : undefined}
              />
              <Tooltip />
              <Legend />
              {datasets.map((dataset, index) => (
                <Area
                  key={index}
                  type="monotone"
                  dataKey={dataset.label}
                  stroke={dataset.color || COLORS[index % COLORS.length]}
                  fillOpacity={1}
                  fill={`url(#color${index})`}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        );

      default:
        return (
          <div style={{ textAlign: "center", padding: 20, color: "#999" }}>
            Unsupported chart type: {chartType}
          </div>
        );
    }
  };

  return (
    <Card
      size="small"
      style={{ marginBottom: 12 }}
      styles={{ body: { padding: 12 } }}
      title={options?.title}
    >
      {renderChart()}
    </Card>
  );
};

export default A2UIChart;
