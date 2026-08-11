export interface Tool {
  slug: string;
  name: string;
  description: string;
  icon: string;
  status: string; // "live" | "soon"
  sort: number;
  url?: string | null; // external tools open this link; internal tools route by slug
}

/** Percentages are fractions (0.07 = 7%), matching the spreadsheet. */
export interface RoasInput {
  selling_price: number;
  cogs: number;
  psp_fee: number;
  vat: number;
  other_fees: number;
  min_margin: number;
  target_margin: number;
}

export interface RoasResult {
  multiplier: number | null;
  contribution: number;
  roas_breakeven: number | null;
  roas_at_min_margin: number | null;
  roas_at_target_margin: number | null;
  breakeven_cpa: number | null;
  target_cpa: number | null;
  warning: string | null;
}

/** Product preset row from the reference Google Sheet. */
export interface SheetProduct {
  name: string;
  psp_fee: number;
  vat: number;
  other_fees: number;
  min_margin: number;
  target_margin: number;
  cogs: number;
  selling_price: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    let message = `API ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (body.detail) message = String(body.detail);
    } catch {
      // non-JSON error body — keep the status message
    }
    throw new Error(message);
  }
  return res.json() as Promise<T>;
}

export const fetchTools = (signal?: AbortSignal): Promise<Tool[]> =>
  request<Tool[]>("/api/tools", { signal });

export const fetchSheetProducts = (signal?: AbortSignal): Promise<SheetProduct[]> =>
  request<SheetProduct[]>("/api/roas/products", { signal });

/** Append the offer as a new row on the reference sheet (needs Editor access). */
export const saveSheetProduct = (product: SheetProduct): Promise<{ row: number }> =>
  request<{ row: number }>("/api/roas/products", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(product),
  });

/** USD-based exchange rates for the supported currencies. */
export const fetchFxRates = (signal?: AbortSignal): Promise<Record<string, number>> =>
  request<{ base: string; rates: Record<string, number> }>("/api/fx", { signal }).then(
    (r) => r.rates,
  );

export const calcRoas = (input: RoasInput, signal?: AbortSignal): Promise<RoasResult> =>
  request<RoasResult>("/api/roas/breakeven", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
    signal,
  });
