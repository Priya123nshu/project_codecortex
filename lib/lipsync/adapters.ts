import type { AudioSourceAdapter } from "./types";

export class ElementAudioSourceAdapter implements AudioSourceAdapter {
  private readonly element: HTMLMediaElement;
  private sourceNode: MediaElementAudioSourceNode | null = null;
  private outputNode: GainNode | null = null;
  private analyser: AnalyserNode | null = null;

  constructor(element: HTMLMediaElement) {
    this.element = element;
  }

  connect(ctx: AudioContext): AnalyserNode {
    if (!this.sourceNode) {
      this.sourceNode = ctx.createMediaElementSource(this.element);
    }

    this.outputNode ??= ctx.createGain();
    this.outputNode.gain.value = 1;
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.06;

    this.disconnectGraph();
    this.sourceNode.connect(this.outputNode);
    this.outputNode.connect(this.analyser);
    this.outputNode.connect(ctx.destination);

    return this.analyser;
  }

  disconnect(): void {
    this.disconnectGraph();
    this.analyser = null;
  }

  private disconnectGraph(): void {
    this.sourceNode?.disconnect();
    this.outputNode?.disconnect();
    this.analyser?.disconnect();
  }
}

export class MediaStreamAudioSourceAdapter implements AudioSourceAdapter {
  private readonly stream: MediaStream;
  private sourceNode: MediaStreamAudioSourceNode | null = null;
  private analyser: AnalyserNode | null = null;

  constructor(stream: MediaStream) {
    this.stream = stream;
  }

  connect(ctx: AudioContext): AnalyserNode {
    this.disconnect();
    this.sourceNode = ctx.createMediaStreamSource(this.stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.06;
    this.sourceNode.connect(this.analyser);

    return this.analyser;
  }

  disconnect(): void {
    this.sourceNode?.disconnect();
    this.analyser?.disconnect();
    this.sourceNode = null;
    this.analyser = null;
  }
}
