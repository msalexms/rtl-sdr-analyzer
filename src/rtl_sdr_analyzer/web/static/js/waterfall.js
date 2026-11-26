import { PAD_LEFT, PAD_RIGHT } from './spectrum.js';

function lerpStops(stops, t) {
  const clamped = Math.min(1, Math.max(0, t));
  for (let i = 0; i < stops.length - 1; i += 1) {
    const [t0, c0] = stops[i];
    const [t1, c1] = stops[i + 1];
    if (clamped >= t0 && clamped <= t1) {
      const f = (clamped - t0) / Math.max(1e-6, t1 - t0);
      return [
        Math.round(c0[0] + (c1[0] - c0[0]) * f),
        Math.round(c0[1] + (c1[1] - c0[1]) * f),
        Math.round(c0[2] + (c1[2] - c0[2]) * f),
      ];
    }
  }
  return stops[stops.length - 1][1];
}

const COLORMAPS = {
  amstech: [
    [0.0, [24, 24, 29]],
    [0.25, [43, 54, 217]],
    [0.52, [124, 196, 255]],
    [0.72, [111, 208, 140]],
    [0.88, [255, 226, 122]],
    [1.0, [255, 92, 57]],
  ],
  viridis: [
    [0.0, [68, 1, 84]],
    [0.25, [59, 82, 139]],
    [0.5, [33, 145, 140]],
    [0.75, [94, 201, 98]],
    [1.0, [253, 231, 37]],
  ],
  inferno: [
    [0.0, [0, 0, 4]],
    [0.25, [87, 16, 110]],
    [0.5, [188, 55, 84]],
    [0.75, [249, 142, 9]],
    [1.0, [252, 255, 164]],
  ],
};

function buildLut(name) {
  const stops = COLORMAPS[name] || COLORMAPS.amstech;
  const lut = new Uint8ClampedArray(256 * 3);
  for (let i = 0; i < 256; i += 1) {
    const [r, g, b] = lerpStops(stops, i / 255);
    lut[i * 3] = r;
    lut[i * 3 + 1] = g;
    lut[i * 3 + 2] = b;
  }
  return lut;
}

export class WaterfallCanvas {
  constructor(canvas, cursorEl = null, callbacks = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.cursorEl = cursorEl;
    this.callbacks = callbacks;
    this.lut = buildLut('amstech');
    this.rowBuffer = null;

    this.startMhz = 97.0;
    this.stepMhz = 0.001;
    this.binCount = 2048;

    this._bindEvents();
    this.resize();
  }

  _bindEvents() {
    window.addEventListener('resize', () => this.resize());
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(this.canvas.parentElement || this.canvas);
    }

    this.canvas.addEventListener('mousemove', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      this.setHoverX(x);
      if (this.callbacks.onHoverXChange) this.callbacks.onHoverXChange(x);
    });

    this.canvas.addEventListener('mouseleave', () => {
      this.setHoverX(null);
      if (this.callbacks.onHoverXChange) this.callbacks.onHoverXChange(null);
    });

    this.canvas.addEventListener('click', (e) => {
      if (!this.callbacks.onTuneFreqMhz || this.binCount < 2) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
      if (x < PAD_LEFT || x > rect.width - PAD_RIGHT) return;
      const frac = Math.min(1, Math.max(0, (x - PAD_LEFT) / plotW));
      const freqMhz = this.startMhz + frac * (this.binCount - 1) * this.stepMhz;
      this.callbacks.onTuneFreqMhz(Number(Math.min(1766, Math.max(24, freqMhz)).toFixed(4)));
    });

    this.canvas.addEventListener(
      'wheel',
      (e) => {
        if (!this.callbacks.onWheelStep) return;
        e.preventDefault();
        const dir = e.deltaY < 0 ? 1 : -1;
        const step = e.shiftKey ? 1.0 : e.altKey ? 0.01 : 0.1;
        this.callbacks.onWheelStep(dir * step);
      },
      { passive: false },
    );
  }

  setAxis(startMhz, stepMhz, binCount) {
    this.startMhz = startMhz;
    this.stepMhz = stepMhz;
    this.binCount = binCount;
  }

  setHoverX(x) {
    if (!this.cursorEl) return;
    const rect = this.canvas.getBoundingClientRect();
    const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
    if (x === null || x < PAD_LEFT || x > PAD_LEFT + plotW) {
      this.cursorEl.hidden = true;
      return;
    }
    this.cursorEl.style.left = `${x}px`;
    this.cursorEl.hidden = false;
  }

  setColormap(name) {
    this.lut = buildLut(name);
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;
    const w = Math.max(100, Math.floor(rect.width));
    const h = Math.max(60, Math.floor(rect.height));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      const prev =
        this.canvas.width > 0 && this.canvas.height > 0
          ? this.ctx.getImageData(0, 0, this.canvas.width, this.canvas.height)
          : null;
      this.canvas.width = w;
      this.canvas.height = h;
      this.ctx.fillStyle = '#18181D';
      this.ctx.fillRect(0, 0, w, h);
      if (prev) this.ctx.putImageData(prev, 0, 0);
    }
  }

  clear() {
    this.ctx.fillStyle = '#18181D';
    this.ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
  }

  pushRow(bins, minDb, maxDb) {
    const w = this.canvas.width;
    const h = this.canvas.height;
    if (w <= PAD_LEFT + PAD_RIGHT || h <= 2 || !bins || bins.length === 0) return;

    const plotW = w - PAD_LEFT - PAD_RIGHT;
    if (h > 1) {
      this.ctx.drawImage(this.canvas, 0, 0, w, h - 1, 0, 1, w, h - 1);
    }

    if (!this.rowBuffer || this.rowBuffer.width !== plotW) {
      this.rowBuffer = this.ctx.createImageData(plotW, 1);
    }
    const imgData = this.rowBuffer;
    const data = imgData.data;
    const span = Math.max(15, maxDb - minDb);
    const n = bins.length;

    for (let px = 0; px < plotW; px += 1) {
      const startBin = Math.floor((px / plotW) * n);
      const endBin = Math.max(startBin + 1, Math.floor(((px + 1) / plotW) * n));
      let peakVal = -160;
      for (let b = startBin; b < endBin && b < n; b += 1) {
        if (bins[b] > peakVal) peakVal = bins[b];
      }
      const norm = Math.min(1, Math.max(0, (peakVal - minDb) / span));
      const lutIdx = Math.min(255, Math.max(0, Math.round(norm * 255))) * 3;
      const off = px * 4;
      data[off] = this.lut[lutIdx];
      data[off + 1] = this.lut[lutIdx + 1];
      data[off + 2] = this.lut[lutIdx + 2];
      data[off + 3] = 255;
    }

    this.ctx.fillStyle = '#18181D';
    this.ctx.fillRect(0, 0, PAD_LEFT, 1);
    this.ctx.fillRect(PAD_LEFT + plotW, 0, PAD_RIGHT, 1);
    this.ctx.putImageData(imgData, PAD_LEFT, 0);
  }
}
