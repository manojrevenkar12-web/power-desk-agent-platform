import { useQuery } from "@tanstack/react-query";
import { motion, useReducedMotion } from "motion/react";
import { type KeyboardEvent, useId, useMemo, useState } from "react";
import { api, type Interval } from "../../shared/api/client";
import { DATA_FIRST_DAY, DATA_LAST_DAY, DEFAULT_DAY, motionTokens, PRICE_BANDS, QUARTER_HOURS_PER_DAY, ZONES, type Zone } from "../../shared/theme/tokens";
import { ErrorState, Skeleton } from "../../shared/ui/states";

const VIEW_W = 960;
const VIEW_H = 160;
const BAR_W = VIEW_W / QUARTER_HOURS_PER_DAY;

export function priceColour(p: number): string {
  if (p < 0) return "var(--price-negative)";
  if (p < PRICE_BANDS.low) return "var(--price-low)";
  if (p < PRICE_BANDS.high) return "var(--price-mid)";
  if (p < PRICE_BANDS.scarce) return "var(--price-high)";
  return "var(--price-scarce)";
}

function fmt(p: number) {
  return p.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function longDay(day: string) {
  return new Date(`${day}T12:00:00`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

export function summarise(iv: Interval[]) {
  const lo = iv.reduce((a, b) => (b.da < a.da ? b : a));
  const hi = iv.reduce((a, b) => (b.da > a.da ? b : a));
  const negative = iv.filter((i) => i.da < 0).length;
  return { lo, hi, negativeHours: negative / 4 };
}

export function Strip({ intervals }: { intervals: Interval[] }) {
  const reduce = useReducedMotion();
  const [focus, setFocus] = useState<number | null>(null);
  const descId = useId();
  const { min, max } = useMemo(() => ({ min: Math.min(0, ...intervals.map((i) => i.da)), max: Math.max(1, ...intervals.map((i) => i.da)) }), [intervals]);
  const y = (p: number) => VIEW_H - ((p - min) / (max - min)) * VIEW_H;
  const zero = y(0);
  const s = summarise(intervals);
  const shown = focus === null ? null : intervals[focus];

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") setFocus((f) => Math.min(intervals.length - 1, (f ?? -1) + 1));
    else if (e.key === "ArrowLeft") setFocus((f) => Math.max(0, (f ?? intervals.length) - 1));
    else if (e.key === "Escape") setFocus(null);
    else return;
    e.preventDefault();
  };

  return (
    <figure className="strip">
      <div className="strip-readout" aria-live="polite">
        {shown ? (
          <>
            <span className="strip-time">{shown.at.slice(11)}</span>
            <span className="strip-price" style={{ color: priceColour(shown.da) }}>
              {fmt(shown.da)} EUR/MWh
            </span>
            <span className="strip-gen">
              solar {Math.round(shown.solar_mw / 1000)} GW, wind {Math.round(shown.wind_mw / 1000)} GW
            </span>
          </>
        ) : (
          <>
            <span className="strip-time">Low {s.lo.at.slice(11)}</span>
            <span className="strip-price">{fmt(s.lo.da)}</span>
            <span className="strip-time">High {s.hi.at.slice(11)}</span>
            <span className="strip-price">{fmt(s.hi.da)}</span>
            <span className="strip-gen">{s.negativeHours > 0 ? `${s.negativeHours} hours below zero` : "no negative prices"}</span>
          </>
        )}
      </div>
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
        preserveAspectRatio="none"
        className="strip-svg"
        role="img"
        aria-describedby={descId}
        tabIndex={0}
        onKeyDown={onKey}
        onMouseLeave={() => setFocus(null)}
        onBlur={() => setFocus(null)}
      >
        {intervals.map((iv, i) => {
          const top = Math.min(y(iv.da), zero);
          const h = Math.max(1, Math.abs(y(iv.da) - zero));
          return (
            <motion.rect
              key={iv.at}
              x={i * BAR_W}
              width={BAR_W - 1}
              y={top}
              height={h}
              fill={priceColour(iv.da)}
              opacity={focus === null || focus === i ? 1 : 0.45}
              style={{ transformBox: "fill-box", transformOrigin: iv.da < 0 ? "top" : "bottom" }}
              initial={reduce ? false : { scaleY: 0 }}
              animate={{ scaleY: 1 }}
              transition={{ duration: motionTokens.calm, ease: motionTokens.ease, delay: reduce ? 0 : (i / intervals.length) * motionTokens.stripReveal }}
              onMouseEnter={() => setFocus(i)}
            />
          );
        })}
        <line x1={0} x2={VIEW_W} y1={zero} y2={zero} className="strip-zero" />
      </svg>
      <figcaption id={descId} className="strip-axis">
        <span>00:00</span>
        <span>06:00</span>
        <span>12:00</span>
        <span>18:00</span>
        <span>24:00</span>
        <span className="visually-hidden">
          Day-ahead price by quarter hour. Lowest {fmt(s.lo.da)} EUR/MWh at {s.lo.at.slice(11)}, highest {fmt(s.hi.da)} at {s.hi.at.slice(11)}.
        </span>
      </figcaption>
    </figure>
  );
}

export function PriceStrip() {
  const [zone, setZone] = useState<Zone>("DE-LU");
  const [day, setDay] = useState(DEFAULT_DAY);
  const q = useQuery({ queryKey: ["day", zone, day], queryFn: () => api.marketDay(zone, day) });
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-head">
        <h1 id="hero-title" className="hero-title">
          {longDay(day)} in {zone}, quarter hour by quarter hour
        </h1>
        <div className="hero-controls">
          <label className="field-inline">
            <span>Zone</span>
            <select value={zone} onChange={(e) => setZone(e.target.value as Zone)}>
              {ZONES.map((z) => (
                <option key={z}>{z}</option>
              ))}
            </select>
          </label>
          <label className="field-inline">
            <span>Delivery day</span>
            <input type="date" min={DATA_FIRST_DAY} max={DATA_LAST_DAY} value={day} onChange={(e) => e.target.value && setDay(e.target.value)} />
          </label>
        </div>
      </div>
      {q.isPending ? <Skeleton lines={2} label="Loading the day's prices" /> : q.isError ? <ErrorState what="the day's prices" error={q.error} onRetry={() => q.refetch()} /> : <Strip intervals={q.data.intervals} />}
    </section>
  );
}
