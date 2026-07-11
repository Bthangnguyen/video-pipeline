export async function api(url, options = {}) {
  const hasFormData = Boolean(options.formData);
  const response = await fetch(url, {
    method: options.method || "GET",
    headers: !hasFormData && options.body ? { "Content-Type": "application/json" } : undefined,
    body: hasFormData ? options.formData : (options.body ? JSON.stringify(options.body) : undefined),
  });
  const data = await response.json();
  if (!data.success) {
    throw new Error(`${data.error.code}: ${data.error.message}`);
  }
  return data;
}
