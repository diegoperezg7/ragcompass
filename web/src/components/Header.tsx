import { Moon, Sun } from "lucide-react";
import { useStore, useT } from "../store";

export function Logo({ size = 28 }: { size?: number }) {
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
  const { lang, setLang, theme, toggleTheme, reset } = useStore();
  return (
    <header className="header">
      <button className="brand" onClick={reset}>
        <Logo />
        <span>ragcompass</span>
      </button>
      <div className="header-actions">
        <div className="segmented" role="group" aria-label={t.language}>
          {(["en", "es"] as const).map((code) => (
            <button key={code} aria-pressed={lang === code} onClick={() => setLang(code)}>
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
          {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      </div>
    </header>
  );
}
