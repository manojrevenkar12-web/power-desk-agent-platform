/** Motion and layout constants used from TypeScript. CSS sizes live in tokens.css. */
export const motionTokens = {
  quick: 0.14,
  calm: 0.32,
  stripReveal: 0.6, // the whole strip, left to right
  ease: [0.2, 0.8, 0.2, 1] as const,
};

export const QUARTER_HOURS_PER_DAY = 96;
export const DATA_FIRST_DAY = "2026-06-01";
export const DATA_LAST_DAY = "2026-09-30";
export const DEFAULT_DAY = "2026-08-12";
export const ZONES = ["DE-LU", "FR", "NL"] as const;
export type Zone = (typeof ZONES)[number];

/** Price thresholds for the strip's colour ramp, EUR/MWh. */
export const PRICE_BANDS = { low: 40, high: 100, scarce: 150 } as const;
