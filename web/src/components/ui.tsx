import { FlaskConical, Gauge } from "lucide-react";
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { useT } from "../store";

export function Panel({
  title,
  hint,
  actions,
  children,
  className = "",
  id,
}: {
  title?: ReactNode;
  hint?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section className={`panel ${className}`} aria-labelledby={id ? `${id}-title` : undefined}>
      {(title || actions) && (
        <header className="panel-head">
          <div className="panel-titles">
            {title && <h2 id={id ? `${id}-title` : undefined}>{title}</h2>}
            {hint && <p className="panel-hint">{hint}</p>}
          </div>
          {actions && <div className="panel-actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  label,
  size = "md",
}: {
  value: T;
  options: { value: T; label: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
}) {
  return (
    <div className={`segmented ${size}`} role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function BasisBadge({ basis }: { basis: "measured" | "rule-based" }) {
  const t = useT();
  return (
    <span className={`badge basis ${basis}`} title={basis === "measured" ? t.measuredHint : t.ruleHint}>
      {basis === "measured" ? <FlaskConical size={11} aria-hidden /> : <Gauge size={11} aria-hidden />}
      {basis === "measured" ? t.measured : t.ruleBased}
    </span>
  );
}

export function PreviewBadge() {
  const t = useT();
  return (
    <span className="badge preview" title={t.previewHint}>
      {t.preview}
    </span>
  );
}

export function Skeleton({ h = 16, w = "100%", r = 6 }: { h?: number; w?: number | string; r?: number }) {
  return <span className="skeleton" style={{ height: h, width: w, borderRadius: r }} aria-hidden />;
}

export function Empty({ icon, title, children }: { icon: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon}</div>
      <strong>{title}</strong>
      {children && <div className="empty-body">{children}</div>}
    </div>
  );
}

/* One floating tooltip for every chart: show() on pointer move, hide() on leave. */
interface TipState {
  x: number;
  y: number;
  content: ReactNode;
}
const TipContext = createContext<{ show: (e: { clientX: number; clientY: number }, content: ReactNode) => void; hide: () => void }>({
  show: () => {},
  hide: () => {},
});

export function TooltipProvider({ children }: { children: ReactNode }) {
  const [tip, setTip] = useState<TipState | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const show = useCallback((e: { clientX: number; clientY: number }, content: ReactNode) => setTip({ x: e.clientX, y: e.clientY, content }), []);
  const hide = useCallback(() => setTip(null), []);
  let left = 0;
  let top = 0;
  if (tip) {
    const width = ref.current?.offsetWidth ?? 220;
    const height = ref.current?.offsetHeight ?? 80;
    left = tip.x + 14 + width > window.innerWidth - 8 ? tip.x - width - 14 : tip.x + 14;
    top = tip.y + 14 + height > window.innerHeight - 8 ? tip.y - height - 14 : tip.y + 14;
  }
  return (
    <TipContext.Provider value={{ show, hide }}>
      {children}
      {tip && (
        <div ref={ref} className="tooltip" role="tooltip" style={{ left: Math.max(8, left), top: Math.max(8, top) }}>
          {tip.content}
        </div>
      )}
    </TipContext.Provider>
  );
}

export const useTooltip = () => useContext(TipContext);

/** Props that give an SVG mark a hover tooltip and the same text on keyboard focus. */
export function useTipProps() {
  const tip = useTooltip();
  return (content: ReactNode, label: string) => ({
    tabIndex: 0,
    "aria-label": label,
    onPointerMove: (e: React.PointerEvent) => tip.show(e, content),
    onPointerLeave: tip.hide,
    onFocus: (e: React.FocusEvent<Element>) => {
      const box = e.currentTarget.getBoundingClientRect();
      tip.show({ clientX: box.right, clientY: box.top }, content);
    },
    onBlur: tip.hide,
  });
}

export function TipRows({ title, rows }: { title: ReactNode; rows: [ReactNode, ReactNode][] }) {
  return (
    <>
      <div className="tip-title">{title}</div>
      {rows.map(([k, v], i) => (
        <div key={i} className="tip-row">
          <span>{k}</span>
          <strong>{v}</strong>
        </div>
      ))}
    </>
  );
}
