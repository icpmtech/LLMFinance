/**
 * Órbe do Jarvis — a cara animada do assistente.
 *
 * Um canvas sem dependências que muda de comportamento conforme o estado:
 *
 * - `idle` — respira devagar (à espera);
 * - `listening` — pulsa com o nível do microfone (está a ouvir);
 * - `thinking` — arcos a orbitar depressa (a falar com os gateways);
 * - `speaking` — anéis a expandir-se com a voz (está a responder).
 *
 * O desenho respeita `prefers-reduced-motion` (nesse caso fica num quadro
 * estático, sem animação contínua) e para quando o separador está escondido,
 * para não gastar bateria com uma app aberta em segundo plano.
 */
import { useEffect, useRef } from "react";

export type JarvisOrbState = "idle" | "listening" | "thinking" | "speaking";

type Palette = { core: string; mid: string; outer: string; glow: string };

const PALETTES: Record<JarvisOrbState, Palette> = {
  idle: { core: "#7dd3fc", mid: "#0ea5e9", outer: "#0369a1", glow: "14,165,233" },
  listening: { core: "#fde68a", mid: "#f59e0b", outer: "#b45309", glow: "245,158,11" },
  thinking: { core: "#e9d5ff", mid: "#a855f7", outer: "#6b21a8", glow: "168,85,247" },
  speaking: { core: "#99f6e4", mid: "#14b8a6", outer: "#0f766e", glow: "20,184,166" },
};

export type JarvisOrbProps = {
  state: JarvisOrbState;
  /** Nível do áudio (0–1) — só usado em `listening` e `speaking`. */
  level?: number;
  size?: number;
  className?: string;
  onClick?: () => void;
  title?: string;
};

export default function JarvisOrb({
  state,
  level = 0,
  size = 168,
  className = "",
  onClick,
  title,
}: JarvisOrbProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Os props são lidos por ref para o ciclo de animação nunca ser reiniciado.
  const stateRef = useRef<JarvisOrbState>(state);
  const levelRef = useRef(level);
  stateRef.current = state;
  levelRef.current = level;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const reduced =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    context.scale(dpr, dpr);

    const center = size / 2;
    const baseRadius = size * 0.24;
    // O nível do áudio é suavizado: sem isto a órbita treme com cada sílaba.
    let smoothLevel = 0;
    let frame = 0;
    let raf = 0;

    const rings = [
      { radius: 0.34, speed: 0.55, tilt: 0.35, particles: 22, width: 1.2 },
      { radius: 0.42, speed: -0.34, tilt: -0.5, particles: 30, width: 1 },
      { radius: 0.48, speed: 0.22, tilt: 1.15, particles: 16, width: 0.9 },
    ];

    const draw = (time: number) => {
      const palette = PALETTES[stateRef.current];
      const rawLevel = stateRef.current === "listening" || stateRef.current === "speaking" ? levelRef.current : 0;
      smoothLevel += (Math.max(0, Math.min(1, rawLevel)) - smoothLevel) * 0.15;

      const seconds = time / 1000;
      const breath = stateRef.current === "idle" ? 0.5 + 0.5 * Math.sin(seconds * 1.1) : 0.5 + 0.5 * Math.sin(seconds * 3.2);
      const energy = stateRef.current === "thinking" ? 0.85 : 0.35 + smoothLevel * 0.65;
      const pulse = 1 + (stateRef.current === "idle" ? 0.045 * breath : 0.12 * energy * (0.4 + breath));

      context.clearRect(0, 0, size, size);
      context.globalCompositeOperation = "lighter";

      // Halo exterior
      const halo = context.createRadialGradient(center, center, baseRadius * 0.4, center, center, size * 0.52);
      halo.addColorStop(0, `rgba(${palette.glow},${0.28 * (0.6 + smoothLevel * 0.4)})`);
      halo.addColorStop(1, `rgba(${palette.glow},0)`);
      context.fillStyle = halo;
      context.beginPath();
      context.arc(center, center, size * 0.52, 0, Math.PI * 2);
      context.fill();

      // Anéis orbitais com partículas
      rings.forEach((ring, index) => {
        const spin = seconds * ring.speed;
        const radius = size * ring.radius * pulse;
        context.save();
        context.translate(center, center);
        context.rotate(ring.tilt);
        context.strokeStyle = `rgba(${palette.glow},${0.16 + index * 0.05})`;
        context.lineWidth = ring.width;
        context.beginPath();
        context.ellipse(0, 0, radius, radius * 0.42, spin, 0, Math.PI * 2);
        context.stroke();
        context.restore();

        for (let i = 0; i < ring.particles; i += 1) {
          const angle = (i / ring.particles) * Math.PI * 2 + spin * (1 + index * 0.2);
          const wobble = Math.sin(seconds * 2 + i) * size * 0.012;
          const x = center + Math.cos(angle) * radius;
          const y = center + Math.sin(angle) * radius * 0.42 + wobble;
          const dot = 1.1 + (i % 3) * 0.5 + smoothLevel * 1.6;
          context.fillStyle = `rgba(${palette.glow},${0.5 + 0.4 * breath})`;
          context.beginPath();
          context.arc(x, y, dot, 0, Math.PI * 2);
          context.fill();
        }
      });

      // Anéis de voz: expandem-se com o nível do áudio
      if (stateRef.current === "speaking" || stateRef.current === "listening") {
        for (let i = 0; i < 3; i += 1) {
          const progress = (seconds * 0.8 + i / 3) % 1;
          const radius = baseRadius * pulse + progress * size * 0.28;
          context.strokeStyle = `rgba(${palette.glow},${(1 - progress) * 0.4 * (0.4 + smoothLevel)})`;
          context.lineWidth = 1.4;
          context.beginPath();
          context.arc(center, center, radius, 0, Math.PI * 2);
          context.stroke();
        }
      }

      // Núcleo
      const coreRadius = baseRadius * pulse * (1 + smoothLevel * 0.25);
      const core = context.createRadialGradient(
        center - coreRadius * 0.25,
        center - coreRadius * 0.3,
        coreRadius * 0.1,
        center,
        center,
        coreRadius,
      );
      core.addColorStop(0, palette.core);
      core.addColorStop(0.55, palette.mid);
      core.addColorStop(1, palette.outer);
      context.globalCompositeOperation = "source-over";
      context.fillStyle = core;
      context.beginPath();
      context.arc(center, center, coreRadius, 0, Math.PI * 2);
      context.fill();

      // Reflexo superior
      context.fillStyle = `rgba(255,255,255,${0.16 + 0.12 * breath})`;
      context.beginPath();
      context.ellipse(center, center - coreRadius * 0.42, coreRadius * 0.5, coreRadius * 0.24, 0, 0, Math.PI * 2);
      context.fill();
      context.globalCompositeOperation = "lighter";
    };

    const loop = (time: number) => {
      frame += 1;
      if (frame % 2 === 0) draw(time); // 30 fps chega para um órbe suave
      raf = window.requestAnimationFrame(loop);
    };

    const still = (time: number) => {
      draw(time);
      raf = window.setTimeout(() => still(performance.now()), 400) as unknown as number;
    };

    if (reduced) {
      still(performance.now());
    } else {
      raf = window.requestAnimationFrame(loop);
    }

    // Sem animação quando o separador está escondido (poupa bateria).
    const onVisibility = () => {
      window.cancelAnimationFrame(raf);
      window.clearTimeout(raf);
      if (!document.hidden) raf = window.requestAnimationFrame(loop);
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.cancelAnimationFrame(raf);
      window.clearTimeout(raf);
    };
  }, [size]);

  return (
    <canvas
      ref={canvasRef}
      width={size}
      height={size}
      onClick={onClick}
      title={title}
      aria-label={title || `Jarvis (${state})`}
      role="img"
      className={`${onClick ? "cursor-pointer" : ""} ${className}`}
      style={{ width: size, height: size }}
    />
  );
}
