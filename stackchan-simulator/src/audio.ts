let context: AudioContext | null = null;
let node: AudioWorkletNode | null = null;

const processor = `
class PCMPlayer extends AudioWorkletProcessor {
  constructor(){ super(); this.queue=[]; this.offset=0; this.port.onmessage=e=>this.queue.push(e.data); }
  process(_, outputs){ const out=outputs[0][0]; out.fill(0); let i=0; while(i<out.length&&this.queue.length){ const b=this.queue[0]; const n=Math.min(out.length-i,b.length-this.offset); out.set(b.subarray(this.offset,this.offset+n),i); i+=n; this.offset+=n; if(this.offset>=b.length){this.queue.shift();this.offset=0;} } return true; }
}
registerProcessor('pcm-player', PCMPlayer);`;

export async function enableAudio(): Promise<void> {
  if (!context) {
    context = new AudioContext({ sampleRate: 24000 });
    const url = URL.createObjectURL(new Blob([processor], { type: "text/javascript" }));
    await context.audioWorklet.addModule(url); URL.revokeObjectURL(url);
    node = new AudioWorkletNode(context, "pcm-player"); node.connect(context.destination);
  }
  await context.resume();
}

export function playPcm(base64: string): void {
  if (!node) return;
  const raw = atob(base64); const values = new Float32Array(raw.length / 2);
  for (let index = 0; index < values.length; index += 1) {
    const lo = raw.charCodeAt(index * 2); const hi = raw.charCodeAt(index * 2 + 1);
    const signed = (hi << 8) | lo; values[index] = (signed > 32767 ? signed - 65536 : signed) / 32768;
  }
  node.port.postMessage(values);
}
