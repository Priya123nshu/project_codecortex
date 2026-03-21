export function getAvatarApiBaseUrl(): string {
  const value = process.env.AVATAR_API_BASE_URL?.trim();
  if (!value) {
    throw new Error("AVATAR_API_BASE_URL is not configured.");
  }
  return value.replace(/\/$/, "");
}

export function buildAvatarApiUrl(pathname: string): string {
  const baseUrl = getAvatarApiBaseUrl();
  return `${baseUrl}${pathname.startsWith("/") ? pathname : `/${pathname}`}`;
}

export function toProxyOutputUrl(value: string): string {
  if (!value) {
    return value;
  }

  if (value.startsWith("http://") || value.startsWith("https://")) {
    const url = new URL(value);
    value = `${url.pathname}${url.search}`;
  }

  const normalized = value.replace(/^\/outputs\//, "").replace(/^\//, "");
  return `/api/avatar/output/${normalized}`;
}

export function rewriteJobPayload<T extends Record<string, unknown>>(payload: T): T {
  const nextPayload = { ...payload } as T & {
    chunk_video_urls?: string[];
    stream_info_url?: string | null;
    output_url_prefix?: string | null;
  };

  if (Array.isArray(nextPayload.chunk_video_urls)) {
    nextPayload.chunk_video_urls = nextPayload.chunk_video_urls.map(toProxyOutputUrl);
  }

  if (typeof nextPayload.stream_info_url === "string") {
    nextPayload.stream_info_url = toProxyOutputUrl(nextPayload.stream_info_url);
  }

  if (typeof nextPayload.output_url_prefix === "string") {
    nextPayload.output_url_prefix = toProxyOutputUrl(nextPayload.output_url_prefix);
  }

  return nextPayload;
}

export async function readJsonResponse<T>(
  response: Response
): Promise<T | { detail?: string }> {
  const contentType = response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return (await response.json()) as T | { detail?: string };
  }

  const detail = await response.text();
  return { detail };
}
