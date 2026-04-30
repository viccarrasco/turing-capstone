const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";
const API_KEY = import.meta.env.VITE_API_KEY || "change_me";

function withQuery(path, params = {}) {
  const search = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") {
      search.set(key, String(value));
    }
  });
  const query = search.toString();
  return query ? `${path}?${query}` : path;
}

async function parseError(res) {
  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    try {
      const payload = await res.json();
      if (typeof payload?.detail === "string" && payload.detail.trim()) {
        return payload.detail;
      }
      return JSON.stringify(payload);
    } catch (_) {
      return `Request failed: ${res.status}`;
    }
  }

  const text = await res.text();
  return text || `Request failed: ${res.status}`;
}

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      ...(options.headers || {})
    }
  });

  if (!res.ok) {
    throw new Error(await parseError(res));
  }
  return res.json();
}

// DEPRECATED: Replaced by queryV1. Kept for reference; remove in a future cleanup.
// export function chatQuery(question, companyId) {
//   return request("/api/chat/query", {
//     method: "POST",
//     body: JSON.stringify({ question, company_id: Number(companyId) })
//   });
// }

function v1EnvelopeToLegacy(envelope, executionSeconds) {
  const meta = envelope?.meta || {};
  const responseType = meta.response_type || "plain_text";
  let results = null;
  if (responseType === "table_records") results = envelope.table_records || [];
  else if (responseType === "graph_json") results = envelope.chart_data || null;
  else if (responseType === "csv") results = envelope.csv_inline || "";
  else results = envelope.answer || "";

  return {
    success: !envelope?.error,
    results,
    sql: meta.generated_sql || "",
    execution_time: executionSeconds,
    response_type: responseType,
    summary: envelope?.answer || ""
  };
}

export async function queryV1(question, companyId, { signal } = {}) {
  const startedAt = performance.now();
  const res = await fetch(`${API_BASE}/api/v1/query`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": API_KEY,
      "X-Company-Id": String(Number(companyId))
    },
    body: JSON.stringify({ question }),
    signal
  });
  if (!res.ok) throw new Error(await parseError(res));
  const envelope = await res.json();
  const elapsedSeconds = (performance.now() - startedAt) / 1000;
  return v1EnvelopeToLegacy(envelope, elapsedSeconds);
}

export function listConversations(companyId) {
  return request(withQuery("/api/conversations", { company_id: companyId }));
}

export function getConversation(id, companyId) {
  return request(withQuery(`/api/conversations/${id}`, { company_id: companyId }));
}

export function createConversation(companyId) {
  return request("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ company_id: Number(companyId) })
  });
}

export function deleteConversation(id, companyId) {
  return request(withQuery(`/api/conversations/${id}`, { company_id: companyId }), {
    method: "DELETE"
  });
}

export function createMessage(conversationId, companyId, content) {
  return request(withQuery(`/api/conversations/${conversationId}/messages`, { company_id: companyId }), {
    method: "POST",
    body: JSON.stringify({ content })
  });
}
