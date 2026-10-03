const API_BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

/**
 * Thin fetch wrapper used for every backend call: attaches
 * `Authorization: Bearer <token>` when a token is supplied, JSON-encodes a
 * plain object body, passes a FormData body through untouched (so the
 * browser sets the multipart boundary itself), and turns any non-2xx
 * response into a thrown ApiError so callers can show a toast.
 */
export async function apiRequest(path, { method = "GET", token, json, formData, headers = {} } = {}) {
  const finalHeaders = { ...headers };
  if (token) finalHeaders["Authorization"] = `Bearer ${token}`;

  let body;
  if (formData) {
    body = formData;
  } else if (json !== undefined) {
    finalHeaders["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { method, headers: finalHeaders, body });

  if (response.status === 204) return null;

  const contentType = response.headers.get("content-type") || "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? await response.json() : await response.blob();

  if (!response.ok) {
    const detail = isJson ? payload.detail ?? payload : "Request failed";
    throw new ApiError(response.status, detail);
  }
  return payload;
}

export { API_BASE_URL };
