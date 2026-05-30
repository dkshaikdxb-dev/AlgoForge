const ITEM_STYLES = {
  strengths: { label: "Strengths", marker: "+", markerCls: "txt-profit" },
  concerns: { label: "Concerns", marker: "−", markerCls: "txt-loss" },
  suggestions: { label: "Suggestions", marker: "→", markerCls: "txt-warn" },
};

function Section({ kind, items }) {
  if (!items?.length) return null;
  const { label, marker, markerCls } = ITEM_STYLES[kind];
  return (
    <div>
      <div className="overline mb-1.5">{label}</div>
      <ul className="text-sm space-y-1">
        {items.map((x) => (
          <li key={`${kind}-${x}`} className="flex gap-2">
            <span className={markerCls}>{marker}</span>
            {x}
          </li>
        ))}
      </ul>
    </div>
  );
}

function verdictTone(v) {
  if (v === "HIGH") return "txt-loss";
  if (v === "MEDIUM") return "txt-warn";
  return "txt-profit";
}

export default function AiRiskReviewPanel({ risk }) {
  return (
    <div className="panel p-5">
      <div className="overline mb-3">AI risk review · Claude Sonnet 4.5</div>
      {!risk && (
        <div className="txt-muted text-sm">Click "AI risk review" to get Claude's structured analysis.</div>
      )}
      {risk && (
        <div data-testid="risk-review-output" className="space-y-4">
          <div className="flex items-center gap-3">
            <div className={`kpi-num text-5xl ${verdictTone(risk.verdict)}`}>{risk.risk_score}</div>
            <div>
              <div className="overline">Risk score</div>
              <div className={`font-section text-lg ${verdictTone(risk.verdict)}`}>{risk.verdict}</div>
            </div>
          </div>
          <p className="text-sm txt-secondary">{risk.summary}</p>
          <Section kind="strengths" items={risk.strengths} />
          <Section kind="concerns" items={risk.concerns} />
          <Section kind="suggestions" items={risk.suggestions} />
        </div>
      )}
    </div>
  );
}
