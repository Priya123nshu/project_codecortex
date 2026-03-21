export type MouthState = "closed" | "small" | "medium" | "wide" | "round";

export type LipSyncFrame = {
  mouth: MouthState;
  energy: number;
  speaking: boolean;
};

export type LipSyncConfig = {
  silenceThreshold: number;
  attackMs: number;
  releaseMs: number;
  holdMs: number;
  closeDelayMs: number;
};

export interface AudioSourceAdapter {
  connect(ctx: AudioContext): AnalyserNode;
  disconnect(): void;
}

export const defaultLipSyncConfig: LipSyncConfig = {
  silenceThreshold: 0.085,
  attackMs: 40,
  releaseMs: 180,
  holdMs: 78,
  closeDelayMs: 145
};

export const idleLipSyncFrame: LipSyncFrame = {
  mouth: "closed",
  energy: 0,
  speaking: false
};
