/**
 * Pure helpers of the AI planner screens (no React, no network) — unit-tested with `node --test`.
 *
 * The server's calculator is the only source of totals. `previewLine` exists so the item editor can show
 * a live "≈" figure while the user types; the saved number always comes back from the API.
 * Money is handled as integer tiyin (BigInt) — never as floating point.
 */

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger";

export const CATEGORY_LABELS = {
  VENUE: "To'yxona / joy",
  FOOD: "Dasturxon / ovqat",
  PHOTO_VIDEO: "Foto va video",
  HOST_DJ: "Boshlovchi / DJ",
  ARTISTS: "Xonandalar / artistlar",
  DECOR: "Bezak",
  CAKE_EXTRAS: "Tort, ichimliklar, qo'shimchalar",
  TRANSPORT: "Transport",
  INVITATIONS_OTHER: "Taklifnomalar va boshqalar",
  CONTINGENCY: "Kutilmagan xarajatlar zaxirasi",
} as const;

export const ITEM_CATEGORIES = Object.keys(CATEGORY_LABELS).filter((c) => c !== "CONTINGENCY") as Exclude<
  keyof typeof CATEGORY_LABELS,
  "CONTINGENCY"
>[];

export const EVENT_TYPE_LABELS = {
  TOY: "To'y",
  NIKOH: "Nikoh",
  SUNNAT: "Sunnat to'yi",
  BIRTHDAY: "Tug'ilgan kun",
  ANNIVERSARY: "Yubiley",
  CORPORATE: "Korporativ",
  OTHER: "Boshqa",
} as const;

export const STYLE_LABELS = { ECONOMY: "Tejamkor", STANDARD: "Standart", PREMIUM: "Premium", CUSTOM: "O'zim belgilayman" } as const;

export const UNIT_LABELS = {
  EVENT: "marosim",
  PERSON: "kishi",
  PIECE: "dona",
  HOUR: "soat",
  SET: "to'plam",
  SERVICE: "xizmat",
} as const;

export const PRICE_STATUS: Record<"VERIFIED" | "ESTIMATED" | "PENDING", { label: string; tone: Tone; hint: string }> = {
  VERIFIED: { label: "Platforma narxi", tone: "success", hint: "Narx platforma bazasidan olingan (tekshirilgan vaqti ko'rsatilgan)." },
  ESTIMATED: { label: "Taxminiy", tone: "warning", hint: "Bu aniq narx emas — taxmin." },
  PENDING: { label: "Narx noma'lum", tone: "neutral", hint: "Narxni xizmat ko'rsatuvchidan so'rang." },
};

export const SOURCE_LABELS = {
  PLATFORM_SERVICE: "Platformadagi xizmat",
  USER_INPUT: "Siz kiritgansiz",
  AI_ESTIMATE: "AI taxmini",
  MANUAL: "Qo'lda",
} as const;

export const BUDGET_STATE: Record<"NO_ITEMS" | "NO_BUDGET" | "WITHIN" | "AT_RISK" | "OVER", { label: string; tone: Tone; hint: string }> = {
  NO_ITEMS: { label: "Hisob yo'q", tone: "neutral", hint: "Hali birorta xarajat bandi qo'shilmagan." },
  NO_BUDGET: { label: "Byudjet kiritilmagan", tone: "neutral", hint: "Umumiy byudjetni kiriting — qolgan summa hisoblanadi." },
  WITHIN: { label: "Byudjet ichida", tone: "success", hint: "Rejalashtirilgan xarajatlar byudjetdan oshmaydi." },
  AT_RISK: { label: "Oshib ketishi mumkin", tone: "warning", hint: "Narx oralig'ining yuqori chegarasi byudjetdan oshadi." },
  OVER: { label: "Byudjetdan oshgan", tone: "danger", hint: "Xarajatlar byudjetdan ko'p — qisqartirish takliflarini ko'ring." },
};

// ------------------------------------------------------------------- money
/** "1 500 000,50" / "1500000.5" → 150000050 tiyin; `null` for anything that is not a non-negative amount. */
export function parseMoney(input: string | number | null | undefined): bigint | null {
  if (input === null || input === undefined) return null;
  const text = String(input).replace(/[\s ]/g, "").replace(",", ".");
  if (!/^\d+(\.\d{1,2})?$/.test(text)) return null;
  const [whole, frac = ""] = text.split(".");
  return BigInt(whole) * BigInt(100) + BigInt((frac + "00").slice(0, 2));
}

/** 150000050 tiyin → "1500000.50" (the API's decimal string). */
export function toDecimalString(tiyin: bigint): string {
  const sign = tiyin < BigInt(0) ? "-" : "";
  const abs = tiyin < BigInt(0) ? -tiyin : tiyin;
  return `${sign}${abs / BigInt(100)}.${String(abs % BigInt(100)).padStart(2, "0")}`;
}

/** "1500000.50" → "1 500 000,50 so'm"; whole amounts without the fraction. */
export function formatSum(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const tiyin = parseMoney(value.startsWith("-") ? value.slice(1) : value);
  if (tiyin === null) return "—";
  const whole = String(tiyin / BigInt(100)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const frac = tiyin % BigInt(100);
  return `${value.startsWith("-") ? "−" : ""}${whole}${frac ? `,${String(frac).padStart(2, "0")}` : ""} so'm`;
}

export function formatRange(min: string, max: string): string {
  return min === max ? formatSum(min) : `${formatSum(min)} – ${formatSum(max)}`;
}

export interface LineInput {
  unitPrice: string;
  unitPriceMax?: string;
  quantity: string;
  perGuest: boolean;
  guests: number | null;
  included: boolean;
  active: boolean;
}

/** Live "≈" preview of one line while typing — mirrors the server rule; `null` when the input is not valid yet. */
export function previewLine(line: LineInput): { min: string; max: string } | null {
  const low = parseMoney(line.unitPrice);
  const high = line.unitPriceMax ? parseMoney(line.unitPriceMax) : low;
  if (low === null || high === null || high < low) return null;
  if (!line.active || line.included) return { min: "0.00", max: "0.00" };
  let qty: bigint | null;
  if (line.perGuest) qty = line.guests && line.guests > 0 ? BigInt(line.guests) * BigInt(100) : null;
  else qty = parseMoney(line.quantity);
  if (qty === null || qty <= BigInt(0)) return null;
  // (tiyin × qty-in-hundredths) / 100, rounded half-up like the server.
  const round = (v: bigint) => (v * qty + BigInt(50)) / BigInt(100);
  return { min: toDecimalString(round(low)), max: toDecimalString(round(high)) };
}

// ------------------------------------------------------------- validation
export interface PlanFormValues {
  title: string;
  guest_count: string;
  total_budget: string;
  event_date: string;
  reserve_percent: string;
}

export function validatePlanForm(values: PlanFormValues, today: string): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.title.trim()) errors.title = "Reja nomini kiriting.";
  if (values.guest_count) {
    const n = Number(values.guest_count);
    if (!Number.isInteger(n) || n < 1 || n > 10000) errors.guest_count = "Mehmonlar soni 1 dan 10 000 gacha bo'lishi kerak.";
  }
  if (values.total_budget && parseMoney(values.total_budget) === null) errors.total_budget = "Byudjet manfiy bo'lmagan son bo'lishi kerak.";
  if (values.reserve_percent) {
    const r = Number(values.reserve_percent);
    if (!Number.isFinite(r) || r < 0 || r > 30) errors.reserve_percent = "Zaxira 0–30% oralig'ida bo'lishi kerak.";
  }
  if (values.event_date && !/^\d{4}-\d{2}-\d{2}$/.test(values.event_date)) errors.event_date = "Sanani tanlang.";
  else if (values.event_date && values.event_date < today) errors.event_date = "O'tgan sana tanlandi — rejangiz uchun to'g'ri sanani kiriting.";
  return errors;
}

// ---------------------------------------------------------- chat UI state
export type ChatBlock =
  | { kind: "ready" }
  | { kind: "disabled" | "maintenance" | "unconfigured" | "limit" | "provider" | "offline"; title: string; message: string; retry: boolean };

/** Maps an API error code (or the status endpoint's `reason`) to what the chat shows. */
export function chatBlockFor(code: string | null | undefined, message?: string | null): ChatBlock {
  switch (code) {
    case null:
    case undefined:
    case "":
      return { kind: "ready" };
    case "ai_disabled":
      return { kind: "disabled", title: "AI maslahatchi vaqtincha o'chirilgan", message: "Reja va byudjetni qo'lda davom ettirishingiz mumkin.", retry: false };
    case "ai_maintenance":
      return { kind: "maintenance", title: "Texnik ishlar", message: message || "AI maslahatchi tez orada qaytadi.", retry: false };
    case "ai_not_configured":
      return { kind: "unconfigured", title: "AI maslahatchi vaqtincha mavjud emas", message: "Reja, byudjet kalkulyatori va bronlar odatdagidek ishlaydi.", retry: false };
    case "ai_daily_limit":
    case "ai_global_limit":
    case "ai_token_budget":
    case "throttled":
      return { kind: "limit", title: "Limit tugadi", message: message || "Birozdan so'ng qayta urinib ko'ring.", retry: code === "throttled" };
    case "network_error":
      return { kind: "offline", title: "Internet aloqasi yo'q", message: "Aloqa tiklangach xabarni qayta yuboring.", retry: true };
    default:
      return { kind: "provider", title: "AI javob bera olmadi", message: message || "Qayta urinib ko'ring.", retry: true };
  }
}

/** Human labels for the server's validation notes on an AI reply. */
export const NOTE_LABELS: Record<string, string> = {
  unknown_service_dropped: "AI platformada yo'q xizmatni tilga oldi — u olib tashlandi.",
  item_dropped_invalid: "Noto'g'ri qiymatli taxmin olib tashlandi.",
  included_in_package_dropped: "To'yxona paketiga kirgan xizmat qayta qo'shilmadi.",
  invalid_guest_count: "Mehmonlar soni noto'g'ri tushunildi — e'tiborsiz qoldirildi.",
  invalid_budget: "Byudjet noto'g'ri tushunildi — e'tiborsiz qoldirildi.",
  invalid_date: "Sana noto'g'ri tushunildi — e'tiborsiz qoldirildi.",
};
