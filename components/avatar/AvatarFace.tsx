"use client";

import { useId } from "react";
import type { CSSProperties } from "react";
import type { MouthState } from "@/lib/lipsync/types";

type AvatarTheme = {
  backgroundStart?: string;
  backgroundEnd?: string;
  skin?: string;
  blush?: string;
  hair?: string;
  eye?: string;
  mouth?: string;
  accent?: string;
};

type AvatarFaceProps = {
  mouth: MouthState;
  speaking: boolean;
  size?: number;
  theme?: AvatarTheme;
};

const defaultTheme: Required<AvatarTheme> = {
  backgroundStart: "#0d2032",
  backgroundEnd: "#152f4c",
  skin: "#f2cdb7",
  blush: "#f5ad9b",
  hair: "#101a31",
  eye: "#111c2e",
  mouth: "#59263b",
  accent: "#5de4c7"
};

export function AvatarFace({
  mouth,
  speaking,
  size = 420,
  theme
}: AvatarFaceProps) {
  const palette = { ...defaultTheme, ...theme };
  const gradientId = useId();
  const maskId = useId();
  const inlineStyle = {
    "--avatar-accent": palette.accent
  } as CSSProperties;

  return (
    <div
      style={{
        ...inlineStyle,
        width: size,
        maxWidth: "100%"
      }}
    >
      <svg
        viewBox="0 0 420 420"
        role="img"
        aria-label="Stylized avatar face with live lip-sync"
        style={{ display: "block", width: "100%", height: "auto" }}
      >
        <defs>
          <linearGradient id={gradientId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={palette.backgroundStart} />
            <stop offset="100%" stopColor={palette.backgroundEnd} />
          </linearGradient>
          <clipPath id={maskId}>
            <circle cx="210" cy="210" r="178" />
          </clipPath>
        </defs>

        <g style={{ animation: "avatarFloat 4.8s ease-in-out infinite" }}>
          <circle cx="210" cy="210" r="188" fill={`url(#${gradientId})`} />
          <circle cx="148" cy="132" r="54" fill="rgba(93, 228, 199, 0.18)" />
          <circle cx="296" cy="118" r="38" fill="rgba(255, 197, 111, 0.15)" />

          <g clipPath={`url(#${maskId})`}>
            <path d="M80 194c16-102 246-130 278 18l-6 112H94Z" fill={palette.hair} />
            <ellipse cx="210" cy="236" rx="116" ry="132" fill={palette.skin} />
            <ellipse cx="147" cy="244" rx="22" ry="14" fill={palette.blush} opacity="0.46" />
            <ellipse cx="276" cy="244" rx="22" ry="14" fill={palette.blush} opacity="0.42" />

            <g style={{ animation: "avatarBlink 7s ease-in-out infinite" }}>
              <ellipse cx="162" cy="210" rx="24" ry="18" fill="white" />
              <ellipse cx="257" cy="210" rx="24" ry="18" fill="white" />
              <circle cx="166" cy="212" r="9" fill={palette.eye} />
              <circle cx="261" cy="212" r="9" fill={palette.eye} />
              <circle cx="170" cy="208" r="3.2" fill="white" opacity="0.9" />
              <circle cx="265" cy="208" r="3.2" fill="white" opacity="0.9" />
            </g>

            <path
              d="M133 178c12-18 40-26 63-16"
              stroke={palette.hair}
              strokeWidth="10"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M228 162c26-13 54-7 66 11"
              stroke={palette.hair}
              strokeWidth="10"
              strokeLinecap="round"
              fill="none"
            />
            <path
              d="M177 286c20 16 46 16 66 0"
              stroke="rgba(118, 72, 92, 0.28)"
              strokeWidth="7"
              strokeLinecap="round"
              fill="none"
            />

            <g transform="translate(210 302)">
              <ellipse
                cx="0"
                cy={speaking ? 3 : 0}
                rx={84}
                ry={26}
                fill="rgba(255,255,255,0.04)"
                opacity={speaking ? 0.4 : 0.2}
              />
              {renderMouth(mouth, palette.mouth)}
            </g>
          </g>

          <circle
            cx="210"
            cy="210"
            r="188"
            fill="none"
            stroke="rgba(255,255,255,0.08)"
            strokeWidth="2"
          />
        </g>
      </svg>
      <style jsx>{`
        @keyframes avatarFloat {
          0%,
          100% {
            transform: translateY(0px);
          }
          50% {
            transform: translateY(-6px);
          }
        }

        @keyframes avatarBlink {
          0%,
          44%,
          46%,
          100% {
            transform: scaleY(1);
            transform-origin: center;
          }
          45% {
            transform: scaleY(0.12);
            transform-origin: center;
          }
        }
      `}</style>
    </div>
  );
}

function renderMouth(mouth: MouthState, color: string) {
  switch (mouth) {
    case "small":
      return <ellipse cx="0" cy="0" rx="16" ry="10" fill={color} />;
    case "medium":
      return <ellipse cx="0" cy="4" rx="20" ry="18" fill={color} />;
    case "wide":
      return (
        <>
          <ellipse cx="0" cy="8" rx="28" ry="30" fill={color} />
          <ellipse cx="0" cy="-3" rx="18" ry="7" fill="rgba(255, 212, 126, 0.24)" />
        </>
      );
    case "round":
      return (
        <>
          <ellipse cx="0" cy="8" rx="18" ry="26" fill={color} />
          <ellipse cx="0" cy="8" rx="7" ry="13" fill="rgba(18, 11, 19, 0.16)" />
        </>
      );
    case "closed":
    default:
      return (
        <path
          d="M-28 2c18 10 38 10 56 0"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          fill="none"
        />
      );
  }
}
