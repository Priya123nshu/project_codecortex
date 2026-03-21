import { NextResponse } from "next/server";

import { buildAvatarApiUrl, readJsonResponse } from "@/lib/avatar-api";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const upstreamResponse = await fetch(buildAvatarApiUrl("/health"), {
      cache: "no-store"
    });
    const payload = await readJsonResponse<{ status: string }>(upstreamResponse);
    return NextResponse.json(payload, { status: upstreamResponse.status });
  } catch (cause) {
    return NextResponse.json(
      {
        detail:
          cause instanceof Error ? cause.message : "Unable to contact the avatar API health endpoint."
      },
      { status: 500 }
    );
  }
}
