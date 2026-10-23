export type TokenKind = "comment" | "string" | "keyword" | "number" | "key" | "func" | "plain";

const PY_KEYWORDS = new Set(
  "from import as def class return if else elif for in while with True False None and or not lambda yield try except finally raise".split(" "),
);

const PYTHON = /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|\b(\d+(?:\.\d+)?)\b|\b([A-Za-z_]\w*)(?=\s*\()|\b([A-Za-z_]\w*)\b/g;
const YAML = /(#[^\n]*)|^(\s*-?\s*)([\w.-]+)(?=:)|("(?:\\.|[^"\\\n])*"|'[^'\n]*')|\b(true|false|null)\b|(?<=:\s+|-\s+)(-?\d+(?:\.\d+)?)(?=\s*(?:#|$))/gm;

/** Small tokenizer for the two languages the export shows; enough for readable coloring. */
export function highlight(code: string, language: "python" | "yaml"): { kind: TokenKind; text: string }[] {
  const out: { kind: TokenKind; text: string }[] = [];
  let last = 0;
  const push = (kind: TokenKind, text: string) => text && out.push({ kind, text });
  const pattern = language === "python" ? PYTHON : YAML;
  pattern.lastIndex = 0;
  for (let m = pattern.exec(code); m; m = pattern.exec(code)) {
    if (m[0] === "") {
      pattern.lastIndex++;
      continue;
    }
    push("plain", code.slice(last, m.index));
    if (language === "python") {
      if (m[1]) push("comment", m[1]);
      else if (m[2]) push("string", m[2]);
      else if (m[3]) push("number", m[3]);
      else if (m[4]) push(PY_KEYWORDS.has(m[4]) ? "keyword" : "func", m[4]);
      else if (m[5]) push(PY_KEYWORDS.has(m[5]) ? "keyword" : "plain", m[5]);
    } else {
      if (m[1]) push("comment", m[1]);
      else if (m[3]) {
        push("plain", m[2]);
        push("key", m[3]);
      } else if (m[4]) push("string", m[4]);
      else if (m[5]) push("keyword", m[5]);
      else if (m[6]) push("number", m[6]);
    }
    last = m.index + m[0].length;
  }
  push("plain", code.slice(last));
  return out;
}
