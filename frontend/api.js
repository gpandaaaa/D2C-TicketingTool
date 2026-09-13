export const state = { user: null, csrf: "", config: null };
export async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    "X-CSRF-Token": state.csrf,
    ...options.headers,
  };
  let response;
  try {
    response = await fetch("/api/v1" + path, {
      ...options,
      headers,
      credentials: "same-origin",
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
  } catch {
    throw new Error(
      "Cannot reach Service Desk. Check your connection and try again.",
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (
      response.status === 401 &&
      !path.includes("/auth/login") &&
      !path.includes("/auth/me")
    )
      window.dispatchEvent(new Event("session-expired"));
    throw new Error(
      data.error?.message || `Request failed (${response.status})`,
    );
  }
  return data;
}
export const send = (path, body, method = "POST") =>
  api(path, { method, body });
export function upload(ticketId, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/tickets/${ticketId}/attachments`);
    xhr.setRequestHeader("X-CSRF-Token", state.csrf);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable)
        onProgress(Math.round((e.loaded / e.total) * 100));
    };
    xhr.onload = () => {
      let data;
      try {
        data = JSON.parse(xhr.responseText);
      } catch {
        data = {};
      }
      xhr.status < 300
        ? resolve(data)
        : reject(new Error(data.error?.message || "Upload failed"));
    };
    xhr.onerror = () => reject(new Error("Upload interrupted. Please retry."));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
