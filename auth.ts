import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";
import Google from "next-auth/providers/google";
import MicrosoftEntraID from "next-auth/providers/microsoft-entra-id";

export type AuthProviderDescriptor = {
  id: string;
  label: string;
  enabled: boolean;
};

const googleEnabled = Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
const microsoftEnabled = Boolean(
  process.env.MICROSOFT_CLIENT_ID && process.env.MICROSOFT_CLIENT_SECRET && process.env.MICROSOFT_TENANT_ID
);
const devCredentialsEnabled = process.env.NODE_ENV !== "production" || (!googleEnabled && !microsoftEnabled);

export const platformAuthProviders: AuthProviderDescriptor[] = [
  { id: "google", label: "Google", enabled: googleEnabled },
  { id: "microsoft-entra-id", label: "Microsoft", enabled: microsoftEnabled },
  { id: "credentials", label: "Development access", enabled: devCredentialsEnabled },
];

const providers: any[] = [];

if (googleEnabled) {
  providers.push(
    Google({
      clientId: process.env.GOOGLE_CLIENT_ID as string,
      clientSecret: process.env.GOOGLE_CLIENT_SECRET as string,
    })
  );
}

if (microsoftEnabled) {
  providers.push(
    MicrosoftEntraID({
      clientId: process.env.MICROSOFT_CLIENT_ID as string,
      clientSecret: process.env.MICROSOFT_CLIENT_SECRET as string,
      issuer: `https://login.microsoftonline.com/${process.env.MICROSOFT_TENANT_ID}/v2.0`,
    })
  );
}

if (devCredentialsEnabled) {
  providers.push(
    Credentials({
      id: "credentials",
      name: "Development access",
      credentials: {
        email: { label: "Email", type: "email" },
        name: { label: "Name", type: "text" },
      },
      authorize(credentials) {
        const email = String(credentials?.email || "demo-admin@example.com").trim();
        const name = String(credentials?.name || "Demo Admin").trim();
        if (!email) {
          return null;
        }
        return {
          id: email,
          email,
          name,
        };
      },
    })
  );
}

export const { handlers, signIn, signOut, auth } = NextAuth({
  session: {
    strategy: "jwt",
  },
  providers,
  pages: {
    signIn: "/",
  },
  callbacks: {
    async jwt({ token, user }) {
      if (user?.email) {
        token.email = user.email;
      }
      if (user?.name) {
        token.name = user.name;
      }
      if (typeof user?.id === "string") {
        token.sub = user.id;
      }
      return token;
    },
    async session({ session, token }) {
      if (session.user) {
        if (typeof token.email === "string") {
          session.user.email = token.email;
        }
        if (typeof token.name === "string") {
          session.user.name = token.name;
        }
      }
      return session;
    },
  },
});

