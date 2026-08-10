import { Component, useEffect, useState, type ReactNode } from "react";
import { Logo } from "./components/Logo";
import { HubPage } from "./pages/Hub";
import { RoasPage } from "./pages/Roas";

function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error) {
      return (
        <div className="crash">
          <p className="eyebrow">SOMETHING BROKE</p>
          <p>{this.state.error.message}</p>
          <button onClick={() => window.location.reload()}>Reload</button>
        </div>
      );
    }
    return this.props.children;
  }
}

export function App() {
  const hash = useHash();

  useEffect(() => {
    window.scrollTo(0, 0);
  }, [hash]);

  return (
    <>
      <header className="nav-wrap">
        <nav className="nav" aria-label="Primary">
          <a className="nav-brand" href="#/">
            <Logo size={26} />
            <span className="wordmark">ToolHub</span>
          </a>
          <span className="nav-sep" aria-hidden="true" />
          <a className="nav-link" href="#/">
            Tools
          </a>
          <span className="nav-chip">v0.1</span>
        </nav>
      </header>

      <main>
        <ErrorBoundary>
          {hash.startsWith("#/tools/roas-breakeven") ? <RoasPage /> : <HubPage />}
        </ErrorBoundary>
      </main>

      <footer className="footer">
        <span>TOOLHUB — OPERATOR TOOLS</span>
        <span className="footer-dot" aria-hidden="true" />
        <span>EVERY NUMBER UNDER CONTROL</span>
        <span className="footer-page">01</span>
      </footer>
    </>
  );
}
