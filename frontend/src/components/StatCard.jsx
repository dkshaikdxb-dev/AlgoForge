export default function StatCard({ label, value, sub, tone = "neutral", testid }) {
  const tones = {
    neutral: "text-white",
    profit: "txt-profit",
    loss: "txt-loss",
    warn: "txt-warn",
  };
  return (
    <div data-testid={testid} className="panel panel-hover p-5">
      <div className="overline">{label}</div>
      <div className={`kpi-num text-4xl mt-2 ${tones[tone]}`}>{value}</div>
      {sub && <div className="text-xs txt-muted font-mono-data mt-2">{sub}</div>}
    </div>
  );
}
