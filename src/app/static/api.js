// JSON calls to the app's API. A failed call throws an Error carrying the server's message.
async function request(path, options = {}) {
  const response = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  let body = null;
  try {
    body = await response.json();
  } catch {
    // empty or not JSON
  }
  if (!response.ok) {
    const error = new Error(body?.error || `Request failed (${response.status})`);
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}

export const get = (path) => request(path);
export const post = (path, data) => request(path, { method: "POST", body: JSON.stringify(data) });
