import { NextResponse } from "next/server";

import { buildAvatarApiUrl, readJsonResponse, rewriteJobPayload } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  context: { params: Promise<{ jobId: string }> }
) {
  try {
    const { jobId } = await context.params;
    const upstreamResponse = await fetch(buildAvatarApiUrl(`/jobs/${jobId}`), {
      cache: "no-store"
    });
    const payload = await readJsonResponse<Record<string, unknown>>(upstreamResponse);
    const body = upstreamResponse.ok ? rewriteJobPayload(payload) : payload;

    return NextResponse.json(body, { status: upstreamResponse.status });
  } catch (cause) {
    return NextResponse.json(
      {
        detail:
          cause instanceof Error ? cause.message : "Unable to fetch the avatar job status."
      },
      { status: 500 }
    );
  }
}
