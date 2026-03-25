import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const PASSTHROUGH_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-length",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
] as const;

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const rawUrl = searchParams.get("url")?.trim();
    if (!rawUrl) {
      return NextResponse.json({ detail: "Chunk url is required." }, { status: 400 });
    }

    let target: URL;
    try {
      target = new URL(rawUrl);
    } catch {
      return NextResponse.json({ detail: "Chunk url must be an absolute URL." }, { status: 400 });
    }

    if (!["http:", "https:"].includes(target.protocol)) {
      return NextResponse.json({ detail: "Unsupported chunk url protocol." }, { status: 400 });
    }

    const upstreamHeaders = new Headers();
    upstreamHeaders.set("ngrok-skip-browser-warning", "1");

    const range = request.headers.get("range");
    if (range) {
      upstreamHeaders.set("range", range);
    }

    const ifRange = request.headers.get("if-range");
    if (ifRange) {
      upstreamHeaders.set("if-range", ifRange);
    }

    const upstreamResponse = await fetch(target.toString(), {
      method: "GET",
      headers: upstreamHeaders,
      cache: "no-store",
    });

    if (!upstreamResponse.ok && upstreamResponse.status !== 206) {
      const contentType = upstreamResponse.headers.get("content-type") ?? "";
      if (contentType.includes("application/json")) {
        const payload = await upstreamResponse.json();
        return NextResponse.json(payload, { status: upstreamResponse.status });
      }
      const detail = await upstreamResponse.text();
      return NextResponse.json({ detail: detail || "Unable to load the rendered chunk." }, { status: upstreamResponse.status });
    }

    const headers = new Headers();
    for (const name of PASSTHROUGH_HEADERS) {
      const value = upstreamResponse.headers.get(name);
      if (value) {
        headers.set(name, value);
      }
    }
    if (!headers.has("cache-control")) {
      headers.set("cache-control", "no-store");
    }

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers,
    });
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : "Unable to proxy the rendered chunk.";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
