function formatCellValue(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function buildTableColumns(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return [];
  }
  const ordered = [];
  rows.forEach((row) => {
    if (!row || typeof row !== "object") {
      return;
    }
    Object.keys(row).forEach((key) => {
      if (!ordered.includes(key)) {
        ordered.push(key);
      }
    });
  });
  return ordered;
}

function toNumeric(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function extractGraphPoints(payload) {
  if (!payload || typeof payload !== "object") {
    return [];
  }

  if (Array.isArray(payload.labels) && Array.isArray(payload.datasets) && payload.datasets.length > 0) {
    const dataset = payload.datasets[0] || {};
    const values = Array.isArray(dataset.data) ? dataset.data : [];
    return payload.labels
      .map((label, index) => {
        const y = toNumeric(values[index]);
        if (y === null) {
          return null;
        }
        return { x: String(label), y };
      })
      .filter(Boolean);
  }

  if (Array.isArray(payload.series) && payload.series.length > 0) {
    const firstRow = payload.series[0];
    if (!firstRow || typeof firstRow !== "object") {
      return [];
    }

    const xKey = payload.x_key || Object.keys(firstRow)[0];
    const yKey =
      payload.y_key ||
      Object.keys(firstRow).find((key) => key !== xKey && toNumeric(firstRow[key]) !== null) ||
      Object.keys(firstRow)[1];

    if (!xKey || !yKey) {
      return [];
    }

    return payload.series
      .map((row) => {
        if (!row || typeof row !== "object") {
          return null;
        }
        const y = toNumeric(row[yKey]);
        if (y === null) {
          return null;
        }
        return { x: String(row[xKey]), y };
      })
      .filter(Boolean);
  }

  return [];
}

function GraphView({ payload }) {
  const chartType = payload?.chart_type === "line" ? "line" : "bar";
  const points = extractGraphPoints(payload);

  if (points.length === 0) {
    return <pre>{JSON.stringify(payload, null, 2)}</pre>;
  }

  const maxY = Math.max(...points.map((point) => point.y), 1);
  const width = 760;
  const height = 260;
  const padLeft = 46;
  const padRight = 12;
  const padTop = 18;
  const padBottom = 34;
  const chartWidth = width - padLeft - padRight;
  const chartHeight = height - padTop - padBottom;

  const xStep = points.length > 1 ? chartWidth / (points.length - 1) : chartWidth / 2;

  const svgPoints = points.map((point, index) => {
    const x = points.length > 1 ? padLeft + index * xStep : padLeft + chartWidth / 2;
    const y = padTop + chartHeight - (point.y / maxY) * chartHeight;
    return { ...point, xPos: x, yPos: y };
  });

  const polyline = svgPoints.map((point) => `${point.xPos},${point.yPos}`).join(" ");

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} className="chart-svg" role="img" aria-label="Query result chart">
        <line x1={padLeft} y1={padTop + chartHeight} x2={width - padRight} y2={padTop + chartHeight} className="chart-axis" />
        <line x1={padLeft} y1={padTop} x2={padLeft} y2={padTop + chartHeight} className="chart-axis" />

        {chartType === "line" ? (
          <>
            <polyline points={polyline} className="chart-line" />
            {svgPoints.map((point) => (
              <circle key={`${point.x}-${point.y}`} cx={point.xPos} cy={point.yPos} r="3.5" className="chart-dot" />
            ))}
          </>
        ) : (
          svgPoints.map((point) => {
            const barWidth = Math.max(chartWidth / Math.max(points.length * 1.8, 4), 10);
            const x = point.xPos - barWidth / 2;
            const barHeight = padTop + chartHeight - point.yPos;
            return <rect key={`${point.x}-${point.y}`} x={x} y={point.yPos} width={barWidth} height={barHeight} className="chart-bar" rx="4" />;
          })
        )}

        {svgPoints.map((point) => (
          <text key={`label-${point.x}`} x={point.xPos} y={height - 10} textAnchor="middle" className="chart-label">
            {point.x}
          </text>
        ))}
      </svg>
    </div>
  );
}

function ResultsContent({ queryResult }) {
  const type = queryResult?.response_type || "table_records";
  const results = queryResult?.results;
  const downloadableFileName = "query-results.csv";

  if (type === "table_records" && Array.isArray(results)) {
    const columns = buildTableColumns(results);
    if (columns.length === 0) {
      return <p className="muted">No table rows returned.</p>;
    }

    return (
      <div className="data-table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {results.map((row, index) => (
              <tr key={`row-${index}`}>
                {columns.map((column) => (
                  <td key={`${index}-${column}`}>{formatCellValue(row?.[column])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }

  if (type === "graph_json" && results && typeof results === "object") {
    return <GraphView payload={results} />;
  }

  if (type === "csv" && typeof results === "string") {
    const previewLines = results.split("\n").filter(Boolean).slice(0, 11).join("\n");
    const handleDownload = () => {
      const blob = new Blob([results], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.setAttribute("download", downloadableFileName);
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    };
    return (
      <div className="csv-result">
        <p className="muted">Large result set exported as CSV.</p>
        <button type="button" className="secondary" onClick={handleDownload}>
          Download CSV
        </button>
        <pre>{previewLines}</pre>
      </div>
    );
  }

  if (typeof results === "string") {
    return <p>{results}</p>;
  }

  return <pre>{JSON.stringify(results, null, 2)}</pre>;
}

function LoadingProgress({ progress }) {
  if (!progress) return null;
  const elapsed = typeof progress.elapsed === "number" ? progress.elapsed : 0;
  return (
    <div className="loading-progress" role="status" aria-live="polite">
      <span className="loading-progress__dot" aria-hidden="true" />
      <span className="loading-progress__text">{progress.message || "Running…"}</span>
      <span className="loading-progress__elapsed">{elapsed.toFixed(1)}s</span>
    </div>
  );
}

export default function ChatView({
  question,
  setQuestion,
  queryResult,
  queryError,
  loadingQuery,
  queryProgress,
  resultRowCount,
  exampleQuestions,
  onSubmit
}) {
  const graphPointCount =
    queryResult?.response_type === "graph_json" && queryResult?.results && typeof queryResult.results === "object"
      ? extractGraphPoints(queryResult.results).length
      : 0;
  const rowCount = resultRowCount || graphPointCount;

  return (
    <section className="panel">
      <div className="panel__grid">
        <form className="query" onSubmit={onSubmit}>
          <label className="field">
            <span>Ask a question</span>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="How many alarms were handled last week?"
              rows={4}
            />
          </label>
          <div className="query__actions">
            <button className="primary" disabled={loadingQuery || !question.trim()}>
              {loadingQuery ? "Running..." : "Run query"}
            </button>
            <span className="helper">Responses are scoped to the company and returned with SQL.</span>
          </div>
          {loadingQuery && <LoadingProgress progress={queryProgress} />}
          {queryError && <p className="error">{queryError}</p>}
        </form>
        <aside className="insight">
          <h3>Quick prompts</h3>
          <p className="muted">Tap a suggestion to preload a question and hit run.</p>
          <div className="chips">
            {exampleQuestions.map((item) => (
              <button key={item} type="button" className="chip" onClick={() => setQuestion(item)}>
                {item}
              </button>
            ))}
          </div>
          <div className="insight__card">
            <span className="insight__label">Last run</span>
            <strong>{queryResult ? "Just now" : "No runs yet"}</strong>
            <p className="muted">Execution time {queryResult ? `${queryResult.execution_time.toFixed(2)}s` : "--"}</p>
          </div>
        </aside>
      </div>

      {queryResult && (
        <div className="results">
          <div className="result-card">
            <div className="result-header">
              <div>
                <h3>SQL</h3>
                <p className="muted">Validated and scoped to company</p>
              </div>
              <span className="pill">Rows: {rowCount}</span>
            </div>
            <pre>{queryResult.sql}</pre>
          </div>
          <div className="result-card">
            <div className="result-header">
              <div>
                <h3>Results</h3>
                <p className="muted">
                  {queryResult.success ? "Query succeeded" : "Query failed"} · {queryResult.response_type || "table_records"}
                </p>
              </div>
              <span className="pill pill--accent">{queryResult.execution_time.toFixed(2)}s</span>
            </div>
            {queryResult.summary && <p className="muted">{queryResult.summary}</p>}
            <ResultsContent queryResult={queryResult} />
            <details>
              <summary>Raw payload</summary>
              <pre>{JSON.stringify(queryResult.results, null, 2)}</pre>
            </details>
          </div>
        </div>
      )}
    </section>
  );
}
