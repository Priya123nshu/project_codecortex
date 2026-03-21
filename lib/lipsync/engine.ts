import {
  defaultLipSyncConfig,
  idleLipSyncFrame,
  type AudioSourceAdapter,
  type LipSyncConfig,
  type LipSyncFrame,
  type MouthState
} from "./types";

type Listener = (frame: LipSyncFrame) => void;

export class LipSyncEngine {
  private ctx: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private adapter: AudioSourceAdapter | null = null;
  private rafId: number | null = null;
  private timeDomain: Uint8Array<ArrayBuffer> | null = null;
  private frequencyDomain: Uint8Array<ArrayBuffer> | null = null;
  private listeners = new Set<Listener>();
  private config: LipSyncConfig = defaultLipSyncConfig;
  private frame: LipSyncFrame = idleLipSyncFrame;
  private smoothedEnergy = 0;
  private currentMouth: MouthState = "closed";
  private lastTick = 0;
  private mouthChangedAt = 0;
  private silenceSince = 0;

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    listener(this.frame);

    return () => {
      this.listeners.delete(listener);
    };
  }

  updateConfig(config: LipSyncConfig): void {
    this.config = config;
  }

  async start(adapter: AudioSourceAdapter, config: LipSyncConfig = this.config): Promise<void> {
    this.config = config;
    this.ctx ??= new AudioContext();

    if (this.ctx.state === "suspended") {
      await this.ctx.resume();
    }

    if (this.adapter && this.adapter !== adapter) {
      this.adapter.disconnect();
    }

    this.adapter = adapter;
    this.analyser = adapter.connect(this.ctx);
    this.timeDomain = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
    this.frequencyDomain = new Uint8Array(new ArrayBuffer(this.analyser.frequencyBinCount));
    this.lastTick = performance.now();
    this.silenceSince = this.lastTick;

    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
    }

    this.tick();
  }

  async stop(): Promise<void> {
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }

    this.adapter?.disconnect();
    this.analyser = null;
    this.adapter = null;
    this.smoothedEnergy = 0;
    this.currentMouth = "closed";
    this.frame = idleLipSyncFrame;
    this.broadcast(this.frame);

    if (this.ctx && this.ctx.state === "running") {
      await this.ctx.suspend();
    }
  }

  private tick = (): void => {
    if (!this.analyser || !this.timeDomain || !this.frequencyDomain) {
      return;
    }

    const now = performance.now();
    const deltaMs = Math.max(now - this.lastTick, 16);
    this.lastTick = now;

    this.analyser.getByteTimeDomainData(this.timeDomain);
    this.analyser.getByteFrequencyData(this.frequencyDomain);

    const rms = computeRms(this.timeDomain);
    const rawEnergy = clamp01(rms * 4.8);
    this.smoothedEnergy = smoothEnergy(
      this.smoothedEnergy,
      rawEnergy,
      deltaMs,
      this.config.attackMs,
      this.config.releaseMs
    );

    const spectralShape = getSpectralShape(
      this.frequencyDomain,
      this.ctx?.sampleRate ?? 48000,
      this.analyser.fftSize
    );
    const isAboveThreshold = this.smoothedEnergy >= this.config.silenceThreshold;

    if (isAboveThreshold) {
      this.silenceSince = 0;
    } else if (!this.silenceSince) {
      this.silenceSince = now;
    }

    const speaking =
      isAboveThreshold ||
      (this.silenceSince !== 0 && now - this.silenceSince < this.config.closeDelayMs);

    const nextMouth = speaking
      ? chooseMouth(this.smoothedEnergy, spectralShape.roundness, this.config.silenceThreshold)
      : "closed";

    if (
      nextMouth !== this.currentMouth &&
      (nextMouth === "closed" || now - this.mouthChangedAt >= this.config.holdMs)
    ) {
      this.currentMouth = nextMouth;
      this.mouthChangedAt = now;
    }

    this.frame = {
      mouth: speaking ? this.currentMouth : "closed",
      energy: this.smoothedEnergy,
      speaking
    };

    this.broadcast(this.frame);
    this.rafId = requestAnimationFrame(this.tick);
  };

  private broadcast(frame: LipSyncFrame): void {
    for (const listener of this.listeners) {
      listener(frame);
    }
  }
}

function computeRms(timeDomain: ArrayLike<number>): number {
  let sum = 0;

  for (let index = 0; index < timeDomain.length; index += 1) {
    const normalized = (timeDomain[index] - 128) / 128;
    sum += normalized * normalized;
  }

  return Math.sqrt(sum / timeDomain.length);
}

function getSpectralShape(
  frequencyDomain: ArrayLike<number>,
  sampleRate: number,
  fftSize: number
): { roundness: number } {
  const binWidth = sampleRate / fftSize;
  const low = averageRange(frequencyDomain, binWidth, 250, 900);
  const mid = averageRange(frequencyDomain, binWidth, 1200, 2600);
  const roundness = low / Math.max(mid, 0.001);

  return { roundness };
}

function averageRange(
  data: ArrayLike<number>,
  binWidth: number,
  minHz: number,
  maxHz: number
): number {
  const start = Math.max(0, Math.floor(minHz / binWidth));
  const end = Math.min(data.length - 1, Math.ceil(maxHz / binWidth));

  if (end < start) {
    return 0;
  }

  let sum = 0;
  let count = 0;

  for (let index = start; index <= end; index += 1) {
    sum += data[index] / 255;
    count += 1;
  }

  return count ? sum / count : 0;
}

function smoothEnergy(
  current: number,
  next: number,
  deltaMs: number,
  attackMs: number,
  releaseMs: number
): number {
  const timeConstant = next > current ? Math.max(attackMs, 1) : Math.max(releaseMs, 1);
  const alpha = 1 - Math.exp(-deltaMs / timeConstant);

  return current + (next - current) * alpha;
}

function chooseMouth(
  energy: number,
  roundness: number,
  silenceThreshold: number
): MouthState {
  if (energy < silenceThreshold) {
    return "closed";
  }

  if (energy > silenceThreshold + 0.05 && roundness > 1.22) {
    return "round";
  }

  if (energy < silenceThreshold + 0.05) {
    return "small";
  }

  if (energy < silenceThreshold + 0.17) {
    return "medium";
  }

  return "wide";
}

function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value));
}
