const PAD_LEFT = 52;
const PAD_RIGHT = 14;
const PAD_TOP = 14;
const PAD_BOTTOM = 24;

export { PAD_LEFT, PAD_RIGHT };

/**
 * Reduce `bins` to one value per pixel column, keeping the column maximum so that
 * narrow carriers stay visible when there are more FFT bins than pixels.
 */
export function columnMax(bins, columns, out) {
  const n = bins.length;
  const res = out && out.length === columns ? out : new Float32Array(columns);
  for (let px = 0; px < columns; px += 1) {
    const start = Math.floor((px / columns) * n);
    const end = Math.max(start + 1, Math.floor(((px + 1) / columns) * n));
    let peak = -Infinity;
    for (let b = start; b < end && b < n; b += 1) if (bins[b] > peak) peak = bins[b];
    res[px] = peak;
  }
  return res;
}

export class SpectrumCanvas {
  constructor(canvas, hoverEl, panBadgeEl, callbacks = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.hoverEl = hoverEl;
    this.panBadgeEl = panBadgeEl;

    this.callbacks = callbacks;
    this._rafPending = false;
    this._colLive = null;
    this._colPeak = null;

    this.bins = null;
    this.peakBins = null;
    this.peakHold = false;
    this.centerMhz = 98.0;
    this.startMhz = 97.0;
    this.stepMhz = 0.001;
    this.noiseFloor = -80;
    this.thresholdDb = -55;
    this.peaks = [];
    this.minDb = -105;
    this.maxDb = -5;
    this.autoRange = true;
    this._initializedRange = false;
    this.hoverX = null;

    this._dragMode = null; // null | 'threshold' | 'maybe-pan' | 'pan'
    this._dragStartX = 0;
    this._panDeltaMhz = 0;
    this._panOffsetPx = 0;

    this._bindEvents();
    this.resize();
  }

  _plotMetrics(rect) {
    const plotW = Math.max(10, rect.width - PAD_LEFT - PAD_RIGHT);
    const plotH = Math.max(10, rect.height - PAD_TOP - PAD_BOTTOM);
    const spanDb = Math.max(20, this.maxDb - this.minDb);
    const yForDb = (db) => PAD_TOP + (1 - (db - this.minDb) / spanDb) * plotH;
    const dbForY = (y) => this.minDb + (1 - (y - PAD_TOP) / plotH) * spanDb;
    return { plotW, plotH, spanDb, yForDb, dbForY };
  }

  _bindEvents() {
    window.addEventListener('resize', () => this.resize());
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(this.canvas.parentElement || this.canvas);
    }

    this.canvas.addEventListener('mousemove', (e) => {
      if (this._dragMode) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const { plotW, yForDb } = this._plotMetrics(rect);

      this.hoverX = x;
      if (this.callbacks.onHoverXChange) this.callbacks.onHoverXChange(x);

      const yThresh = yForDb(this.thresholdDb);
      const nearThresh = x >= PAD_LEFT && x <= PAD_LEFT + plotW && Math.abs(y - yThresh) <= 8;
      this.canvas.style.cursor = nearThresh ? 'ns-resize' : 'crosshair';

      this._renderHover();
      this.draw();
    });

    this.canvas.addEventListener('mouseleave', () => {
      if (this._dragMode) return;
      this.hoverX = null;
      if (this.callbacks.onHoverXChange) this.callbacks.onHoverXChange(null);
      if (this.hoverEl) this.hoverEl.hidden = true;
      this.draw();
    });

    this.canvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0 || !this.bins || this.bins.length < 2) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const { plotW, yForDb } = this._plotMetrics(rect);
      if (x < PAD_LEFT || x > PAD_LEFT + plotW) return;

      const yThresh = yForDb(this.thresholdDb);
      if (Math.abs(y - yThresh) <= 8) {
        this._dragMode = 'threshold';
        this.canvas.style.cursor = 'ns-resize';
      } else {
        this._dragMode = 'maybe-pan';
        this._dragStartX = x;
        this._panDeltaMhz = 0;
        this._panOffsetPx = 0;
      }
      e.preventDefault();
    });

    window.addEventListener('mousemove', (e) => {
      if (!this._dragMode) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const y = e.clientY - rect.top;
      const { plotW, dbForY } = this._plotMetrics(rect);

      if (this._dragMode === 'threshold') {
        const clamped = Math.max(-110, Math.min(0, Math.round(dbForY(y))));
        this.thresholdDb = clamped;
        if (this.callbacks.onThresholdInput) this.callbacks.onThresholdInput(clamped);
        this.draw();
        return;
      }

      const dx = x - this._dragStartX;
      if (this._dragMode === 'maybe-pan' && Math.abs(dx) > 6) {
        this._dragMode = 'pan';
        this.canvas.style.cursor = 'grabbing';
      }

      if (this._dragMode === 'pan' && this.bins) {
        const spanMhz = Math.max(1e-6, (this.bins.length - 1) * this.stepMhz);
        this._panOffsetPx = dx;
        this._panDeltaMhz = -(dx / plotW) * spanMhz;
        const previewFreq = Math.min(1766, Math.max(24, this.centerMhz + this._panDeltaMhz));
        if (this.panBadgeEl) {
          this.panBadgeEl.textContent = `→ ${previewFreq.toFixed(3)} MHz`;
          this.panBadgeEl.hidden = false;
        }
        this.draw();
      }
    });

    window.addEventListener('mouseup', (e) => {
      if (!this._dragMode) return;
      const mode = this._dragMode;
      this._dragMode = null;
      this.canvas.style.cursor = 'crosshair';
      if (this.panBadgeEl) this.panBadgeEl.hidden = true;

      if (mode === 'threshold') {
        if (this.callbacks.onThresholdCommit) {
          this.callbacks.onThresholdCommit(this.thresholdDb);
        }
        this.draw();
        return;
      }

      if (mode === 'pan') {
        const target = Math.min(1766, Math.max(24, this.centerMhz + this._panDeltaMhz));
        this._panDeltaMhz = 0;
        this._panOffsetPx = 0;
        if (this.callbacks.onTuneFreqMhz && Math.abs(target - this.centerMhz) > 0.001) {
          this.callbacks.onTuneFreqMhz(Number(target.toFixed(4)));
        }
        this.draw();
        return;
      }

      if (mode === 'maybe-pan' && this.bins && this.callbacks.onTuneFreqMhz) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
        const frac = Math.min(1, Math.max(0, (x - PAD_LEFT) / plotW));
        const freqMhz = this.startMhz + frac * (this.bins.length - 1) * this.stepMhz;
        this.callbacks.onTuneFreqMhz(Number(Math.min(1766, Math.max(24, freqMhz)).toFixed(4)));
      }
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

  setHoverX(x) {
    this.hoverX = x;
    this._renderHover();
    this.draw();
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (rect.width < 20 || rect.height < 20) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = Math.max(100, Math.floor(rect.width * dpr));
    const h = Math.max(80, Math.floor(rect.height * dpr));
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    this.draw();
  }

  setThreshold(db) {
    this.thresholdDb = db;
    this.draw();
  }

  setPeakHold(enabled) {
    this.peakHold = enabled;
    if (!enabled) this.peakBins = null;
    else if (this.bins) this.peakBins = new Float32Array(this.bins);
    this.draw();
  }

  resetPeak() {
    this.peakBins = this.bins ? new Float32Array(this.bins) : null;
    this.draw();
  }

  triggerAutoScale() {
    this.autoRange = true;
    if (!this.bins || this.bins.length === 0) return;
    let pMin = Infinity;
    let pMax = -Infinity;
    for (let i = 0; i < this.bins.length; i += 1) {
      if (this.bins[i] < pMin) pMin = this.bins[i];
      if (this.bins[i] > pMax) pMax = this.bins[i];
    }
    this.minDb = Math.max(-135, Math.floor((Math.min(this.noiseFloor - 12, pMin - 4)) / 5) * 5);
    this.maxDb = Math.min(10, Math.ceil((Math.max(pMax + 10, this.thresholdDb + 12)) / 5) * 5);
    if (this.maxDb - this.minDb < 35) this.maxDb = this.minDb + 35;
    this.draw();
  }

  updateFrame(frame, bins) {
    this.bins = bins;
    this.centerMhz = (frame.center_freq_hz || 98e6) / 1e6;
    this.startMhz = frame.freqs_start_mhz;
    this.stepMhz = frame.freqs_step_mhz;
    this.noiseFloor = frame.noise_floor_db;
    this.peaks = frame.peaks || [];

    if (this.peakHold) {
      if (!this.peakBins || this.peakBins.length !== bins.length) {
        this.peakBins = new Float32Array(bins);
      } else {
        for (let i = 0; i < bins.length; i += 1) {
          if (bins[i] > this.peakBins[i]) this.peakBins[i] = bins[i];
        }
      }
    }

    if (this.autoRange) {
      const targetMin = Math.max(-135, Math.floor((this.noiseFloor - 14) / 5) * 5);
      const targetMax = Math.min(
        10,
        Math.ceil((Math.max(frame.peak_power_db + 12, this.thresholdDb + 14)) / 5) * 5,
      );
      if (!this._initializedRange) {
        this.minDb = targetMin;
        this.maxDb = Math.max(targetMin + 35, targetMax);
        this._initializedRange = true;
      } else {
        this.minDb = this.minDb * 0.85 + targetMin * 0.15;
        this.maxDb = Math.max(this.minDb + 35, this.maxDb * 0.85 + targetMax * 0.15);
      }
    }

    this._renderHover();
    this.draw();
  }

  _renderHover() {
    if (!this.hoverEl) return;
    if (this.hoverX === null || !this.bins || this.bins.length === 0) {
      this.hoverEl.hidden = true;
      return;
    }
    const rect = this.canvas.getBoundingClientRect();
    const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
    if (this.hoverX < PAD_LEFT || this.hoverX > rect.width - PAD_RIGHT) {
      this.hoverEl.hidden = true;
      return;
    }
    const frac = (this.hoverX - PAD_LEFT) / plotW;
    const idx = Math.min(this.bins.length - 1, Math.max(0, Math.round(frac * (this.bins.length - 1))));
    const freq = this.startMhz + idx * this.stepMhz;
    const val = this.bins[idx];
    const snr = Math.max(0, val - this.noiseFloor);
    this.hoverEl.textContent = `${freq.toFixed(4)} MHz · ${val.toFixed(1)} dBFS · +${snr.toFixed(1)} dB`;
    this.hoverEl.hidden = false;
  }

  /** Schedule a repaint; multiple calls within one frame collapse into one. */
  draw() {
    if (this._rafPending) return;
    this._rafPending = true;
    requestAnimationFrame(() => {
      this._rafPending = false;
      this._paint();
    });
  }

  _paint() {
    const ctx = this.ctx;
    if (!ctx) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = this.canvas.width / dpr;
    const h = this.canvas.height / dpr;
    ctx.save();
    ctx.scale(dpr, dpr);

    ctx.fillStyle = '#18181D';
    ctx.fillRect(0, 0, w, h);

    const plotW = Math.max(10, w - PAD_LEFT - PAD_RIGHT);
    const plotH = Math.max(10, h - PAD_TOP - PAD_BOTTOM);
    const spanDb = Math.max(20, this.maxDb - this.minDb);
    const yForDb = (db) => PAD_TOP + (1 - (db - this.minDb) / spanDb) * plotH;

    // Horizontal dBFS grid
    ctx.strokeStyle = 'rgba(233, 230, 224, 0.10)';
    ctx.lineWidth = 1;
    ctx.fillStyle = '#9E9AA8';
    ctx.font = '500 11px "DM Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    const stepDb = spanDb > 80 ? 20 : 10;
    const firstTick = Math.ceil(this.minDb / stepDb) * stepDb;
    for (let db = firstTick; db <= this.maxDb; db += stepDb) {
      const y = Math.round(yForDb(db)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(PAD_LEFT + plotW, y);
      ctx.stroke();
      ctx.fillText(`${Math.round(db)}`, PAD_LEFT - 8, y);
    }

    // Vertical frequency grid
    const nBins = this.bins ? this.bins.length : 2048;
    const endMhz = this.startMhz + (nBins - 1) * this.stepMhz;
    const numCols = 6;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    for (let i = 0; i <= numCols; i += 1) {
      const frac = i / numCols;
      const x = Math.round(PAD_LEFT + frac * plotW) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, PAD_TOP);
      ctx.lineTo(x, PAD_TOP + plotH);
      ctx.stroke();
      const f = this.startMhz + frac * (endMhz - this.startMhz);
      ctx.fillText(f.toFixed(2), x, PAD_TOP + plotH + 6);
    }

    // Subtle center marker
    const xCenter = Math.round(PAD_LEFT + plotW * 0.5) + 0.5;
    ctx.save();
    ctx.strokeStyle = 'rgba(233, 230, 224, 0.18)';
    ctx.setLineDash([2, 4]);
    ctx.beginPath();
    ctx.moveTo(xCenter, PAD_TOP);
    ctx.lineTo(xCenter, PAD_TOP + plotH);
    ctx.stroke();
    ctx.restore();

    // Noise floor line
    const yFloor = yForDb(this.noiseFloor);
    if (yFloor >= PAD_TOP && yFloor <= PAD_TOP + plotH) {
      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = 'rgba(111, 208, 140, 0.55)';
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, yFloor);
      ctx.lineTo(PAD_LEFT + plotW, yFloor);
      ctx.stroke();
      ctx.restore();
    }

    // Detection threshold line (draggable handle)
    const yThresh = yForDb(this.thresholdDb);
    if (yThresh >= PAD_TOP && yThresh <= PAD_TOP + plotH) {
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = this._dragMode === 'threshold' ? '#FFE27A' : 'rgba(255, 92, 57, 0.90)';
      ctx.lineWidth = this._dragMode === 'threshold' ? 2 : 1.5;
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, yThresh);
      ctx.lineTo(PAD_LEFT + plotW, yThresh);
      ctx.stroke();

      ctx.setLineDash([]);
      ctx.fillStyle = this._dragMode === 'threshold' ? '#FFE27A' : '#FF5C39';
      ctx.fillRect(PAD_LEFT, yThresh - 9, 68, 16);
      ctx.fillStyle = '#1E1B2E';
      ctx.font = '700 10px "DM Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.fillText(`THR ${Math.round(this.thresholdDb)}`, PAD_LEFT + 5, yThresh - 1);
      ctx.restore();
    }

    if (this.bins && this.bins.length > 1) {
      const panShift = this._dragMode === 'pan' ? this._panOffsetPx : 0;
      ctx.save();
      ctx.beginPath();
      ctx.rect(PAD_LEFT, PAD_TOP, plotW, plotH);
      ctx.clip();

      // Peak Hold trace
      const columns = Math.max(2, Math.round(plotW));
      if (this.peakHold && this.peakBins && this.peakBins.length === this.bins.length) {
        this._colPeak = columnMax(this.peakBins, columns, this._colPeak);
        ctx.save();
        ctx.strokeStyle = 'rgba(255, 226, 122, 0.72)';
        ctx.lineWidth = 1.25;
        ctx.beginPath();
        for (let px = 0; px < columns; px += 1) {
          const y = Math.min(PAD_TOP + plotH, Math.max(PAD_TOP, yForDb(this._colPeak[px])));
          const drawX = PAD_LEFT + (px / (columns - 1)) * plotW + panShift;
          if (px === 0) ctx.moveTo(drawX, y);
          else ctx.lineTo(drawX, y);
        }
        ctx.stroke();
        ctx.restore();
      }

      // Live spectrum trace + gradient fill
      this._colLive = columnMax(this.bins, columns, this._colLive);
      ctx.beginPath();
      for (let px = 0; px < columns; px += 1) {
        const y = Math.min(PAD_TOP + plotH, Math.max(PAD_TOP, yForDb(this._colLive[px])));
        const drawX = PAD_LEFT + (px / (columns - 1)) * plotW + panShift;
        if (px === 0) ctx.moveTo(drawX, y);
        else ctx.lineTo(drawX, y);
      }
      ctx.strokeStyle = '#7CC4FF';
      ctx.lineWidth = 1.8;
      ctx.stroke();

      ctx.lineTo(PAD_LEFT + plotW + panShift, PAD_TOP + plotH);
      ctx.lineTo(PAD_LEFT + panShift, PAD_TOP + plotH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(124, 196, 255, 0.16)';
      ctx.fill();

      // Peak markers (top 3, non-overlapping)
      const spanMhz = Math.max(1e-6, endMhz - this.startMhz);
      const placedLabels = [];
      this.peaks.slice(0, 4).forEach((pk, rank) => {
        const frac = (pk.frequency_mhz - this.startMhz) / spanMhz;
        if (frac < 0 || frac > 1) return;
        const x = PAD_LEFT + frac * plotW + panShift;
        const y = Math.min(PAD_TOP + plotH, Math.max(PAD_TOP + 10, yForDb(pk.power_db)));
        ctx.fillStyle = rank === 0 ? '#FFE27A' : '#6FD08C';
        ctx.beginPath();
        ctx.arc(x, y, rank === 0 ? 4 : 3, 0, Math.PI * 2);
        ctx.fill();
        if (placedLabels.every((lx) => Math.abs(lx - x) > 58)) {
          placedLabels.push(x);
          ctx.font = '500 11px "DM Mono", monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText(`${pk.frequency_mhz.toFixed(3)}`, x, Math.max(PAD_TOP + 11, y - 5));
        }
      });

      ctx.restore();
    }

    // Hover crosshair
    if (this.hoverX !== null && this.hoverX >= PAD_LEFT && this.hoverX <= PAD_LEFT + plotW) {
      ctx.save();
      ctx.strokeStyle = 'rgba(255, 226, 122, 0.55)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(this.hoverX, PAD_TOP);
      ctx.lineTo(this.hoverX, PAD_TOP + plotH);
      ctx.stroke();
      ctx.restore();
    }

    ctx.restore();
  }
}
