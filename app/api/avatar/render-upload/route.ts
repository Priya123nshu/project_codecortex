import { NextResponse } from "next/server";

import { buildAvatarApiUrl, readJsonResponse, rewriteJobPayload } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function POST(request: Request) {
  try {
    const formData = await request.formData();
    const upstreamResponse = await fetch(buildAvatarApiUrl("/jobs/render-upload"), {
      method: "POST",
      body: formData,
      cache: "no-store"
    });

    const payload = await readJsonResponse<Record<string, unknown>>(upstreamResponse);
    const body = upstreamResponse.ok ? rewriteJobPayload(payload) : payload;

    return NextResponse.json(body, { status: upstreamResponse.status });
  } catch (cause) {
    return NextResponse.json(
      {
        detail:
          cause instanceof Error ? cause.message : "Unable to contact the avatar API backend."
      },
      { status: 500 }
    );
  }
}
