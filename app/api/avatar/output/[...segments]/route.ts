import { buildAvatarApiUrl } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const PASS_THROUGH_HEADERS = [
  "content-type",
  "content-length",
  "cache-control",
  "accept-ranges",
  "content-range",
  "etag",
  "last-modified"
];

export async function GET(
  request: Request,
  context: { params: Promise<{ segments: string[] }> }
) {
  try {
    const { segments } = await context.params;
    const upstreamHeaders = new Headers();
    const rangeHeader = request.headers.get("range");

    if (rangeHeader) {
      upstreamHeaders.set("range", rangeHeader);
    }

    const upstreamResponse = await fetch(buildAvatarApiUrl(`/outputs/${segments.join("/")}`), {
      cache: "no-store",
      headers: upstreamHeaders
    });

    const headers = new Headers();
    for (const headerName of PASS_THROUGH_HEADERS) {
      const headerValue = upstreamResponse.headers.get(headerName);
      if (headerValue) {
        headers.set(headerName, headerValue);
      }
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers
    });
  } catch {
    return new Response("Unable to load output file.", { status: 500 });
  }
}
