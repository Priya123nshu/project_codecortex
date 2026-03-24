import { SignJWT } from "jose";

export type PlatformAccessTokenInput = {
  subject: string;
  email: string;
  name: string;
  role: "admin" | "user";
  orgId: string;
};

function getSecret(): Uint8Array {
  const secret = process.env.PLATFORM_API_JWT_SECRET || process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
  if (!secret) {
    throw new Error("PLATFORM_API_JWT_SECRET, AUTH_SECRET, or NEXTAUTH_SECRET must be configured.");
  }
  return new TextEncoder().encode(secret);
}

export function roleForEmail(email: string): "admin" | "user" {
  const raw = process.env.PLATFORM_ADMIN_EMAILS ?? "";
  const admins = raw
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean);
  return admins.includes(email.toLowerCase()) ? "admin" : "user";
}

export async function issuePlatformAccessToken(input: PlatformAccessTokenInput): Promise<string> {
  return await new SignJWT({
    email: input.email,
    name: input.name,
    role: input.role,
    org_id: input.orgId,
  })
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(input.subject)
    .setIssuedAt()
    .setExpirationTime("2h")
    .sign(getSecret());
}

