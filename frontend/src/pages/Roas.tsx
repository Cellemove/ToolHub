import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  calcRoas,
  deleteActiveOffer,
  fetchActiveOffers,
  fetchFxRates,
  fetchSheetProducts,
  saveActiveOffer,
  saveSheetProduct,
  type ActiveOffer,
  type RoasInput,
  type RoasResult,
  type SheetProduct,
} from "../api";
import { useReveal } from "../useReveal";

const CUSTOM = "__custom__";
const MARKETS = ["UK", "USA", "CANADA", "PT", "PL", "GR", "FR", "DE", "ES", "MX", "CZ"];
const MARKET_CURRENCY: Record<string, string> = {
  UK: "GBP",
  USA: "USD",
  CANADA: "CAD",
  PT: "EUR",
  PL: "PLN",
  GR: "EUR",
  FR: "EUR",
  DE: "EUR",
  ES: "EUR",
  MX: "MXN",
  CZ: "CZK",
};

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

function identityFromPreset(name: string) {
  const matchedMarket = name.match(/\b(UK|USA|US|CANADA|PT|PL|GR|FR|DE|ES|MX|CZ)\b/i)?.[1]?.toUpperCase() ?? "";
  const market = matchedMarket === "US" ? "USA" : matchedMarket;
  const product = /\bV2\b/i.test(name) ? "VLegging V2" : "VLegging V1";
  let bundle = name
    .replace(/\b(UK|USA|US|CANADA|PT|PL|GR|FR|DE|ES|MX|CZ|V1|V2)\b/gi, "")
    .replace(/\s+/g, " ")
    .trim();
  bundle = bundle.replace(/^(\d+)\s*(legging)?/i, (_, count: string) =>
    `${count} ${count === "1" ? "Legging" : "Leggings"}`,
  );
  bundle = bundle
    .split("+")
    .map((part) =>
      part
        .trim()
        .replace(/\b(sleeve|patch)\b/gi, (word) => word[0].toUpperCase() + word.slice(1).toLowerCase())
        .replace(/\btop bra\b/i, "Top Bra"),
    )
    .join(" + ");
  return { market, product, bundle };
}

function sheetBundleName(product: string, bundle: string, market: string) {
  let name = bundle.trim();
  const version = product.match(/\bV\d+\b/i)?.[0]?.toUpperCase();
  if (version && !new RegExp(`\\b${version}\\b`, "i").test(name)) name += ` ${version}`;
  if (market && !new RegExp(`\\b${market}\\b`, "i").test(name)) name += ` ${market}`;
  return name.trim();
}

function OfferOverview({
  offers,
  state,
  error,
  market,
  onMarketChange,
  onRemove,
  removingKey,
  removeError,
}: {
  offers: ActiveOffer[];
  state: "loading" | "ok" | "error";
  error: string | null;
  market: string;
  onMarketChange: (market: string) => void;
  onRemove: (offer: ActiveOffer) => void;
  removingKey: string | null;
  removeError: string | null;
}) {
  const [confirmRemoveKey, setConfirmRemoveKey] = useState<string | null>(null);
  const shown = useMemo(() => offers.filter((offer) => offer.market === market), [offers, market]);
  const groups = useMemo(() => {
    const next = new Map<string, ActiveOffer[]>();
    for (const offer of shown) next.set(offer.product, [...(next.get(offer.product) ?? []), offer]);
    return [...next.entries()];
  }, [shown]);
  const roas = (value: number | null) => (value == null ? "--" : value.toFixed(2));
  const handleRemoveClick = (event: MouseEvent<HTMLButtonElement>) => {
    const key = event.currentTarget.dataset.offerKey;
    if (!key) return;
    if (confirmRemoveKey !== key) {
      setConfirmRemoveKey(key);
      return;
    }
    const offer = shown.find((item) => `${item.market}:${item.product}:${item.bundle}` === key);
    if (offer) {
      setConfirmRemoveKey(null);
      onRemove(offer);
    }
  };

  return (
    <section className="overview shell reveal" style={{ transitionDelay: "100ms" }} aria-label="Active offer overview">
      <div className="core overview-core">
        <div className="overview-head">
          <div>
            <p className="eyebrow">ACTIVE CONFIGURATION</p>
            <h2>Break-even by market &amp; bundle</h2>
            <p className="overview-copy">
              One registered offer per slot. Calculator tests below never appear here unless you set them active.
            </p>
          </div>
          <label className="field market-picker">
            <span className="field-name">Market</span>
            <span className="control">
              <select value={market} onChange={(event) => onMarketChange(event.target.value)}>
                {MARKETS.map((item) => <option key={item} value={item}>{item}</option>)}
              </select>
            </span>
          </label>
        </div>

        {state === "loading" && <div className="overview-empty">Loading active offers...</div>}
        {state === "error" && <div className="banner banner--danger">{error ?? "Active offers are unavailable."}</div>}
        {removeError && <div className="banner banner--danger">{removeError}</div>}
        {state === "ok" && groups.length === 0 && <div className="overview-empty">No active offers registered for this market.</div>}
        {state === "ok" && groups.map(([product, productOffers]) => (
          <div className="offer-group" key={product}>
            <div className="offer-group-title">
              <h3>{product}</h3>
              <span>{productOffers.length} {productOffers.length === 1 ? "bundle" : "bundles"}</span>
            </div>
            <div className="offer-table-wrap">
              <table className="offer-table">
                <thead>
                  <tr>
                    <th>Bundle</th>
                    <th>Break-even</th>
                    <th>Min ROAS</th>
                    <th>Target ROAS</th>
                    <th>Price</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {productOffers.map((offer) => {
                    const key = `${offer.market}:${offer.product}:${offer.bundle}`;
                    return (
                      <tr key={key}>
                        <td><span className="status-dot" aria-hidden="true" />{offer.bundle}</td>
                        <td className="offer-be">{roas(offer.roas_breakeven)}</td>
                        <td>{roas(offer.roas_at_min_margin)}</td>
                        <td>{roas(offer.roas_at_target_margin)}</td>
                        <td>{offer.currency} {offer.selling_price.toFixed(2)}</td>
                        <td>
                          <button
                            type="button"
                            className="remove-offer"
                            data-offer-key={key}
                            onClick={handleRemoveClick}
                            disabled={removingKey !== null}
                            aria-label={
                              confirmRemoveKey === key
                                ? `Confirm removal of ${offer.bundle} from ${offer.product} in ${offer.market}`
                                : `Remove ${offer.bundle} from ${offer.product} in ${offer.market}`
                            }
                          >
                            {removingKey === key
                              ? "Removing..."
                              : confirmRemoveKey === key
                                ? "Confirm remove"
                                : "Remove"}
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function RoasPage() {
  const [fields, setFields] = useState<Fields>(DEFAULTS);
  const [lines, setLines] = useState<CogsLine[]>([{ id: 0, label: "", amount: "13.80" }]);
  const nextId = useRef(1);
  const [product, setProduct] = useState("");
  const [presets, setPresets] = useState<SheetProduct[]>([]);
  const [rates, setRates] = useState<Record<string, number> | null>(null);
  const [result, setResult] = useState<RoasResult | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ok" | "error">("loading");
  const [offers, setOffers] = useState<ActiveOffer[]>([]);
  const [offersState, setOffersState] = useState<"loading" | "ok" | "error">("loading");
  const [offersError, setOffersError] = useState<string | null>(null);
  const [overviewMarket, setOverviewMarket] = useState("UK");
  const [activeMarket, setActiveMarket] = useState("UK");
  const [activeProduct, setActiveProduct] = useState("VLegging V1");
  const [activeBundle, setActiveBundle] = useState("2 Leggings + Sleeve");
  const [registerState, setRegisterState] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [registerError, setRegisterError] = useState<string | null>(null);
  const [sheetSaveState, setSheetSaveState] = useState<"idle" | "saving" | "done" | "error">("idle");
  const [sheetSaveError, setSheetSaveError] = useState<string | null>(null);
  const [sheetRow, setSheetRow] = useState<number | null>(null);
  const [removingKey, setRemovingKey] = useState<string | null>(null);
  const [removeError, setRemoveError] = useState<string | null>(null);
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

  // USD is the accounting currency for inputs, calculations, storage, and Sheets.
  const input = useMemo(() => toInput(fields, cogsTotal), [fields, cogsTotal]);

  useEffect(() => {
    const ctrl = new AbortController();
    // Presets and FX are optional; the active overview reports its own failure.
    fetchSheetProducts(ctrl.signal).then(setPresets).catch(() => {});
    fetchFxRates(ctrl.signal).then(setRates).catch(() => {});
    fetchActiveOffers(ctrl.signal)
      .then((next) => {
        setOffers(next);
        setOffersState("ok");
      })
      .catch((error: unknown) => {
        if ((error as Error).name === "AbortError") return;
        setOffersState("error");
        setOffersError(error instanceof Error ? error.message : "Active offers are unavailable.");
      });
    return () => ctrl.abort();
  }, []);

  const loadPreset = (name: string) => {
    setProduct(name === CUSTOM ? "" : name);
    const p = presets.find((x) => x.name === name);
    if (!p) return;
    const identity = identityFromPreset(p.name);
    if (identity.market) {
      setActiveMarket(identity.market);
    }
    setActiveProduct(identity.product);
    setActiveBundle(identity.bundle);
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

  const suggestedName =
    lines.map((l) => l.label.trim()).filter(Boolean).join(" + ") || "Custom offer";
  const sheetName = sheetBundleName(
    activeProduct,
    activeBundle.trim() || suggestedName,
    activeMarket,
  );
  const alreadyInSheet = presets.some(
    (preset) => preset.name.trim().toLowerCase() === sheetName.toLowerCase(),
  );

  useEffect(() => {
    setSheetSaveState("idle");
    setSheetSaveError(null);
    setSheetRow(null);
  }, [sheetName, fields, cogsTotal]);

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

  const registerActiveOffer = () => {
    const base = toInput(fields, cogsTotal);
    const market = activeMarket.trim().toUpperCase();
    const registeredProduct = activeProduct.trim();
    const bundle = activeBundle.trim() || suggestedName;
    if (!base || !market || !registeredProduct || !bundle || registerState === "saving") return;
    setRegisterState("saving");
    setRegisterError(null);
    saveActiveOffer({
      market,
      product: registeredProduct,
      bundle,
      currency: "USD",
      selling_price: base.selling_price,
      cogs_usd: base.cogs,
      psp_fee: base.psp_fee,
      vat: base.vat,
      other_fees: base.other_fees,
      min_margin: base.min_margin,
      target_margin: base.target_margin,
    })
      .then(() => {
        setRegisterState("done");
        setOverviewMarket(market);
        return fetchActiveOffers()
          .then((next) => {
            setOffers(next);
            setOffersState("ok");
            setOffersError(null);
          })
          .catch((error: unknown) => {
            setOffersState("error");
            setOffersError(error instanceof Error ? error.message : "Active offer saved; overview refresh failed.");
          });
      })
      .catch((error: unknown) => {
        setRegisterState("error");
        setRegisterError(error instanceof Error ? error.message : "Could not set the active offer.");
      });
  };

  const addBundleToSheet = () => {
    const base = toInput(fields, cogsTotal);
    if (!base || !sheetName || alreadyInSheet || sheetSaveState === "saving") return;
    setSheetSaveState("saving");
    setSheetSaveError(null);
    setSheetRow(null);
    saveSheetProduct({
      name: sheetName,
      psp_fee: base.psp_fee,
      vat: base.vat,
      other_fees: base.other_fees,
      min_margin: base.min_margin,
      target_margin: base.target_margin,
      cogs: base.cogs,
      selling_price: base.selling_price,
    })
      .then(({ row }) => {
        setSheetRow(row);
        setSheetSaveState("done");
        return fetchSheetProducts()
          .then(setPresets)
          .catch(() => {});
      })
      .catch((error: unknown) => {
        setSheetSaveState("error");
        setSheetSaveError(error instanceof Error ? error.message : "Could not add the bundle to Google Sheets.");
      });
  };

  const removeActiveOffer = (offer: ActiveOffer) => {
    const key = `${offer.market}:${offer.product}:${offer.bundle}`;
    setRemovingKey(key);
    setRemoveError(null);
    deleteActiveOffer({ market: offer.market, product: offer.product, bundle: offer.bundle })
      .then(() => {
        setOffers((current) =>
          current.filter(
            (item) =>
              item.market !== offer.market ||
              item.product !== offer.product ||
              item.bundle !== offer.bundle,
          ),
        );
      })
      .catch((error: unknown) => {
        setRemoveError(error instanceof Error ? error.message : "Could not remove the active offer.");
      })
      .finally(() => setRemovingKey(null));
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
    () => new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }),
    [],
  );
  const fm = (v: number | null | undefined) => (v == null ? "—" : money.format(v));
  const fx = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(2));
  const localCurrency = MARKET_CURRENCY[activeMarket] ?? "USD";
  const localRate = localCurrency === "USD" ? 1 : rates?.[localCurrency];
  const localMoney = useMemo(
    () => new Intl.NumberFormat(undefined, { style: "currency", currency: localCurrency }),
    [localCurrency],
  );
  const local = (value: number | null | undefined) =>
    value == null || localRate == null ? "—" : localMoney.format(value * localRate);

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

      <OfferOverview
        offers={offers}
        state={offersState}
        error={offersError}
        market={overviewMarket}
        onMarketChange={setOverviewMarket}
        onRemove={removeActiveOffer}
        removingKey={removingKey}
        removeError={removeError}
      />

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
              <Field label="Accounting currency">
                <input type="text" readOnly tabIndex={-1} value="USD" />
              </Field>
            </div>

            <div className="grid-2">
              <Field label="Selling price — USD" unit="$">
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

            <div className="activation">
              <div className="activation-head">
                <div>
                  <p className="group-label activation-label">Active offer</p>
                  <p>Test mode is the default. Save only when these numbers should replace the active configuration.</p>
                </div>
                <span className="chip chip--test">TEST</span>
              </div>
              <div className="grid-3 active-fields">
                <Field label="Market">
                  <select
                    value={activeMarket}
                    onChange={(event) => {
                      const market = event.target.value;
                      setActiveMarket(market);
                    }}
                  >
                    {MARKETS.map((market) => <option key={market} value={market}>{market}</option>)}
                  </select>
                </Field>
                <Field label="Product">
                  <input
                    type="text"
                    value={activeProduct}
                    onChange={(event) => setActiveProduct(event.target.value)}
                    placeholder="VLegging V1"
                  />
                </Field>
                <Field label="Bundle">
                  <input
                    type="text"
                    value={activeBundle}
                    onChange={(event) => setActiveBundle(event.target.value)}
                    placeholder={suggestedName}
                  />
                </Field>
              </div>
              <div className="activation-actions">
                <button
                  type="button"
                  className="activate-btn"
                  onClick={registerActiveOffer}
                  disabled={
                    stale ||
                    registerState === "saving" ||
                    !activeMarket.trim() ||
                    !activeProduct.trim() ||
                    !(activeBundle.trim() || suggestedName)
                  }
                >
                  {registerState === "saving"
                    ? "SAVING ACTIVE OFFER…"
                    : registerState === "done"
                      ? "ACTIVE OFFER UPDATED ✓"
                      : "SET AS ACTIVE OFFER"}
                </button>
                <button
                  type="button"
                  className="sheet-btn"
                  onClick={addBundleToSheet}
                  disabled={
                    !toInput(fields, cogsTotal) ||
                    !sheetName ||
                    alreadyInSheet ||
                    sheetSaveState === "saving"
                  }
                  title={sheetName ? `Sheet row name: ${sheetName}` : undefined}
                >
                  {sheetSaveState === "saving"
                      ? "ADDING TO SHEET…"
                      : sheetSaveState === "done"
                        ? `ADDED TO ROW ${sheetRow ?? ""} ✓`
                        : alreadyInSheet
                          ? "ALREADY IN SHEET"
                          : "ADD BUNDLE TO SHEET"}
                </button>
              </div>
              <p className="sheet-name-preview">Google Sheet row: <strong>{sheetName || "—"}</strong></p>
              {registerState === "error" && registerError && (
                <div className="banner banner--danger">{registerError}</div>
              )}
              {sheetSaveState === "error" && sheetSaveError && (
                <div className="banner banner--danger">{sheetSaveError}</div>
              )}
            </div>
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
          {state === "idle" && (
            <div className="banner">Enter a selling price above zero to calculate.</div>
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
              <span className="field-name">PRICE / COGS (USD)</span>
              <p className="stat-val">
                {fm(input ? input.selling_price : null)} / {fm(input ? input.cogs : null)}
              </p>
            </div>
          </div>

          <div className="shell conversion-card">
            <div className="core">
              <div className="conversion-head">
                <div>
                  <span className="field-name">MARKET CONVERSION — DISPLAY ONLY</span>
                  <h3>{activeMarket} · {localCurrency}</h3>
                </div>
                <span className="chip chip--test">FX</span>
              </div>
              {localRate == null ? (
                <div className="banner banner--danger">
                  FX rate unavailable. USD calculations and saved values are unaffected.
                </div>
              ) : (
                <>
                  <p className="conversion-rate">1 USD = {localRate.toFixed(4)} {localCurrency}</p>
                  <div className="conversion-grid">
                    <div>
                      <span className="field-name">SELLING PRICE</span>
                      <p className="stat-val">{local(input?.selling_price)}</p>
                    </div>
                    <div>
                      <span className="field-name">COGS</span>
                      <p className="stat-val">{local(input?.cogs)}</p>
                    </div>
                    <div>
                      <span className="field-name">CONTRIBUTION</span>
                      <p className="stat-val">{local(result?.contribution)}</p>
                    </div>
                    <div>
                      <span className="field-name">MAX AD SPEND</span>
                      <p className="stat-val">{local(result?.breakeven_cpa)}</p>
                    </div>
                  </div>
                  <p className="conversion-note">
                    Reference conversion only. Calculations, active offers, and Google Sheet rows remain in USD.
                  </p>
                </>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
