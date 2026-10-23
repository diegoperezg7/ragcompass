import "@fontsource-variable/inter";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Header } from "./components/Header";
import { Report } from "./components/Report";
import { Upload } from "./components/Upload";
import { useStore, useT } from "./store";
import "./styles.css";

function App() {
  const t = useT();
  const { status, report } = useStore();
  return (
    <>
      <Header />
      <main className="main">
        {status === "done" && report ? (
          <Report report={report} />
        ) : (
          <div className="home">
            <div className="hero">
              <h1>ragcompass</h1>
              <p className="muted">{t.tagline}</p>
            </div>
            <Upload />
          </div>
        )}
      </main>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
