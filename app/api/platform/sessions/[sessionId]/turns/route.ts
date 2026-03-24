import { NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

function platformBaseUrl(): string {
  const baseUrl = process.env.NEXT_PUBLIC_PLATFORM_API_BASE_URL?.trim();
  if (!baseUrl) {
    throw new Error("NEXT_PUBLIC_PLATFORM_API_BASE_URL is not configured.");
  }
  return baseUrl.replace(/\/$/, "");
}

export async function POST(request: Request, { params }: { params: Promise<{ sessionId: string }> }) {
  try {
    const authorization = request.headers.get("authorization");
    if (!authorization) {
      return NextResponse.json({ detail: "Missing Authorization header." }, { status: 401 });
    }

    const { sessionId } = await params;
    const formData = await request.formData();
    const upstreamResponse = await fetch(`${platformBaseUrl()}/sessions/${sessionId}/turns`, {
      method: "POST",
      headers: {
        Authorization: authorization,
        "ngrok-skip-browser-warning": "1",
      },
      body: formData,
      cache: "no-store",
    });

    if (!upstreamResponse.ok || !upstreamResponse.body) {
      const contentType = upstreamResponse.headers.get("content-type") ?? "";
      if (contentType.includes("application/json")) {
        const payload = await upstreamResponse.json();
        return NextResponse.json(payload, { status: upstreamResponse.status });
      }
      const detail = await upstreamResponse.text();
      return NextResponse.json({ detail: detail || "Unable to submit the turn." }, { status: upstreamResponse.status });
    }

    const responseHeaders = new Headers();
    responseHeaders.set("content-type", upstreamResponse.headers.get("content-type") ?? "text/event-stream");
    responseHeaders.set("cache-control", "no-cache, no-transform");
    responseHeaders.set("x-accel-buffering", "no");

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: responseHeaders,
    });
  } catch (error) {
    const message = error instanceof Error && error.message ? error.message : "Unable to proxy the streamed turn request.";
    return NextResponse.json({ detail: message }, { status: 500 });
  }
}
