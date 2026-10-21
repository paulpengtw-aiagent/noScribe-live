// The voice orb's drawing engine: canvas 2D, no React. activity-orb.tsx owns the component and feeds
// it props. Each frame places every dot on a rotating sphere (surface noise, converting scatter,
// page-load intro, rotation, perspective), gives it an alpha and a radius from its depth, and sorts
// the dots into buckets of (alpha level, colour class). One fill call per bucket keeps a frame to a
// few dozen draw calls. Nothing is allocated per frame.

import { mixColor, parseColor, rgbaCss, rgbCss, sameRgb, type RGB } from "@/lib/color";

export type OrbMode = "idle" | "converting" | "diarizing" | "thinking" | "transcribing" | "finished" | "error";

export interface OrbInput {
  mode: OrbMode;
  /** Loudness samples, 0..1, of the newest segment. Played across one pulse. */
  envelope: readonly number[];
  /** Changes once for each new segment. */
  pulseKey: number;
  /** 0..1, drives the converting mode. */
  progress: number;
  speakerColors: readonly string[];
  activeColor: string | undefined;
  /** Square size in CSS pixels. */
  size: number;
  /** The pre-roll's big orb: dots are drawn larger and brighter (see PROMINENT_RADIUS and PROMINENT_ALPHA). */
  prominent?: boolean;
}

interface ModeSpec {
  /** Surface displacement at rest. Energy adds up to 0.16 more. */
  amp: number;
  /** Rotation in radians per second. */
  spin: number;
  /** Global breathing, as a share of the radius. */
  breath: number;
  breathPeriod: number;
  /** Multiplier on dot alpha. */
  dim: number;
}

const MODES: Record<OrbMode, ModeSpec> = {
  idle: { amp: 0.015, spin: 0.1, breath: 0.012, breathPeriod: 4, dim: 0.78 },
  converting: { amp: 0.01, spin: 0.2, breath: 0, breathPeriod: 4, dim: 0.9 },
  diarizing: { amp: 0.02, spin: 0.12, breath: 0, breathPeriod: 4, dim: 1 },
  thinking: { amp: 0.02, spin: 0.16, breath: 0.012, breathPeriod: 3.2, dim: 0.8 },
  transcribing: { amp: 0.035, spin: 0.18, breath: 0, breathPeriod: 4, dim: 1 },
  finished: { amp: 0.012, spin: 0.09, breath: 0, breathPeriod: 4, dim: 0.92 },
  error: { amp: 0, spin: 0, breath: 0, breathPeriod: 4, dim: 0.55 },
};

const TAU = Math.PI * 2;
const DOTS = 720;
const GOLDEN_ANGLE = Math.PI * (3 - Math.sqrt(5));
/** Sphere radius as a share of the canvas size. The rest is room for the halo and the ring. */
const RADIUS_RATIO = 0.33;
/** Perspective distance in sphere radii. Nearer dots grow a little, farther ones shrink. */
const CAMERA = 4.2;
/** Tilt of the rotation axis, radians. */
const TILT = 0.42;
const ENERGY_TAU = 0.12;
const MODE_TAU = 0.35;
const PROGRESS_TAU = 0.3;
const PULSE_MS = 900;
const RIPPLE_MS = 1100;
const INTRO_S = 1.2;
/** Idle draws only this share of the dots, the rest are left out. */
const SPARSE_KEEP = 0.55;
/** A prominent orb draws its dots this many times larger and this many times brighter. */
const PROMINENT_RADIUS = 1.6;
const PROMINENT_ALPHA = 1.25;

const ALPHA_LEVELS = 20;
/** Colour classes: 0 ink, 1-3 ripple tints, 4-11 speaker colours, 12 the dim grey. */
const CLASSES = 13;
const KEYS = ALPHA_LEVELS * CLASSES;
/** Dots that are not drawn this frame go to a bucket after the last one. */
const SKIP = KEYS;
const CLS_INK = 0;
const CLS_TINT = 1;
const CLS_SPEAKER = 4;
const CLS_DIM = 12;
const MAX_SPEAKERS = 8;
const TINT_WEIGHTS = [0.35, 0.6, 0.85] as const;
/** Ink dots on the dark theme take a Frost gradient across the orb; the light theme gets a deeper Frost run. */
const FROST_DARK = ["#8fbcbb", "#88c0d0", "#5e81ac"] as const;
const FROST_LIGHT = ["#81a1c1", "#5e81ac", "#486488"] as const;
/** Crimson palette: the ink gradient runs coral to gold to blue on the dark theme, red to gold to navy on the light. */
const CRIMSON_FROST_DARK = ["#f08a8f", "#f5e1a4", "#7fb8e6"] as const;
const CRIMSON_FROST_LIGHT = ["#93272c", "#7a5a1e", "#003865"] as const;

const FALLBACK_INK: RGB = { r: 245, g: 245, b: 245 };
const FALLBACK_INK3: RGB = { r: 115, g: 115, b: 115 };
const NO_ENVELOPE: readonly number[] = [];

const clamp01 = (v: number) => (v < 0 ? 0 : v > 1 ? 1 : v);
const clamp = (v: number, lo: number, hi: number) => (v < lo ? lo : v > hi ? hi : v);
const smooth01 = (v: number) => {
  const c = clamp01(v);
  return c * c * (3 - 2 * c);
};

/** Small seeded generator, so the random parts of the lattice are the same on every load. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

interface Lattice {
  /** Unit positions on a Fibonacci lattice. */
  ux: Float32Array;
  uy: Float32Array;
  uz: Float32Array;
  /** Latitude and longitude, for the surface noise and the speaker bands. */
  lat: Float32Array;
  lon: Float32Array;
  /** Converting: where each dot starts, scattered at 1.3 to 1.9 radii. */
  scx: Float32Array;
  scy: Float32Array;
  scz: Float32Array;
  /** Page-load intro: where each dot starts, outside the sphere. */
  icx: Float32Array;
  icy: Float32Array;
  icz: Float32Array;
  /** Progress at which a dot joins the sphere while converting. */
  gather: Float32Array;
  /** Share of the intro window before a dot starts to move. */
  delay: Float32Array;
  /** Fixed per dot. Idle keeps the dots below SPARSE_KEEP. */
  keep: Float32Array;
}

function buildLattice(): Lattice {
  const rand = mulberry32(20261020);
  const lattice: Lattice = {
    ux: new Float32Array(DOTS),
    uy: new Float32Array(DOTS),
    uz: new Float32Array(DOTS),
    lat: new Float32Array(DOTS),
    lon: new Float32Array(DOTS),
    scx: new Float32Array(DOTS),
    scy: new Float32Array(DOTS),
    scz: new Float32Array(DOTS),
    icx: new Float32Array(DOTS),
    icy: new Float32Array(DOTS),
    icz: new Float32Array(DOTS),
    gather: new Float32Array(DOTS),
    delay: new Float32Array(DOTS),
    keep: new Float32Array(DOTS),
  };
  for (let i = 0; i < DOTS; i++) {
    const y = 1 - (2 * i + 1) / DOTS;
    const ring = Math.sqrt(1 - y * y);
    const phi = GOLDEN_ANGLE * i;
    lattice.ux[i] = Math.cos(phi) * ring;
    lattice.uy[i] = y;
    lattice.uz[i] = Math.sin(phi) * ring;
    lattice.lat[i] = Math.asin(y);
    lattice.lon[i] = phi % TAU;

    // A uniform random direction, then a random radius for the scatter and for the intro.
    const zr = 2 * rand() - 1;
    const angle = TAU * rand();
    const rr = Math.sqrt(1 - zr * zr);
    const dx = rr * Math.cos(angle);
    const dy = rr * Math.sin(angle);
    const scatterR = 1.3 + 0.6 * rand();
    const introR = 2.4 + 1.2 * rand();
    lattice.scx[i] = dx * scatterR;
    lattice.scy[i] = dy * scatterR;
    lattice.scz[i] = zr * scatterR;
    lattice.icx[i] = dx * introR;
    lattice.icy[i] = dy * introR;
    lattice.icz[i] = zr * introR;
    lattice.gather[i] = 0.8 * rand();
    lattice.delay[i] = 0.3 * rand();
    lattice.keep[i] = rand();
  }
  return lattice;
}

/** Built once, shared by every orb on the page. */
const LATTICE = buildLattice();

interface Clock {
  /** Seconds of animation. Stays at 0 under reduced motion. */
  t: number;
  /** Timestamp of the last frame, in ms. */
  last: number;
  yaw: number;
  /** Smoothed surface amplitude, spin and dimming for the current mode. */
  amp: number;
  spin: number;
  dim: number;
  /** Pulse energy, 0..1, smoothed. */
  energy: number;
  /** Smoothed progress, 0..1. */
  progress: number;
  /** 0..1 weight of the converting scatter. */
  scatter: number;
  /** 0..1 weight of the finished ring. */
  ring: number;
  /** Clock time the envelope started playing, or -1. */
  pulseAt: number;
  /** Clock time the ripple started, or -1. */
  rippleAt: number;
  pulseEnv: readonly number[];
  seenPulse: number;
}

export class OrbRenderer {
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  /** Reduced motion: one static frame per change, no loop. */
  private readonly still: boolean;
  private readonly clock: Clock;
  private input: OrbInput | null = null;
  private ink: RGB = FALLBACK_INK;
  private ink3: RGB = FALLBACK_INK3;
  /** Fill style per colour class; rebuilt when the ink, the active colour or the speakers change. */
  private styles: Array<string | CanvasGradient> = [];
  /** The Frost gradient for the ink class; rebuilt only when the size or the theme ink changes. */
  private inkFill: CanvasGradient | null = null;
  private inkFillKey = "";
  private stylesKey = "";
  private speakerRgb: RGB[] = [];
  private activeRgb: RGB | null = null;
  /** Soft halo, drawn once per ink colour and scaled when it is used. */
  private sprite: HTMLCanvasElement | null = null;
  private spriteKey = "";
  private laidOut = "";
  private raf = 0;
  private listening = false;

  // Per-dot scratch arrays, reused every frame.
  private readonly px = new Float32Array(DOTS);
  private readonly py = new Float32Array(DOTS);
  private readonly pr = new Float32Array(DOTS);
  private readonly keys = new Uint16Array(DOTS);
  private readonly order = new Uint16Array(DOTS);
  private readonly counts = new Uint32Array(KEYS + 2);
  private readonly cursor = new Uint32Array(KEYS + 2);

  constructor(canvas: HTMLCanvasElement, reduced: boolean) {
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("noScribe Live: the activity orb needs a 2D canvas context");
    this.canvas = canvas;
    this.ctx = ctx;
    this.still = reduced;
    const idle = MODES.idle;
    this.clock = {
      t: 0,
      last: 0,
      yaw: 0.6,
      amp: idle.amp,
      spin: idle.spin,
      dim: idle.dim,
      energy: 0,
      progress: 0,
      scatter: 0,
      ring: 0,
      pulseAt: -1,
      rippleAt: -1,
      pulseEnv: NO_ENVELOPE,
      seenPulse: 0,
    };
  }

  /** The ink (--foreground) and the tertiary grey (--ink-3) of the current theme. */
  setInk(ink: RGB, ink3: RGB): void {
    if (sameRgb(ink, this.ink) && sameRgb(ink3, this.ink3)) return;
    this.ink = ink;
    this.ink3 = ink3;
    this.stylesKey = "";
    this.spriteKey = "";
    this.refresh();
  }

  setInput(input: OrbInput): void {
    const clock = this.clock;
    // A new pulseKey starts the envelope and the ripple. The first value seen is not a pulse.
    if (this.input !== null && input.pulseKey !== clock.seenPulse) {
      clock.pulseAt = clock.t;
      clock.rippleAt = clock.t;
      clock.pulseEnv = input.envelope;
    }
    clock.seenPulse = input.pulseKey;
    this.input = input;
    this.refresh();
  }

  /** Starts the animation loop. Under reduced motion this only draws the static frame. */
  start(): void {
    if (this.still) {
      // No loop under reduced motion. Paint the one static frame if input has already arrived.
      this.renderStill();
      return;
    }
    if (this.listening) return;
    this.listening = true;
    document.addEventListener("visibilitychange", this.onVisibility);
    this.resumeLoop();
  }

  dispose(): void {
    this.listening = false;
    document.removeEventListener("visibilitychange", this.onVisibility);
    cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private refresh(): void {
    this.syncStyles();
    if (this.still) this.renderStill();
  }

  private resumeLoop(): void {
    if (this.raf !== 0 || document.hidden || !this.listening) return;
    this.clock.last = performance.now();
    this.raf = requestAnimationFrame(this.tick);
  }

  private readonly tick = (now: number): void => {
    this.raf = 0;
    if (!this.listening || document.hidden) return;
    this.step(now);
    this.raf = requestAnimationFrame(this.tick);
  };

  private readonly onVisibility = (): void => {
    if (document.hidden) {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    } else {
      this.resumeLoop();
    }
  };

  /** One animation frame: advance the clock and the smoothed values, then paint. */
  private step(now: number): void {
    const c = this.clock;
    const input = this.input;
    const dt = Math.min(0.05, Math.max(0, (now - c.last) / 1000));
    c.last = now;
    if (!input) return;
    c.t += dt;
    const spec = MODES[input.mode];

    // Energy follows the loudness of the newest segment while its pulse plays, then decays to rest.
    let target = 0;
    if (c.pulseAt >= 0) {
      const p = ((c.t - c.pulseAt) * 1000) / PULSE_MS;
      if (p >= 1) {
        c.pulseAt = -1;
      } else {
        const env = c.pulseEnv;
        target = env.length > 0
          ? clamp01(env[Math.min(env.length - 1, Math.floor(p * env.length))])
          : 0.55 * Math.sin(Math.PI * p);
      }
    }
    c.energy += (target - c.energy) * (1 - Math.exp(-dt / ENERGY_TAU));

    const k = 1 - Math.exp(-dt / MODE_TAU);
    c.amp += (spec.amp - c.amp) * k;
    c.spin += (spec.spin - c.spin) * k;
    c.dim += (spec.dim - c.dim) * k;
    c.scatter += ((input.mode === "converting" ? 1 : 0) - c.scatter) * k;
    c.ring += ((input.mode === "finished" ? 1 : 0) - c.ring) * k;
    c.progress += (clamp01(input.progress) - c.progress) * (1 - Math.exp(-dt / PROGRESS_TAU));
    c.yaw += (c.spin + 0.12 * c.energy) * dt;
    this.paint();
  }

  private renderStill(): void {
    const input = this.input;
    if (!input) return;
    const spec = MODES[input.mode];
    const c = this.clock;
    c.t = 0;
    c.yaw = 0.6;
    c.amp = spec.amp;
    c.spin = spec.spin;
    c.dim = spec.dim;
    c.energy = 0;
    c.progress = clamp01(input.progress);
    c.scatter = input.mode === "converting" ? 1 : 0;
    c.ring = input.mode === "finished" ? 1 : 0;
    c.pulseAt = -1;
    c.rippleAt = -1;
    this.paint();
  }

  private syncStyles(): void {
    const input = this.input;
    if (!input) return;
    const { ink, ink3 } = this;
    const key = `${ink.r},${ink.g},${ink.b}|${ink3.r},${ink3.g},${ink3.b}|${input.activeColor ?? ""}|${input.speakerColors.join("|")}`;
    if (key === this.stylesKey) return;
    this.stylesKey = key;
    this.speakerRgb = input.speakerColors.slice(0, MAX_SPEAKERS).map((c) => parseColor(c) ?? ink);
    this.activeRgb = input.activeColor ? parseColor(input.activeColor) : null;

    const styles: Array<string | CanvasGradient> = new Array<string | CanvasGradient>(CLASSES).fill(rgbCss(ink));
    for (let k = 0; k < 3; k++) {
      styles[CLS_TINT + k] = this.activeRgb ? rgbCss(mixColor(ink, this.activeRgb, TINT_WEIGHTS[k])) : rgbCss(ink);
    }
    // Without speakers, diarizing shows two neutral bands: ink and the tertiary grey.
    for (let k = 0; k < MAX_SPEAKERS; k++) {
      const colour = this.speakerRgb.length > 0
        ? this.speakerRgb[k % this.speakerRgb.length]
        : k === 1 ? ink3 : ink;
      styles[CLS_SPEAKER + k] = rgbCss(colour);
    }
    styles[CLS_DIM] = rgbCss(ink3);
    this.styles = styles;
  }

  /** Sizes the backing store for the current size and device pixel ratio. */
  private fit(size: number): void {
    const dpr = Math.min(3, window.devicePixelRatio || 1);
    const key = `${size}@${dpr}`;
    if (key === this.laidOut) return;
    this.laidOut = key;
    const pixels = Math.max(1, Math.round(size * dpr));
    this.canvas.width = pixels;
    this.canvas.height = pixels;
    this.canvas.style.width = `${size}px`;
    this.canvas.style.height = `${size}px`;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  /** The ink class as a Frost gradient across the orb, cached until the size or the theme ink changes. */
  private frostInk(size: number): string | CanvasGradient {
    const { ink } = this;
    const dark = ink.r + ink.g + ink.b > 382;
    const crimson = document.documentElement.dataset.palette === "crimson";
    const key = `${size}|${dark}|${crimson}`;
    if (this.inkFill && key === this.inkFillKey) return this.inkFill;
    const stops = crimson ? (dark ? CRIMSON_FROST_DARK : CRIMSON_FROST_LIGHT) : dark ? FROST_DARK : FROST_LIGHT;
    const grad = this.ctx.createLinearGradient(0, 0, size, size);
    stops.forEach((colour, i) => grad.addColorStop(i / (stops.length - 1), colour));
    this.inkFill = grad;
    this.inkFillKey = key;
    return grad;
  }

  private ensureSprite(): HTMLCanvasElement {
    const { ink } = this;
    const key = `${ink.r},${ink.g},${ink.b}`;
    if (this.sprite && key === this.spriteKey) return this.sprite;
    const sprite = document.createElement("canvas");
    sprite.width = 128;
    sprite.height = 128;
    const sctx = sprite.getContext("2d");
    if (sctx) {
      // Strongest at the sphere's rim (0.66 of the radius), fading to nothing at the edge.
      const grad = sctx.createRadialGradient(64, 64, 0, 64, 64, 64);
      grad.addColorStop(0, rgbaCss(ink, 0.3));
      grad.addColorStop(0.66, rgbaCss(ink, 1));
      grad.addColorStop(1, rgbaCss(ink, 0));
      sctx.fillStyle = grad;
      sctx.fillRect(0, 0, 128, 128);
      // Soft aurora rim light: a thin Aurora-green band on the same rim. Drawn once into the cached sprite.
      const rim = sctx.createRadialGradient(64, 64, 0, 64, 64, 64);
      rim.addColorStop(0, "rgba(163, 190, 140, 0)");
      rim.addColorStop(0.6, "rgba(163, 190, 140, 0)");
      rim.addColorStop(0.66, "rgba(163, 190, 140, 0.6)");
      rim.addColorStop(0.76, "rgba(163, 190, 140, 0)");
      rim.addColorStop(1, "rgba(163, 190, 140, 0)");
      sctx.fillStyle = rim;
      sctx.fillRect(0, 0, 128, 128);
    }
    this.sprite = sprite;
    this.spriteKey = key;
    return sprite;
  }

  private paint(): void {
    const input = this.input;
    if (!input) return;
    this.syncStyles();
    const size = input.size;
    this.fit(size);
    this.styles[CLS_INK] = this.frostInk(size);
    const ctx = this.ctx;
    const c = this.clock;
    const spec = MODES[input.mode];
    const L = LATTICE;
    const still = this.still;
    const t = c.t;
    const half = size / 2;
    const R = size * RADIUS_RATIO;

    const amp = c.amp + 0.16 * c.energy;
    const breath = still || spec.breath === 0 ? 0 : spec.breath * Math.sin((TAU * t) / spec.breathPeriod);
    const tilt = TILT + (still ? 0 : 0.035 * Math.sin(0.11 * t));
    const cosY = Math.cos(c.yaw);
    const sinY = Math.sin(c.yaw);
    const cosT = Math.cos(tilt);
    const sinT = Math.sin(tilt);
    const introU = still ? 1 : Math.min(1, t / INTRO_S);
    const rippleP = !still && c.rippleAt >= 0 ? ((t - c.rippleAt) * 1000) / RIPPLE_MS : -1;
    const ripple = rippleP >= 0 && rippleP < 1;
    const frontAngle = Math.PI * rippleP;
    const tint = ripple && this.activeRgb !== null;
    const shimmer = !still && input.mode === "thinking";
    // The shimmer band crosses from the top of the sphere to the bottom every 2.2 s.
    const shimmerY = 1 - 2 * ((t % 2.2) / 2.2);
    const diarizing = input.mode === "diarizing";
    const bands = this.speakerRgb.length > 0 ? this.speakerRgb.length : 2;
    const bandShift = 0.1 * t;
    const sparse = input.mode === "idle";
    const dimmed = input.mode === "error";
    const dotScale = clamp(size / 260, 0.6, 1);
    const radiusBoost = input.prominent ? PROMINENT_RADIUS : 1;
    const alphaBoost = input.prominent ? PROMINENT_ALPHA : 1;
    const scatter = c.scatter;
    const progress = c.progress;
    const keys = this.keys;
    const px = this.px;
    const py = this.py;
    const pr = this.pr;

    for (let i = 0; i < DOTS; i++) {
      if (sparse && L.keep[i] > SPARSE_KEEP) {
        keys[i] = SKIP;
        continue;
      }
      // Surface: three sine products over latitude, longitude and time. Normalised to about -1..1.
      const lat = L.lat[i];
      const lon = L.lon[i];
      const wave = (Math.sin(2 * lon + 0.9 * t) * Math.cos(3 * lat - 0.6 * t)
        + 0.5 * Math.sin(5 * lon - 2 * lat + 1.3 * t)
        + 0.25 * Math.sin(7 * lat + 3 * lon - 1.9 * t)) / 1.75;
      const rs = 1 + amp * wave + breath;
      let x = L.ux[i] * rs;
      let y = L.uy[i] * rs;
      let z = L.uz[i] * rs;

      if (scatter > 0) {
        const w = scatter * (1 - smooth01((progress - L.gather[i]) / 0.2));
        if (w > 0) {
          x += (L.scx[i] - x) * w;
          y += (L.scy[i] - y) * w;
          z += (L.scz[i] - z) * w;
        }
      }
      if (introU < 1) {
        const local = clamp01((introU - L.delay[i]) / (1 - L.delay[i]));
        if (local < 1) {
          const e = 1 - (1 - local) ** 3;
          x = L.icx[i] + (x - L.icx[i]) * e;
          y = L.icy[i] + (y - L.icy[i]) * e;
          z = L.icz[i] + (z - L.icz[i]) * e;
        }
      }

      // Rotate: yaw about the vertical axis, then the tilt about the horizontal one.
      const x1 = x * cosY + z * sinY;
      const z1 = z * cosY - x * sinY;
      const y2 = y * cosT - z1 * sinT;
      const z2 = y * sinT + z1 * cosT;
      const persp = CAMERA / (CAMERA - z2);

      // Depth: 0 at the back, 1 at the front. Front dots are 2.2 px and 0.95 alpha; back dots 0.6 px and 0.08.
      const d = clamp01((z2 + 1) * 0.5);
      let alpha = 0.08 + 0.87 * d * Math.sqrt(d);
      let radius = (0.3 + 0.8 * d) * dotScale;
      let cls = CLS_INK;

      if (ripple) {
        // Angle from the front pole, measured on the sphere before the perspective.
        const len = Math.sqrt(x * x + y * y + z * z) || 1;
        const angle = Math.acos(clamp(z2 / len, -1, 1));
        const dd = angle - frontAngle;
        const wv = Math.exp(-(dd * dd) / 0.08);
        if (wv > 0.01) {
          alpha += 0.5 * wv;
          radius += 0.5 * wv * dotScale;
          if (tint && wv > 0.3) cls = CLS_TINT + (wv > 0.75 ? 2 : wv > 0.5 ? 1 : 0);
        }
      }
      if (shimmer) {
        const ds = y2 - shimmerY;
        const s = Math.exp(-(ds * ds) / 0.05);
        alpha += 0.45 * s;
        radius += 0.3 * s * dotScale;
      }
      if (diarizing) {
        let lonNow = (L.lon[i] + bandShift) % TAU;
        if (lonNow < 0) lonNow += TAU;
        cls = CLS_SPEAKER + Math.min(bands - 1, Math.floor((lonNow / TAU) * bands));
      }
      if (dimmed) cls = CLS_DIM;
      alpha *= c.dim * alphaBoost;

      px[i] = half + x1 * persp * R;
      py[i] = half - y2 * persp * R;
      pr[i] = radius * radiusBoost;
      const a = clamp01(alpha) * 0.999;
      keys[i] = Math.floor(a * ALPHA_LEVELS) * CLASSES + cls;
    }

    // Counting sort of the dots into buckets. counts[k] is where bucket k starts.
    const counts = this.counts;
    const cursor = this.cursor;
    const order = this.order;
    counts.fill(0);
    for (let i = 0; i < DOTS; i++) counts[keys[i] + 1]++;
    for (let k = 1; k < counts.length; k++) counts[k] += counts[k - 1];
    cursor.set(counts);
    for (let i = 0; i < DOTS; i++) order[cursor[keys[i]]++] = i;

    ctx.clearRect(0, 0, size, size);

    // Halo behind the sphere: ink at about 6% at the rim, a little stronger with energy.
    const introFade = smooth01(introU);
    const haloAlpha = (0.06 + 0.07 * c.energy) * introFade;
    if (haloAlpha > 0.002) {
      const hr = half * (1 + 0.06 * c.energy);
      ctx.globalAlpha = haloAlpha;
      ctx.drawImage(this.ensureSprite(), half - hr, half - hr, hr * 2, hr * 2);
      ctx.globalAlpha = 1;
    }

    // Finished: a thin ring at 1.12 radii.
    if (c.ring > 0.01) {
      ctx.globalAlpha = 0.2 * c.ring;
      ctx.strokeStyle = this.styles[CLS_INK];
      ctx.lineWidth = 0.5;
      ctx.beginPath();
      ctx.arc(half, half, R * 1.12, 0, TAU);
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    let lastCls = -1;
    for (let k = 0; k < KEYS; k++) {
      const start = counts[k];
      const end = counts[k + 1];
      if (start === end) continue;
      const cls = k % CLASSES;
      if (cls !== lastCls) {
        ctx.fillStyle = this.styles[cls];
        lastCls = cls;
      }
      ctx.globalAlpha = (Math.floor(k / CLASSES) + 0.5) / ALPHA_LEVELS;
      ctx.beginPath();
      for (let j = start; j < end; j++) {
        const i = order[j];
        const x = px[i];
        const y = py[i];
        const r = pr[i];
        ctx.moveTo(x + r, y);
        ctx.arc(x, y, r, 0, TAU);
      }
      ctx.fill();
    }
    ctx.globalAlpha = 1;
  }
}
