import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from "react";
import {
  calcRoas,
  fetchFxRates,
  fetchSheetProducts,
  saveSheetProduct,
  type RoasInput,
  type RoasResult,
  type SheetProduct,
} from "../api";
import { useReveal } from "../useReveal";

const CURRENCIES = ["EUR", "USD", "GBP", "CHF", "CAD", "AUD", "SEK", "AED"];
const CUSTOM = "__custom__";

/** 0.07 → "7", 0.155 → "15.5" */
const pctStr = (v: number) => String(Number((v * 100).toFixed(2)));

interface Fields {
  price: string;
  psp: string;
  vat: string;
  other: string;
  min: string;
  target: string;
}

/** One COGS line: base product or an upsell, always in USD. */
interface CogsLine {
  id: number;
  label: string;
  amount: string;
}

/** Sheet row 2 as the landing example: 2 Legging UK + Sleeve. */
const DEFAULTS: Fields = {
  price: "53.55",
  psp: "7",
  vat: "0",
  other: "1",
  min: "15",
  target: "20",
};

function toInput(f: Fields, cogs: number | null): RoasInput | null {
  const n = (s: string) => Number(s.replace(",", "."));
  const price = n(f.price);
  const pct = [f.psp, f.vat, f.other, f.min, f.target].map((s) => (s === "" ? 0 : n(s) / 100));
  if (!Number.isFinite(price) || price <= 0) return null;
  if (cogs === null) return null;
  if (pct.some((p) => !Number.isFinite(p) || p < 0 || p >= 1)) return null;
  const [psp_fee, vat, other_fees, min_margin, target_margin] = pct;
  return { selling_price: price, cogs, psp_fee, vat, other_fees, min_margin, target_margin };
}

function Field({
  label,
  children,
  unit,
  suffix,
}: {
  label: string;
  children: ReactNode;
  unit?: string;
  suffix?: string;
}) {
  return (
    <label className="field">
      <span className="field-name">{label}</span>
      <span className="control">
        {unit && <span className="unit">{unit}</span>}
        {children}
        {suffix && <span className="unit unit--suffix">{suffix}</span>}
      </span>
    </label>
  );
}

export function RoasPage() {
  const [fields, setFields] = useState<Fields>(DEFAULTS);
  const [lines, setLines] = useState<CogsLine[]>([{ id: 0, label: "", amount: "13.80" }]);
  const nextId = useRef(1);
  const [currency, setCurrency] = useState("USD");
  const [product, setProduct] = useState("");
  const [presets, setPresets] = useState<SheetProduct[]>([]);
  const [rates, setRates] = useState<Record<string, number> | null>(null);
  const [result, setResult] = useState<RoasResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("loading");
  const ref = useReveal<HTMLDivElement>();

  // Sum of the COGS lines (USD). Empty amounts count as 0; a garbage amount
  // invalidates the whole input rather than silently miscounting.
  const cogsTotal = useMemo(() => {
    let sum = 0;
    for (const l of lines) {
      const s = l.amount.trim();
      if (s === "") continue;
      const n = Number(s.replace(",", "."));
      if (!Number.isFinite(n) || n < 0) return null;
      sum += n;
    }
    return sum;
  }, [lines]);

  // COGS is entered in USD; the calculation needs both sides in the display
  // currency, so convert COGS with the USD-based cross rate at calc time.
  const fxBlocked = currency !== "USD" && !rates?.[currency];
  const input = useMemo(() => {
    const base = toInput(fields, cogsTotal);
    if (!base || currency === "USD") return base;
    const rate = rates?.[currency];
    if (!rate) return null;
    return { ...base, cogs: base.cogs * rate };
  }, [fields, cogsTotal, currency, rates]);

  useEffect(() => {
    const ctrl = new AbortController();
    // preset picker and FX conversion are optional — failures just disable them
    fetchSheetProducts(ctrl.signal).then(setPresets).catch(() => {});
    fetchFxRates(ctrl.signal).then(setRates).catch(() => {});
    return () => ctrl.abort();
  }, []);

  const changeCurrency = (next: string) => {
    // selling price follows the display currency; COGS stays in USD
    if (rates?.[currency] && rates[next]) {
      const factor = rates[next] / rates[currency];
      const conv = (s: string) => {
        const n = Number(s.replace(",", "."));
        return s.trim() !== "" && Number.isFinite(n) ? (n * factor).toFixed(2) : s;
      };
      setFields((f) => ({ ...f, price: conv(f.price) }));
    }
    setCurrency(next);
  };

  const loadPreset = (name: string) => {
    setProduct(name === CUSTOM ? "" : name);
    const p = presets.find((x) => x.name === name);
    if (!p) return;
    setFields({
      price: p.selling_price.toFixed(2),
      psp: pctStr(p.psp_fee),
      vat: pctStr(p.vat),
      other: pctStr(p.other_fees),
      min: pctStr(p.min_margin),
      target: pctStr(p.target_margin),
    });
    // "3 legging UK + sleeve + patch" → one line per component. The sheet only
    // knows the total COGS, so it lands on line 1; the rest start empty.
    const parts = p.name.split("+").map((s) => s.trim()).filter(Boolean);
    setLines(
      (parts.length ? parts : [p.name]).map((label, i) => ({
        id: nextId.current++,
        label,
        amount: i === 0 ? p.cogs.toFixed(2) : "",
      })),
    );
  };

  const setLine = (id: number, patch: Partial<Omit<CogsLine, "id">>) =>
    setLines((ls) => ls.map((l) => (l.id === id ? { ...l, ...patch } : l)));
  const addLine = () =>
    setLines((ls) => [...ls, { id: nextId.current++, label: "", amount: "" }]);
  const removeLine = (id: number) =>
    setLines((ls) => (ls.length > 1 ? ls.filter((l) => l.id !== id) : ls));

  // Save the current offer as a new sheet row; it then shows up as a preset.
  const [offerName, setOfferName] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);
  const suggestedName =
    lines.map((l) => l.label.trim()).filter(Boolean).join(" + ") || "Custom offer";

  const saveOffer = () => {
    const base = toInput(fields, cogsTotal); // unconverted: sheet keeps USD COGS
    if (!base || saveState === "saving") return;
    setSaveState("saving");
    setSaveError(null);
    saveSheetProduct({
      name: offerName.trim() || suggestedName,
      psp_fee: base.psp_fee,
      vat: base.vat,
      other_fees: base.other_fees,
      min_margin: base.min_margin,
      target_margin: base.target_margin,
      cogs: base.cogs,
      selling_price: base.selling_price,
    })
      .then(() => {
        setSaveState("done");
        window.setTimeout(() => setSaveState("idle"), 2500);
        return fetchSheetProducts().then(setPresets).catch(() => {});
      })
      .catch((e: unknown) => {
        setSaveState("error");
        setSaveError(e instanceof Error ? e.message : "Saving failed.");
      });
  };

  // Explicit calculation: results update on CALCULATE ROAS (and once on load),
  // and dim as soon as any input drifts from the last computed set.
  const [dirty, setDirty] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const didInit = useRef(false);

  const calcNow = () => {
    if (!input) return;
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setState("loading");
    calcRoas(input, ctrl.signal)
      .then((r) => {
        setResult(r);
        setState("ok");
        setDirty(false);
      })
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setState("error");
      });
  };

  useEffect(() => {
    setDirty(true);
    if (!input) {
      setState("idle");
    } else if (!didInit.current) {
      didInit.current = true;
      calcNow();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [input]);

  const set =
    (k: keyof Fields) =>
    (e: ChangeEvent<HTMLInputElement>) =>
      setFields((f) => ({ ...f, [k]: e.target.value }));

  const money = useMemo(
    () => new Intl.NumberFormat(undefined, { style: "currency", currency }),
    [currency],
  );
  const symbol = useMemo(
    () => money.formatToParts(0).find((p) => p.type === "currency")?.value ?? currency,
    [money, currency],
  );
  const fm = (v: number | null | undefined) => (v == null ? "—" : money.format(v));
  const fx = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));

  const band = useMemo(() => {
    if (
      result?.roas_breakeven == null ||
      result.roas_at_min_margin == null ||
      result.roas_at_target_margin == null
    )
      return null;
    const be = result.roas_breakeven;
    const lo = result.roas_at_min_margin;
    const hi = result.roas_at_target_margin;
    const start = be * 0.9;
    const end = hi * 1.12;
    const pos = (v: number) => ((v - start) / (end - start)) * 100;
    return { be: pos(be), lo: pos(lo), hi: pos(hi) };
  }, [result]);

  const stale = state !== "ok" || dirty;

  return (
    <div ref={ref} className="page">
      <a className="backlink reveal" href="#/">
        ← All tools
      </a>

      <header className="tool-head reveal" style={{ transitionDelay: "60ms" }}>
        <p className="eyebrow">TOOL 01 — MEDIA BUYING</p>
        <h1>
          ROAS Calculator
          {product && <span className="for-product"> · {product}</span>}
        </h1>
        <p className="lede">
          Break-even and target return on ad spend from price, COGS, fees and margin goals.
        </p>
      </header>

      <div className="tool-grid">
        <section className="shell reveal" style={{ transitionDelay: "120ms" }} aria-label="Inputs">
          <div className="core form">
            <div className="grid-2">
              <Field label={presets.length ? "Product — from sheet" : "Product — optional"}>
                {presets.length ? (
                  <select
                    value={product || CUSTOM}
                    onChange={(e: ChangeEvent<HTMLSelectElement>) => loadPreset(e.target.value)}
                  >
                    <option value={CUSTOM}>Custom…</option>
                    {presets.map((p) => (
                      <option key={p.name} value={p.name}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={product}
                    onChange={(e) => setProduct(e.target.value)}
                    placeholder="2 Legging UK + Sleeve"
                  />
                )}
              </Field>
              <Field label="Currency">
                <select
                  value={currency}
                  onChange={(e: ChangeEvent<HTMLSelectElement>) => changeCurrency(e.target.value)}
                >
                  {CURRENCIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </Field>
            </div>

            <div className="grid-2">
              <Field label="Selling price" unit={symbol}>
                <input type="number" min="0" step="0.01" value={fields.price} onChange={set("price")} />
              </Field>
              <Field label="COGS total — USD" unit="$">
                <input type="text" readOnly tabIndex={-1} value={cogsTotal?.toFixed(2) ?? "—"} />
              </Field>
            </div>

            <p className="group-label group-label--row">
              COGS lines — USD, product + upsells
              <span className="chip chip--exp">EXPERIMENTAL</span>
            </p>
            {lines.map((l, i) => (
              <div className="cogs-line" key={l.id}>
                <span className="control control--label">
                  <input
                    type="text"
                    value={l.label}
                    placeholder={i === 0 ? "Base product" : "Upsell"}
                    onChange={(e) => setLine(l.id, { label: e.target.value })}
                  />
                </span>
                <span className="control control--amount">
                  <span className="unit">$</span>
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    value={l.amount}
                    placeholder="0.00"
                    onChange={(e) => setLine(l.id, { amount: e.target.value })}
                  />
                </span>
                <button
                  type="button"
                  className="line-x"
                  onClick={() => removeLine(l.id)}
                  disabled={lines.length === 1}
                  aria-label={`Remove line ${l.label || i + 1}`}
                >
                  ×
                </button>
              </div>
            ))}
            <button type="button" className="add-line" onClick={addLine}>
              + Add upsell
            </button>

            <div className="save-row">
              <span className="control control--label">
                <input
                  type="text"
                  value={offerName}
                  placeholder={suggestedName}
                  onChange={(e) => setOfferName(e.target.value)}
                  aria-label="Offer name for the sheet"
                />
              </span>
              <button
                type="button"
                className="add-line save-btn"
                onClick={saveOffer}
                disabled={saveState === "saving" || !toInput(fields, cogsTotal)}
              >
                {saveState === "saving"
                  ? "SAVING…"
                  : saveState === "done"
                    ? "ADDED ✓"
                    : "ADD TO SHEET"}
              </button>
            </div>
            {saveState === "error" && saveError && (
              <div className="banner banner--danger">{saveError}</div>
            )}

            <p className="group-label">Fees — % of price</p>
            <div className="grid-3">
              <Field label="PSP" suffix="%">
                <input type="number" min="0" step="0.1" value={fields.psp} onChange={set("psp")} />
              </Field>
              <Field label="VAT" suffix="%">
                <input type="number" min="0" step="0.1" value={fields.vat} onChange={set("vat")} />
              </Field>
              <Field label="Other" suffix="%">
                <input type="number" min="0" step="0.1" value={fields.other} onChange={set("other")} />
              </Field>
            </div>

            <p className="group-label">Net margin goals — % of price</p>
            <div className="grid-2">
              <Field label="Minimum" suffix="%">
                <input type="number" min="0" step="1" value={fields.min} onChange={set("min")} />
              </Field>
              <Field label="Target" suffix="%">
                <input type="number" min="0" step="1" value={fields.target} onChange={set("target")} />
              </Field>
            </div>

            <button
              type="button"
              className="calc-btn"
              onClick={calcNow}
              disabled={!input || state === "loading"}
            >
              {state === "loading" ? "CALCULATING…" : "CALCULATE ROAS"}
            </button>
          </div>
        </section>

        <section
          className={`results reveal${stale ? " results--stale" : ""}`}
          style={{ transitionDelay: "180ms" }}
          aria-live="polite"
          aria-label="Results"
        >
          {state === "error" && (
            <div className="banner banner--danger">
              API offline — start the backend: <code>uvicorn app.main:app --reload</code>
            </div>
          )}
          {state === "idle" && !fxBlocked && (
            <div className="banner">Enter a selling price above zero to calculate.</div>
          )}
          {fxBlocked && (
            <div className="banner banner--danger">
              FX rates unavailable — cannot convert USD COGS to {currency}. Switch back to USD
              or reload.
            </div>
          )}
          {result?.warning && state === "ok" && (
            <div className="banner banner--danger">{result.warning}</div>
          )}

          <div className="shell">
            <div className="core hero-num">
              <div className="hero-num-top">
                <span className="chip chip--live">BREAK-EVEN ROAS</span>
                <span className="mini-note">profit = 0</span>
              </div>
              <p className="numeral">{fx(result?.roas_breakeven)}</p>
              <p className="hero-sub">
                {result?.breakeven_cpa != null ? (
                  <>
                    Ads below this lose money. Max spend per order:{" "}
                    <strong>{fm(result.breakeven_cpa)}</strong>.
                  </>
                ) : (
                  "This product cannot break even at these numbers."
                )}
              </p>
            </div>
          </div>

          <div className="duo">
            <div className="shell">
              <div className="core stat-card">
                <span className="field-name">TARGET ROAS — {fields.target || 0}% NET</span>
                <p className="numeral numeral--md numeral--accent">
                  {fx(result?.roas_at_target_margin)}
                </p>
                <p className="mini-note">
                  max spend {fm(result?.target_cpa)} / order
                </p>
              </div>
            </div>
            <div className="shell">
              <div className="core stat-card">
                <span className="field-name">
                  BUYING WINDOW — {fields.min || 0}–{fields.target || 0}% NET
                </span>
                <p className="numeral numeral--md">
                  {fx(result?.roas_at_min_margin)}
                  <span className="range-sep"> – </span>
                  {fx(result?.roas_at_target_margin)}
                </p>
                {band && (
                  <div className="window" aria-hidden="true">
                    <span
                      className="window-band"
                      style={{ left: `${band.lo}%`, width: `${band.hi - band.lo}%` }}
                    />
                    <span className="window-tick" style={{ left: `${band.be}%` }} />
                    <span className="window-label" style={{ left: `${band.be}%` }}>
                      BE
                    </span>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="stat-row">
            <div>
              <span className="field-name">MULTIPLIER</span>
              <p className="stat-val">
                {result?.multiplier != null ? `${result.multiplier.toFixed(2)}×` : "—"}
              </p>
            </div>
            <div>
              <span className="field-name">CONTRIBUTION / ORDER</span>
              <p className="stat-val">{fm(result?.contribution)}</p>
            </div>
            <div>
              <span className="field-name">PRICE / COGS ({currency})</span>
              <p className="stat-val">
                {fm(input ? input.selling_price : null)} / {fm(input ? input.cogs : null)}
              </p>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
