import { useEffect, useRef } from "react";
import type { DeviceState } from "./types";

const EXPRESSIONS: Record<string, { eye: number; brow: number; mouth: number; color: string }> = {
  neutral: { eye: 1, brow: 0, mouth: 0, color: "#71d8a8" }, happy: { eye: .7, brow: -.1, mouth: .7, color: "#ffd166" },
  laughing: { eye: .25, brow: -.2, mouth: 1, color: "#ffd166" }, funny: { eye: .5, brow: .2, mouth: .9, color: "#ef8354" },
  sad: { eye: .8, brow: .35, mouth: -.5, color: "#72a9e8" }, angry: { eye: .65, brow: -.45, mouth: -.25, color: "#ef5d60" },
  crying: { eye: .6, brow: .4, mouth: -.7, color: "#72a9e8" }, loving: { eye: .8, brow: -.1, mouth: .65, color: "#f47c9b" },
  embarrassed: { eye: .7, brow: .1, mouth: .15, color: "#f6a6bb" }, surprised: { eye: 1.25, brow: -.25, mouth: 1, color: "#ef8354" },
  shocked: { eye: 1.35, brow: -.35, mouth: 1.2, color: "#ef5d60" }, thinking: { eye: .65, brow: .25, mouth: -.1, color: "#a58bd4" },
  winking: { eye: .45, brow: -.15, mouth: .5, color: "#ffd166" }, cool: { eye: .35, brow: -.15, mouth: .25, color: "#69c8d4" },
  relaxed: { eye: .4, brow: 0, mouth: .35, color: "#71d8a8" }, delicious: { eye: .55, brow: -.05, mouth: .75, color: "#ef8354" },
  kissy: { eye: .45, brow: -.1, mouth: .35, color: "#f47c9b" }, confident: { eye: .6, brow: -.2, mouth: .3, color: "#69c8d4" },
  sleepy: { eye: .2, brow: .15, mouth: .1, color: "#8fa8c7" }, silly: { eye: .8, brow: -.25, mouth: .8, color: "#ef8354" },
  confused: { eye: .7, brow: .35, mouth: -.1, color: "#a58bd4" },
};

export default function StackChanCanvas({ state }: { state: DeviceState }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const canvas = ref.current!;
    const context = canvas.getContext("2d")!;
    const draw = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.round(rect.width * dpr); canvas.height = Math.round(rect.height * dpr);
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
      const w = rect.width, h = rect.height;
      const e = EXPRESSIONS[state.emotion] || EXPRESSIONS.neutral;
      context.clearRect(0, 0, w, h);
      context.fillStyle = "#0c0e10"; context.fillRect(0, 0, w, h);
      context.save();
      context.translate(w / 2 + state.yaw * .25, h * .42 + (state.pitch - 45) * .18);
      context.rotate(state.yaw * .0018);
      const size = Math.min(w * .68, h * .64);
      context.shadowColor = "rgba(0,0,0,.45)"; context.shadowBlur = 30; context.shadowOffsetY = 18;
      rounded(context, -size / 2, -size * .36, size, size * .72, 22);
      context.fillStyle = "#f4f1e9"; context.fill(); context.shadowColor = "transparent";
      rounded(context, -size * .43, -size * .29, size * .86, size * .58, 15);
      context.fillStyle = "#171a1d"; context.fill();
      context.strokeStyle = e.color; context.lineWidth = Math.max(3, size * .018); context.globalAlpha = .95;
      const eyeY = -size * .055; const eyeR = size * .052;
      drawEye(context, -size * .18, eyeY, eyeR, e.eye, e.brow, false, state.emotion === "winking");
      drawEye(context, size * .18, eyeY, eyeR, e.eye, e.brow, true, false);
      const audioMouth = Math.max(state.mouth, state.status === "speaking" ? .12 : 0);
      context.beginPath();
      context.ellipse(0, size * .13, size * (.07 + Math.max(0, e.mouth) * .035), size * (.012 + audioMouth * .065 + Math.abs(e.mouth) * .018), 0, 0, Math.PI * 2);
      if (e.mouth < 0 && audioMouth < .15) { context.moveTo(-size * .08, size * .17); context.quadraticCurveTo(0, size * .105, size * .08, size * .17); }
      context.stroke();
      context.restore();
      const baseY = h * .79;
      context.fillStyle = "#d9dde0"; rounded(context, w * .37, baseY, w * .26, h * .08, 8); context.fill();
      context.fillStyle = "#272c30"; rounded(context, w * .31, h * .86, w * .38, h * .08, 8); context.fill();
      state.leds.forEach((color, index) => {
        const angle = Math.PI * 2 * index / 12 - Math.PI / 2;
        const x = w / 2 + Math.cos(angle) * Math.min(w, h) * .34;
        const y = h * .42 + Math.sin(angle) * Math.min(w, h) * .34;
        context.beginPath(); context.arc(x, y, 5, 0, Math.PI * 2); context.fillStyle = color; context.shadowColor = color; context.shadowBlur = 9; context.fill(); context.shadowBlur = 0;
      });
      context.fillStyle = "rgba(255,255,255,.72)"; context.font = "12px ui-monospace, monospace";
      context.fillText(`${state.mode.toUpperCase()} / ${state.emotion.toUpperCase()}`, 16, h - 18);
    };
    draw(); const observer = new ResizeObserver(draw); observer.observe(canvas); return () => observer.disconnect();
  }, [state]);
  return <canvas ref={ref} aria-label="StackChan simulated display" />;
}

function rounded(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }
function drawEye(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, scale: number, brow: number, mirror: boolean, wink: boolean) {
  ctx.beginPath();
  if (wink) { ctx.moveTo(x - r, y); ctx.quadraticCurveTo(x, y + r * .45, x + r, y); }
  else ctx.ellipse(x, y, r * .75, Math.max(2, r * scale), 0, 0, Math.PI * 2);
  ctx.stroke(); ctx.beginPath(); ctx.moveTo(x - r, y - r * 1.75 + brow * r * (mirror ? -1 : 1)); ctx.lineTo(x + r, y - r * 1.75 - brow * r * (mirror ? -1 : 1)); ctx.stroke();
}
