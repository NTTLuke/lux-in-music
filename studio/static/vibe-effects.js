"use strict";

/* Local playback visualization. One media source, no microphone or audio effects. */
window.VibeEffects = (() => {
  const canvas = document.getElementById("vibe-effects");
  const button = document.getElementById("vibe-effects-toggle");
  const message = document.getElementById("vibe-effects-message");
  const player = document.getElementById("audio");
  const view = document.getElementById("vibe-listening");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)");
  const storageKey = "lux.vibe.effects";
  const painter = canvas.getContext("2d", { alpha: true });
  let enabled = true;
  try { enabled = localStorage.getItem(storageKey) !== "off"; } catch { /* Storage is optional. */ }
  let context = null, source = null, analyser = null, preparing = null;
  let frequencies = null, waveform = null, visible = false, failed = false;
  let frame = 0, last = 0, phase = 0, energy = 0, bass = 0, mid = 0, treble = 0;
  let pulse = 0, beatFloor = 0, lastBeat = 0, width = 0, height = 0, sparks = [];
  const sprites = {};
  const palette = [[240, 147, 56], [214, 90, 128], [138, 93, 175], [62, 150, 153]];
  const sparkColors = ["255,214,148", "255,214,148", "146,214,214", "236,158,188"];
  const running = () => enabled && !failed && !reduced.matches && visible && !player.paused && !document.hidden;

  function controls() {
    const on = enabled && !reduced.matches && !failed;
    button.textContent = `Effects ${on ? "On" : "Off"}`;
    button.setAttribute("aria-pressed", String(on));
    button.disabled = reduced.matches || failed;
    button.title = reduced.matches ? "Motion effects are disabled by your reduced-motion preference."
      : failed ? "Audio visualization is unavailable. Music playback is unchanged."
      : "A breathing glow, light rays and sparkles that react to the playing music";
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

  /* Palette entries slowly trade colors so long songs keep moving. */
  function drift(a, b, offset) {
    const mix = .5 + .5 * Math.sin(offset), from = palette[a], to = palette[b];
    return `${Math.round(from[0] + (to[0] - from[0]) * mix)},${Math.round(from[1] + (to[1] - from[1]) * mix)},${Math.round(from[2] + (to[2] - from[2]) * mix)}`;
  }

  /* Elliptical ambient pool with a hot core and a long soft falloff. */
  function light(x, y, radius, color, opacity) {
    if (radius <= 0 || opacity <= .004) return;
    painter.save(); painter.translate(x, y);
    painter.rotate(phase * .22 + x / width);
    painter.scale(1, .65 + .15 * Math.sin(phase * .45 + x / width));
    const gradient = painter.createRadialGradient(0, 0, 0, 0, 0, radius);
    gradient.addColorStop(0, `rgba(${color},${opacity})`);
    gradient.addColorStop(.3, `rgba(${color},${opacity * .58})`);
    gradient.addColorStop(.65, `rgba(${color},${opacity * .16})`);
    gradient.addColorStop(1, `rgba(${color},0)`);
    painter.fillStyle = gradient; painter.fillRect(-radius, -radius, radius * 2, radius * 2);
    painter.restore();
  }

  /* Circular bloom for the halo directly behind the artwork. */
  function glow(x, y, radius, color, opacity) {
    if (radius <= 0 || opacity <= .004) return;
    const gradient = painter.createRadialGradient(x, y, 0, x, y, radius);
    gradient.addColorStop(0, `rgba(${color},${opacity})`);
    gradient.addColorStop(.32, `rgba(${color},${opacity * .55})`);
    gradient.addColorStop(.68, `rgba(${color},${opacity * .15})`);
    gradient.addColorStop(1, `rgba(${color},0)`);
    painter.fillStyle = gradient; painter.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  }

  /* Pre-rendered radial sprites keep dozens of sparkles cheap. */
  function glowSprite(color) {
    if (sprites[color]) return sprites[color];
    const dot = document.createElement("canvas"); dot.width = dot.height = 64;
    const pen = dot.getContext("2d");
    const gradient = pen.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, `rgba(${color},1)`);
    gradient.addColorStop(.22, `rgba(${color},.62)`);
    gradient.addColorStop(1, `rgba(${color},0)`);
    pen.fillStyle = gradient; pen.fillRect(0, 0, 64, 64);
    return sprites[color] = dot;
  }

  function seedSparks() {
    sparks = [];
    for (let i = 0; i < 56; i++) sparks.push({
      x: Math.random(), y: Math.random(),
      rise: .006 + Math.random() * .02, sway: 8 + Math.random() * 24,
      freq: .25 + Math.random() * .8, size: 5 + Math.random() * 15,
      twinkle: .8 + Math.random() * 2.6, offset: Math.random() * 6.283,
      color: sparkColors[i % sparkColors.length],
    });
  }

  function draw(dt) {
    if (!width || !height) return;
    const w = width, h = height, t = phase, beat = pulse;
    const size = Math.max(w, h), span = Math.min(w, h);
    painter.clearRect(0, 0, w, h);
    // Darkened edges make the center read as a source of light.
    painter.globalCompositeOperation = "source-over";
    const vignette = painter.createRadialGradient(w * .5, h * .42, span * .3, w * .5, h * .5, size * .78);
    vignette.addColorStop(0, "rgba(3,2,7,0)"); vignette.addColorStop(1, "rgba(3,2,7,.38)");
    painter.fillStyle = vignette; painter.fillRect(0, 0, w, h);
    // Broad amber, rose, violet and teal pools fold around the image, with a bass-led breath.
    painter.globalCompositeOperation = "screen";
    light(w * (.2 + .11 * Math.sin(t * .7)), h * (.46 + .15 * Math.cos(t * .47)),
      size * (.40 + bass * .13), drift(0, 1, t * .21), .3 + bass * .5);
    light(w * (.78 + .09 * Math.cos(t * .53)), h * (.38 + .16 * Math.sin(t * .61)),
      size * (.35 + mid * .15), drift(2, 1, t * .17 + 2), .26 + mid * .42);
    light(w * (.5 + .25 * Math.sin(t * .31)), h * (.76 + .09 * Math.cos(t * .59)),
      size * (.32 + treble * .16), drift(3, 2, t * .19 + 4), .2 + treble * .42);
    light(w * (.62 + .3 * Math.cos(t * .41)), h * (.2 + .12 * Math.sin(t * .57)),
      size * (.24 + energy * .12), drift(1, 0, t * .25 + 1), .14 + energy * .3);
    // A hot halo beats behind the artwork: aura, bloom, core and a white-hot point.
    painter.globalCompositeOperation = "lighter";
    const cx = w * .5, cy = h * .44, halo = span * (.5 + bass * .22 + beat * .16);
    glow(cx, cy, halo * 2.3, drift(2, 1, t * .13), .05 + energy * .1);
    glow(cx, cy, halo * 1.35, drift(0, 1, t * .11 + 3), .12 + bass * .22 + beat * .2);
    glow(cx, cy, halo * .62, "255,222,168", .16 + bass * .26 + beat * .3);
    glow(cx, cy, halo * .26, "255,244,222", .1 + energy * .14 + beat * .42);
    // Slow concert shafts breathe with the mid band and kick on beats.
    const rays = 10;
    for (let i = 0; i < rays; i++) {
      const alpha = (.02 + energy * .055 + beat * .05) * (.5 + .5 * Math.sin(t * .5 + i * 2.6));
      if (alpha <= .005) continue;
      const angle = i / rays * 6.283 + t * .12 + Math.sin(t * .21 + i) * .12;
      const length = span * (.48 + .28 * Math.sin(t * .34 + i * 2.1) + mid * .32 + beat * .22);
      const spread = .1 + .05 * Math.sin(t * .27 + i * 1.7);
      const gradient = painter.createLinearGradient(cx, cy, cx + Math.cos(angle) * length, cy + Math.sin(angle) * length);
      gradient.addColorStop(0, `rgba(255,214,150,${alpha})`);
      gradient.addColorStop(.55, `rgba(244,156,116,${alpha * .45})`);
      gradient.addColorStop(1, "rgba(244,156,116,0)");
      painter.fillStyle = gradient;
      painter.beginPath(); painter.moveTo(cx, cy);
      painter.arc(cx, cy, length, angle - spread, angle + spread);
      painter.closePath(); painter.fill();
    }
    // Rising embers twinkle with the treble and flare on beats.
    if (!sparks.length) seedSparks();
    const sparkLift = .1 + treble * .5 + beat * .3;
    for (const spark of sparks) {
      spark.y -= spark.rise * dt * (1 + energy * 2.4);
      if (spark.y < -.06) { spark.y = 1.06; spark.x = Math.random(); }
      const alpha = sparkLift * (.5 + .5 * Math.sin(t * spark.twinkle + spark.offset));
      if (alpha <= .012) continue;
      const x = spark.x * w + Math.sin(t * spark.freq + spark.offset) * spark.sway * w / 960;
      const diameter = spark.size * span / 720 * (1 + beat * .4);
      painter.globalAlpha = Math.min(1, alpha);
      painter.drawImage(glowSprite(spark.color), x - diameter / 2, spark.y * h - diameter / 2, diameter, diameter);
    }
    painter.globalAlpha = 1;
    // Long liquid ribbons, never hard flashing edges: a wide haze around a bright core.
    painter.globalCompositeOperation = "screen";
    for (let layer = 0; layer < 4; layer++) {
      const y = h * (.46 + layer * .06), bend = h * (.1 + bass * .12);
      const gradient = painter.createLinearGradient(0, 0, w, h);
      gradient.addColorStop(0, "rgba(240,162,60,0)");
      gradient.addColorStop(.28, `rgba(240,162,60,${.14 + energy * .32})`);
      gradient.addColorStop(.7, `rgba(111,169,174,${.1 + mid * .27})`);
      gradient.addColorStop(1, "rgba(151,101,185,0)");
      painter.strokeStyle = gradient;
      painter.beginPath(); painter.moveTo(-w * .1, y);
      painter.bezierCurveTo(w * .25, y - bend * Math.sin(t + layer * .6),
        w * .65, y + bend * Math.cos(t * .8 + layer), w * 1.1, y - h * .1);
      painter.globalAlpha = .35; painter.lineWidth = size * (.024 + layer * .009); painter.stroke();
      painter.globalAlpha = 1; painter.lineWidth = size * (.008 + layer * .004); painter.stroke();
    }
    // Mirrored frequency pillars sit at the outer edges, behind the artwork.
    const count = 42, step = h * .68 / count;
    for (let i = 0; i < count; i++) {
      const frequency = 45 * Math.pow(160, i / (count - 1));
      const bin = Math.min(frequencies.length - 1, Math.round(frequency * analyser.fftSize / context.sampleRate));
      const magnitude = frequencies[bin] / 255, length = w * (.008 + magnitude * .095);
      const y = h * .16 + i * step, thick = Math.max(1, step * .26);
      const color = drift(i < 17 ? 0 : 3, i < 17 ? 1 : 2, t * .3 + i * .05);
      painter.fillStyle = `rgba(${color},${.05 + magnitude * .22})`;
      painter.fillRect(w * .045 - 2, y - thick, length * 1.25 + 2, thick * 3);
      painter.fillRect(w * .955 - length * 1.25, y - thick, length * 1.25 + 2, thick * 3);
      painter.fillStyle = `rgba(${color},${.14 + magnitude * .46})`;
      painter.fillRect(w * .045, y, length, thick);
      painter.fillRect(w * .955 - length, y, length, thick);
    }
    painter.globalCompositeOperation = "source-over";
    const level = energy.toFixed(3);
    canvas.style.setProperty("--vibe-energy", level);
    view.style.setProperty("--vibe-energy", level);
    view.style.setProperty("--vibe-bass", bass.toFixed(3));
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
      const bassNow = band(30, 180), midNow = band(180, 2500), trebleNow = band(2500, 10000);
      bass += (bassNow - bass) * .15;
      mid += (midNow - mid) * .12;
      treble += (trebleNow - treble) * .1;
      // Beat onsets kick the halo: a fast bass rise over its recent floor.
      beatFloor += (bassNow - beatFloor) * .045;
      if (bassNow > .16 && bassNow > beatFloor * 1.32 + .04 && now - lastBeat > 220) {
        lastBeat = now; pulse = Math.min(1, pulse + .5 + bassNow * .35);
      }
      pulse *= Math.exp(-dt * 3.4);
      phase += dt * (.18 + energy * .65);
      draw(dt);
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
  player.addEventListener("emptied", () => { energy = bass = mid = treble = pulse = beatFloor = 0; sync(); });
  controls();
  return {
    show: () => { visible = true; sync(); },
    hide: () => { visible = false; sync(); },
    // Keep the context alive once attached: it is the player's transparent audio path.
  };
})();
