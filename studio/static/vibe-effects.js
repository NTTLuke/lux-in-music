"use strict";

/* Local playback visualization. One media source, no microphone or audio effects. */
window.VibeEffects = (() => {
  const canvas = document.getElementById("vibe-effects");
  const button = document.getElementById("vibe-effects-toggle");
  const message = document.getElementById("vibe-effects-message");
  const player = document.getElementById("audio");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const storageKey = "lux.vibe.effects";
  const painter = canvas.getContext("2d", { alpha: true });
  let enabled = true;
  try { enabled = localStorage.getItem(storageKey) !== "off"; } catch { /* Storage is optional. */ }
  let context = null, source = null, analyser = null, preparing = null;
  let frequencies = null, waveform = null, visible = false, failed = false;
  let frame = 0, last = 0, phase = 0, energy = 0, bass = 0, mid = 0, treble = 0;
  let width = 0, height = 0;
  const running = () => enabled && !failed && !reduced.matches && visible && !player.paused && !document.hidden;

  function controls() {
    const on = enabled && !reduced.matches && !failed;
    button.textContent = `Effects ${on ? "On" : "Off"}`;
    button.setAttribute("aria-pressed", String(on));
    button.disabled = reduced.matches || failed;
    button.title = reduced.matches ? "Motion effects are disabled by your reduced-motion preference."
      : failed ? "Audio visualization is unavailable. Music playback is unchanged."
      : "Liquid glow and an equalizer that react to the playing music";
    canvas.classList.toggle("enabled", on);
    message.textContent = failed ? "Audio effects are unavailable in this browser. Playback continues." : "";
    message.hidden = !failed;
  }

  async function prepare() {
    if (analyser && context.state === "running") return true;
    if (preparing) return preparing;
    preparing = (async () => {
      try {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext || !painter) throw new Error("Visualization unavailable");
        context ||= new AudioContext();
        // Attach only after resume succeeds: an unavailable context must not mute playback.
        await context.resume();
        if (context.state !== "running") return false;
        if (!source) {
          const node = context.createAnalyser();
          node.fftSize = 2048; node.smoothingTimeConstant = .72;
          node.minDecibels = -90; node.maxDecibels = -15;
          node.connect(context.destination);
          source = context.createMediaElementSource(player);
          source.connect(node); analyser = node;
          frequencies = new Uint8Array(node.frequencyBinCount);
          waveform = new Float32Array(node.fftSize);
        }
        return true;
      } catch {
        failed = true; controls();
        return false;
      }
    })();
    try { return await preparing; } finally { preparing = null; }
  }

  function resize() {
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    // Soft light needs few pixels. Bound raster work independently of Retina resolution.
    const scale = Math.min(1, 960 / rect.width, 720 / rect.height);
    width = Math.max(1, Math.round(rect.width * scale)); height = Math.max(1, Math.round(rect.height * scale));
    if (canvas.width !== width || canvas.height !== height) { canvas.width = width; canvas.height = height; }
  }

  function band(low, high) {
    const hz = context.sampleRate / analyser.fftSize;
    const start = Math.max(1, Math.floor(low / hz)), end = Math.min(frequencies.length, Math.ceil(high / hz));
    let sum = 0;
    for (let i = start; i < end; i++) sum += frequencies[i] * frequencies[i];
    return end > start ? Math.sqrt(sum / (end - start)) / 255 : 0;
  }

  function light(x, y, radius, color, opacity) {
    painter.save(); painter.translate(x, y);
    painter.rotate(phase * .22 + x / width);
    painter.scale(1, .65 + .15 * Math.sin(phase * .45 + x / width));
    const gradient = painter.createRadialGradient(0, 0, 0, 0, 0, radius);
    gradient.addColorStop(0, `rgba(${color},${opacity})`);
    gradient.addColorStop(.38, `rgba(${color},${opacity * .58})`);
    gradient.addColorStop(1, `rgba(${color},0)`);
    painter.fillStyle = gradient; painter.fillRect(-radius, -radius, radius * 2, radius * 2);
    painter.restore();
  }

  function draw() {
    if (!width || !height) return;
    const w = width, h = height, t = phase, size = Math.max(w, h);
    painter.clearRect(0, 0, w, h);
    painter.globalCompositeOperation = "screen";
    // Broad amber, rose and teal pools fold around the image, with a bass-led breath.
    light(w * (.2 + .11 * Math.sin(t * .7)), h * (.46 + .15 * Math.cos(t * .47)),
      size * (.40 + bass * .13), "240,147,56", .25 + bass * .45);
    light(w * (.78 + .09 * Math.cos(t * .53)), h * (.38 + .16 * Math.sin(t * .61)),
      size * (.35 + mid * .15), "138,93,175", .24 + mid * .40);
    light(w * (.5 + .25 * Math.sin(t * .31)), h * (.76 + .09 * Math.cos(t * .59)),
      size * (.32 + treble * .16), "62,150,153", .17 + treble * .4);
    // Long liquid ribbons, never hard flashing edges.
    for (let layer = 0; layer < 4; layer++) {
      const y = h * (.46 + layer * .06), bend = h * (.1 + bass * .12);
      const gradient = painter.createLinearGradient(0, 0, w, h);
      gradient.addColorStop(0, "rgba(240,162,60,0)");
      gradient.addColorStop(.28, `rgba(240,162,60,${.12 + energy * .3})`);
      gradient.addColorStop(.7, `rgba(111,169,174,${.08 + mid * .25})`);
      gradient.addColorStop(1, "rgba(151,101,185,0)");
      painter.strokeStyle = gradient; painter.lineWidth = size * (.012 + layer * .007);
      painter.beginPath(); painter.moveTo(-w * .1, y);
      painter.bezierCurveTo(w * .25, y - bend * Math.sin(t + layer * .6),
        w * .65, y + bend * Math.cos(t * .8 + layer), w * 1.1, y - h * .1);
      painter.stroke();
    }
    // Mirrored frequency pillars sit at the outer edges, behind the artwork.
    const count = 42, step = h * .68 / count;
    for (let i = 0; i < count; i++) {
      const frequency = 45 * Math.pow(160, i / (count - 1));
      const bin = Math.min(frequencies.length - 1, Math.round(frequency * analyser.fftSize / context.sampleRate));
      const magnitude = frequencies[bin] / 255, length = w * (.006 + magnitude * .085);
      const y = h * .16 + i * step;
      painter.fillStyle = `rgba(${i < 17 ? "240,162,60" : "117,165,173"},${.10 + magnitude * .42})`;
      painter.fillRect(w * .045, y, length, Math.max(1, step * .26));
      painter.fillRect(w * .955 - length, y, length, Math.max(1, step * .26));
    }
    painter.globalCompositeOperation = "source-over";
    canvas.style.setProperty("--vibe-energy", energy.toFixed(3));
  }

  function tick(now) {
    frame = 0;
    if (!running() || !analyser || context.state !== "running") return;
    if (!last || now - last >= 1000 / 30) {
      const dt = last ? Math.min(.1, (now - last) / 1000) : 1 / 30; last = now;
      analyser.getByteFrequencyData(frequencies); analyser.getFloatTimeDomainData(waveform);
      let sum = 0;
      for (const sample of waveform) sum += sample * sample;
      const level = Math.min(1, Math.sqrt(sum / waveform.length) * 4);
      const ease = 1 - Math.exp(-dt * (level > energy ? 10 : 2.6));
      energy += (level - energy) * ease;
      bass += (band(30, 180) - bass) * .15;
      mid += (band(180, 2500) - mid) * .12;
      treble += (band(2500, 10000) - treble) * .1;
      phase += dt * (.18 + energy * .65);
      draw();
    }
    frame = requestAnimationFrame(tick);
  }

  async function sync() {
    cancelAnimationFrame(frame); frame = 0; last = 0; controls();
    if (!running()) return;
    if (await prepare() && running() && !frame) { resize(); frame = requestAnimationFrame(tick); }
  }
  button.onclick = () => {
    enabled = !enabled;
    try { localStorage.setItem(storageKey, enabled ? "on" : "off"); } catch { /* Keep the session choice. */ }
    sync();
  };
  reduced.addEventListener("change", sync);
  document.addEventListener("visibilitychange", sync);
  window.addEventListener("resize", () => { if (visible) resize(); });
  player.addEventListener("play", sync);
  player.addEventListener("pause", sync);
  player.addEventListener("ended", sync);
  player.addEventListener("emptied", () => { energy = bass = mid = treble = 0; sync(); });
  controls();
  return {
    show: () => { visible = true; sync(); },
    hide: () => { visible = false; sync(); },
    // Keep the context alive once attached: it is the player's transparent audio path.
  };
})();
