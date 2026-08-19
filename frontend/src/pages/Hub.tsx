import { useEffect, useState } from "react";
import { fetchTools, type Tool } from "../api";
import { useReveal } from "../useReveal";

function Glyph({ name }: { name: string }) {
  const stroke = { stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round" } as const;
  if (name === "chart") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
        <path d="M3.5 16.5v-6M10 16.5V4M16.5 16.5v-9" {...stroke} />
      </svg>
    );
  }
  if (name === "convert") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none">
        <path d="M4 7h10.5M12 3.5 15.5 7 12 10.5M16 13H5.5M8 9.5 4.5 13 8 16.5" {...stroke} />
      </svg>
    );
  }
  if (name === "invoice") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none">
        <path d="M5 3h10v14l-2.5-1.5L10 17l-2.5-1.5L5 17V3ZM8 7.5h4M8 11h4" {...stroke} strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "ads") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none">
        <path d="M3.5 8.5v3M6.5 6v8M3.5 10h3M6.5 10l8-5.5v11L6.5 10ZM16 8v4" {...stroke} strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "experiment") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none">
        <path d="M3.5 10h5M8.5 10c3 0 3-4.5 6-4.5H17M8.5 10c3 0 3 4.5 6 4.5H17M14.5 3.5 17 5.5l-2.5 2M14.5 12.5l2.5 2-2.5 2" {...stroke} strokeLinejoin="round" />
      </svg>
    );
  }
  if (name === "call") {
    return (
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true" fill="none">
        <path d="M4 3.5h3l1.5 4-2 1.5a10 10 0 0 0 4.5 4.5l1.5-2 4 1.5v3c0 .5-.5 1-1 1C9 17 3 11 3 4.5c0-.5.5-1 1-1Z" {...stroke} strokeLinejoin="round" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
      <circle cx="6" cy="6" r="1.6" fill="currentColor" />
      <circle cx="14" cy="6" r="1.6" fill="currentColor" />
      <circle cx="6" cy="14" r="1.6" fill="currentColor" />
      <circle cx="14" cy="14" r="1.6" fill="currentColor" />
    </svg>
  );
}

function ToolCard({ tool, wide, delay }: { tool: Tool; wide: boolean; delay: number }) {
  const live = tool.status === "live";
  const external = live && !!tool.url;
  return (
    <a
      className={`shell card reveal${wide ? " card--wide" : ""}${live ? "" : " card--soon"}`}
      href={live ? (tool.url ?? `#/tools/${tool.slug}`) : undefined}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
      style={{ transitionDelay: `${delay}ms` }}
    >
      <div className="core card-core">
        <div className="card-top">
          <span className="icon-tile">
            <Glyph name={tool.icon} />
          </span>
          <span className={`chip${live ? " chip--live" : ""}`}>{live ? "LIVE" : "SOON"}</span>
        </div>
        <h3>{tool.name}</h3>
        <p>{tool.description}</p>
        <div className="card-foot">
          <span className="card-open">
            {live ? (external ? "Open app" : "Open tool") : "In the dock"}
          </span>
          <span className="btn-orb" aria-hidden="true">
            ↗
          </span>
        </div>
      </div>
    </a>
  );
}

export function HubPage() {
  const [tools, setTools] = useState<Tool[] | null>(null);
  const [offline, setOffline] = useState(false);
  const ref = useReveal<HTMLDivElement>(tools);

  useEffect(() => {
    const ctrl = new AbortController();
    fetchTools(ctrl.signal)
      .then(setTools)
      .catch((e: unknown) => {
        if ((e as Error).name !== "AbortError") setOffline(true);
      });
    return () => ctrl.abort();
  }, []);

  const count = tools?.length ?? 0;

  return (
    <div ref={ref} className="page">
      <section className="hero">
        <p className="eyebrow reveal">TOOLHUB — INTERNAL TOOLS</p>
        <h1 className="reveal" style={{ transitionDelay: "80ms" }}>
          Every <em>number</em>
          <br />
          under control.
        </h1>
        <p className="lede reveal" style={{ transitionDelay: "160ms" }}>
          One hub for the calculators and utilities the team runs on. Open a tool, get the
          answer, get back to work.
        </p>
      </section>

      <div className="rule reveal">
        <span>TOOLS — {String(count).padStart(2, "0")}</span>
      </div>

      {offline && (
        <div className="banner banner--danger reveal" data-in="">
          API offline — start the backend: <code>uvicorn app.main:app --reload</code>
        </div>
      )}

      <section className="bento">
        {(tools ?? []).map((t, i) => (
          <ToolCard key={t.slug} tool={t} wide={i % 2 === 0} delay={i * 90} />
        ))}
        <div className="shell card card--ghost reveal" style={{ transitionDelay: `${count * 90}ms` }}>
          <div className="core card-core">
            <span className="ghost-mark" aria-hidden="true">
              +
            </span>
            <p>Next tool docks here.</p>
          </div>
        </div>
      </section>
    </div>
  );
}
