import { useEffect, useState } from "react";

export default function App() {
  const [health, setHealth] = useState<string>("检查中…");

  useEffect(() => {
    fetch("/api/v1/healthz")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(() => setHealth("后端连接正常"))
      .catch(() => setHealth("后端未就绪"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", padding: 48 }}>
      <h1>CDAP 临床数据分析平台</h1>
      <p>M0 骨架运行中。API 状态：{health}</p>
    </main>
  );
}
