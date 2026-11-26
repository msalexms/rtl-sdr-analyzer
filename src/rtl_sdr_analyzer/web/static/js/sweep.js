import { columnMax, PAD_LEFT, PAD_RIGHT } from './spectrum.js';

const PAD_TOP = 18;
const PAD_BOTTOM = 26;

export class SweepCanvas {
  constructor(canvas, hoverEl, onSelectFreqMhz = null) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.hoverEl = hoverEl;
    this.onSelectFreqMhz = onSelectFreqMhz;
    this.result = null;
    this.hoverX = null;

    window.addEventListener('resize', () => this.resize());
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver(() => this.resize());
      this._ro.observe(this.canvas.parentElement || this.canvas);
    }

    this.canvas.addEventListener('mousemove', (e) => {
      const rect = this.canvas.getBoundingClientRect();
      this.hoverX = e.clientX - rect.left;
      this._updateHover();
      this.draw();
    });
    this.canvas.addEventListener('mouseleave', () => {
      this.hoverX = null;
      if (this.hoverEl) this.hoverEl.hidden = true;
      this.draw();
    });
    this.canvas.addEventListener('click', (e) => {
      if (!this.onSelectFreqMhz || !this.result || !this.result.freqs_mhz?.length) return;
      const rect = this.canvas.getBoundingClientRect();
      const x = e.clientX - rect.left;
      const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
      if (x < PAD_LEFT || x > rect.width - PAD_RIGHT) return;
      const frac = Math.min(1, Math.max(0, (x - PAD_LEFT) / plotW));
      const f0 = this.result.freqs_mhz[0];
      const f1 = this.result.freqs_mhz[this.result.freqs_mhz.length - 1];
      const freq = f0 + frac * (f1 - f0);
      this.onSelectFreqMhz(Number(freq.toFixed(3)));
    });
    this.resize();
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

  setResult(result) {
    this.result = result;
    this.draw();
  }

  _updateHover() {
    if (!this.hoverEl || this.hoverX === null || !this.result || !this.result.freqs_mhz.length) return;
    const rect = this.canvas.getBoundingClientRect();
    const plotW = Math.max(1, rect.width - PAD_LEFT - PAD_RIGHT);
    if (this.hoverX < PAD_LEFT || this.hoverX > rect.width - PAD_RIGHT) {
      this.hoverEl.hidden = true;
      return;
    }
    const frac = (this.hoverX - PAD_LEFT) / plotW;
    const idx = Math.min(
      this.result.freqs_mhz.length - 1,
      Math.max(0, Math.round(frac * (this.result.freqs_mhz.length - 1))),
    );
    const f = this.result.freqs_mhz[idx];
    const p = this.result.power_db[idx];
    this.hoverEl.textContent = `${f.toFixed(3)} MHz · ${p.toFixed(1)} dBFS`;
    this.hoverEl.hidden = false;
  }

  draw() {
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

    const freqs = this.result ? this.result.freqs_mhz : [];
    const powers = this.result ? this.result.power_db : [];

    let minDb = -105;
    let maxDb = -10;
    if (powers.length > 0) {
      let lo = Infinity;
      let hi = -Infinity;
      for (let i = 0; i < powers.length; i += 1) {
        if (powers[i] < lo) lo = powers[i];
        if (powers[i] > hi) hi = powers[i];
      }
      minDb = Math.floor((lo - 5) / 5) * 5;
      maxDb = Math.ceil((hi + 10) / 5) * 5;
      if (maxDb - minDb < 35) maxDb = minDb + 35;
    }
    const spanDb = Math.max(20, maxDb - minDb);
    const yForDb = (db) => PAD_TOP + (1 - (db - minDb) / spanDb) * plotH;

    // Grid
    ctx.strokeStyle = 'rgba(233, 230, 224, 0.10)';
    ctx.fillStyle = '#9E9AA8';
    ctx.font = '500 11px "DM Mono", monospace';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    const stepDb = spanDb > 70 ? 20 : 10;
    for (let db = Math.ceil(minDb / stepDb) * stepDb; db <= maxDb; db += stepDb) {
      const y = Math.round(yForDb(db)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(PAD_LEFT, y);
      ctx.lineTo(PAD_LEFT + plotW, y);
      ctx.stroke();
      ctx.fillText(`${Math.round(db)}`, PAD_LEFT - 8, y);
    }

    if (freqs.length > 1) {
      const f0 = freqs[0];
      const f1 = freqs[freqs.length - 1];
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      for (let i = 0; i <= 6; i += 1) {
        const frac = i / 6;
        const x = Math.round(PAD_LEFT + frac * plotW) + 0.5;
        ctx.beginPath();
        ctx.moveTo(x, PAD_TOP);
        ctx.lineTo(x, PAD_TOP + plotH);
        ctx.stroke();
        ctx.fillText((f0 + frac * (f1 - f0)).toFixed(1), x, PAD_TOP + plotH + 6);
      }

      const columns = Math.max(2, Math.round(plotW));
      const cols = columnMax(powers, columns);
      ctx.beginPath();
      for (let px = 0; px < columns; px += 1) {
        const y = Math.min(PAD_TOP + plotH, Math.max(PAD_TOP, yForDb(cols[px])));
        const x = PAD_LEFT + (px / (columns - 1)) * plotW;
        if (px === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.strokeStyle = '#6FD08C';
      ctx.lineWidth = 1.8;
      ctx.stroke();
      ctx.lineTo(PAD_LEFT + plotW, PAD_TOP + plotH);
      ctx.lineTo(PAD_LEFT, PAD_TOP + plotH);
      ctx.closePath();
      ctx.fillStyle = 'rgba(111, 208, 140, 0.16)';
      ctx.fill();

      const fSpan = Math.max(1e-6, f1 - f0);
      const placed = [];
      (this.result.peaks || []).slice(0, 10).forEach((pk) => {
        const x = PAD_LEFT + ((pk.frequency_mhz - f0) / fSpan) * plotW;
        const y = Math.min(PAD_TOP + plotH, Math.max(PAD_TOP + 12, yForDb(pk.power_db)));
        ctx.fillStyle = '#FFE27A';
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
        if (placed.every((px) => Math.abs(px - x) > 54)) {
          placed.push(x);
          ctx.font = '500 10.5px "DM Mono", monospace';
          ctx.textAlign = 'center';
          ctx.textBaseline = 'bottom';
          ctx.fillText(pk.frequency_mhz.toFixed(2), x, Math.max(PAD_TOP + 11, y - 5));
        }
      });
    } else {
      ctx.fillStyle = '#9E9AA8';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.font = '500 13px "DM Mono", monospace';
      ctx.fillText('—', PAD_LEFT + plotW / 2, PAD_TOP + plotH / 2);
    }

    if (this.hoverX !== null && this.hoverX >= PAD_LEFT && this.hoverX <= PAD_LEFT + plotW) {
      ctx.strokeStyle = 'rgba(255, 226, 122, 0.55)';
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(this.hoverX, PAD_TOP);
      ctx.lineTo(this.hoverX, PAD_TOP + plotH);
      ctx.stroke();
    }

    ctx.restore();
  }
}
