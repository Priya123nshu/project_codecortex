import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "Multilingual Avatar Platform",
  description:
    "Login-only pilot for multilingual avatar conversations with retrieval grounding, Azure OpenAI generation, TTS, and streamed MuseTalk replies.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
