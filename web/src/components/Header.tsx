import { Code2, LayoutDashboard, Moon, Plus, ScanSearch, Sun } from "lucide-react";
import { useStore, useT } from "../store";

export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" aria-hidden="true">
      <rect width="64" height="64" rx="14" fill="var(--accent)" />
      <circle cx="32" cy="32" r="20" fill="none" stroke="var(--on-accent)" strokeOpacity=".35" strokeWidth="3" />
      <path d="M32 11 39 32H25z" fill="var(--on-accent)" />
      <path d="M32 53 25 32h14z" fill="var(--on-accent)" fillOpacity=".45" />
      <circle cx="32" cy="32" r="3.2" fill="var(--accent)" />
    </svg>
  );
}

export function Header() {
  const t = useT();
  const { lang, setLang, theme, toggleTheme, reset, report, view, setView, setExportOpen } = useStore();
  return (
    <header className="header">
      <div className="header-left">
        <button className="brand" onClick={reset} aria-label={t.home}>
          <Logo />
          <span>ragcompass</span>
        </button>
        {report && (
          <>
            <span className="crumb-sep" aria-hidden>
              /
            </span>
            <span className="crumb" title={report.summary.root}>
              {report.summary.root}
            </span>
            <nav className="tabs" aria-label={t.views}>
              <button aria-current={view === "report" ? "page" : undefined} onClick={() => setView("report")} aria-label={t.report}>
                <LayoutDashboard size={15} aria-hidden />
                <span>{t.report}</span>
              </button>
              <button aria-current={view === "explorer" ? "page" : undefined} onClick={() => setView("explorer")} aria-label={t.explorer}>
                <ScanSearch size={15} aria-hidden />
                <span>{t.explorer}</span>
              </button>
            </nav>
          </>
        )}
      </div>
      <div className="header-actions">
        {report && (
          <>
            <button className="button sm" onClick={() => setExportOpen(true)} aria-label={t.export}>
              <Code2 size={15} aria-hidden />
              <span className="hide-sm">{t.export}</span>
            </button>
            <button className="button sm ghost" onClick={reset} aria-label={t.newAnalysis} title={t.newAnalysis}>
              <Plus size={15} aria-hidden />
              <span className="hide-sm">{t.newAnalysis}</span>
            </button>
            <span className="divider" aria-hidden />
          </>
        )}
        <div className="segmented sm" role="radiogroup" aria-label={t.language}>
          {(["en", "es"] as const).map((code) => (
            <button key={code} role="radio" aria-checked={lang === code} onClick={() => setLang(code)}>
              {code.toUpperCase()}
            </button>
          ))}
        </div>
        <button
          className="icon-button"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? t.themeLight : t.themeDark}
          title={theme === "dark" ? t.themeLight : t.themeDark}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </header>
  );
}
