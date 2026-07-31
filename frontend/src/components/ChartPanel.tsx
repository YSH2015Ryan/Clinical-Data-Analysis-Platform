/** ECharts 封装（docs/11 §3 ChartPanel）：初始化/resize/销毁 + 工具箱导出 PNG。 */

import * as echarts from "echarts";
import { useEffect, useRef } from "react";

export default function ChartPanel({
  option,
  height = 360,
}: {
  option: echarts.EChartsOption;
  height?: number;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<echarts.ECharts | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    chartRef.current = chart;
    chart.setOption(option);
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
      chartRef.current = null;
    };
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
