import { Dashboard } from "./components/Dashboard";
import { Explorer } from "./components/Explorer";
import { ExportDialog } from "./components/ExportDialog";
import { Header } from "./components/Header";
import { Home } from "./components/Home";
import { TooltipProvider } from "./components/ui";
import { useStore, useT } from "./store";

export function App() {
  const t = useT();
  const { status, report, view } = useStore();
  const ready = status === "done" && report;
  return (
    <TooltipProvider>
      <a className="skip-link" href="#main">
        {t.skipToContent}
      </a>
      <Header />
      <main id="main" className="main">
        {ready ? view === "explorer" ? <Explorer report={report} /> : <Dashboard report={report} /> : <Home />}
      </main>
      {ready && <ExportDialog report={report} />}
    </TooltipProvider>
  );
}
