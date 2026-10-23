// Placeholder data in the shape of docs/api.md for endpoints the server does not answer yet
// (bench, projection, export). The UI labels anything that comes from here as preview data.
import type { Bench, BenchConfig, ExportTarget, Projection, ProjectedChunk, Report } from "../types";
import { picks } from "../lib/report";

// Deterministic pseudo-random numbers so previews do not jump between renders.
function rng(seed: number) {
  let s = seed >>> 0 || 1;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619);
  return h >>> 0;
}

const round = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 1000;
const interval = (mean: number, spread: number) => ({ mean: round(mean), ci: [round(mean - spread), round(mean + spread)] as [number, number] });

export function mockBench(report: Report): Bench {
  const group = report.simulations.some((s) => s.group === "documents") ? "documents" : report.simulations[0]?.group;
  const sims = report.simulations.filter((s) => s.group === group);
  const pick = picks(report)[group ?? ""];
  const chosen = sims.find((s) => s.strategy === pick?.strategy && s.size === pick?.size && s.overlap === pick?.overlap);
  const others = sims
    .filter((s) => s !== chosen)
    .sort((a, b) => a.damage - b.damage)
    .filter((s, i, all) => all.findIndex((o) => o.strategy === s.strategy) === i)
    .slice(0, 3);
  const random = rng(hash(report.summary.root));
  const configs: BenchConfig[] = [chosen, ...others]
    .filter((s): s is NonNullable<typeof s> => Boolean(s))
    .map((s) => {
      const recall = Math.max(0.4, 0.94 - s.damage / 420 - (s.size > 512 ? 0.04 : 0)) + random() * 0.02;
      const tau = 1.6 + s.damage / 70;
      const at = (k: number) => round((recall + 0.05) * (1 - Math.exp(-k / tau)));
      return {
        label: `${s.strategy} ${s.size}/${s.overlap} · hybrid`,
        group: s.group,
        strategy: s.strategy,
        size: s.size,
        overlap: s.overlap,
        retriever: "hybrid",
        recommended: s === chosen,
        chunks: s.chunks,
        recall_at_k: interval(recall, 0.04 + random() * 0.02),
        mrr: interval(recall * 0.84, 0.05 + random() * 0.02),
        ndcg: interval(recall * 0.9, 0.04 + random() * 0.02),
        curves: { recall: { "1": at(1), "3": at(3), "5": at(5), "10": at(10) } },
        index_ms: Math.round(180 + s.chunks * 9 + random() * 40),
        query_ms: { mean: Math.round((2 + s.size / 300 + random()) * 10) / 10, p95: Math.round((4 + s.size / 160 + random() * 2) * 10) / 10 },
      };
    });
  const ranked = [...configs].sort((a, b) => b.ndcg.mean - a.ndcg.mean);
  const [best, second] = ranked;
  const margin = second ? best.ndcg.mean - second.ndcg.mean : 0;
  return {
    k: 5,
    seed: 13,
    queries: 60,
    mode: "template",
    query_kinds: { keyphrase: 20, masked: 20, question: 20 },
    lexical_overlap: { mean: 0.298, by_kind: { keyphrase: 0.391, masked: 0.216, question: 0.288 } },
    retrievers: ["bm25", "dense", "hybrid"],
    dense_model: "BAAI/bge-small-en-v1.5",
    warnings: [],
    primary_metric: "ndcg",
    configs,
    winner: {
      label: best?.label ?? "",
      runner_up: second?.label ?? null,
      significant: margin > 0.03,
      margin: second ? interval(margin, 0.03) : null,
    },
    decisions: [],
    sample_queries: [],
    elapsed_ms: 2310,
  };
}

export function mockProjection(report: Report): Projection {
  const files = report.documents.filter((d) => d.tokens > 0);
  const random = rng(hash(report.summary.root) + 7);
  const points: ProjectedChunk[] = [];
  files.forEach((doc, f) => {
    const angle = (2 * Math.PI * f) / Math.max(1, files.length);
    const count = Math.max(2, Math.min(16, Math.round(doc.tokens / 120)));
    for (let i = 0; i < count; i++) {
      points.push({
        id: points.length,
        file: doc.path,
        chunk_index: i,
        x: Math.cos(angle) * 0.6 + (random() - 0.5) * 0.45,
        y: Math.sin(angle) * 0.55 + (random() - 0.5) * 0.45,
        tokens: Math.round(60 + random() * 190),
        preview: `${doc.path}, chunk ${i + 1}`,
      });
    }
  });
  const anchor = points[Math.floor(points.length / 3)];
  const queries = anchor
    ? [
        {
          id: "q001",
          text: "How fast must a P2 ticket get a first response?",
          x: anchor.x + 0.05,
          y: anchor.y - 0.04,
          neighbors: points
            .map((p) => [p.id, (p.x - anchor.x - 0.05) ** 2 + (p.y - anchor.y + 0.04) ** 2] as const)
            .sort((a, b) => a[1] - b[1])
            .slice(0, 5)
            .map(([id]) => id),
        },
      ]
    : [];
  const pick = picks(report).documents ?? { strategy: "recursive", size: 512, overlap: 0 };
  return { model: "BAAI/bge-small-en-v1.5", group: "documents", ...pick, explained_variance: [0.21, 0.12], points, queries };
}

export function mockExport(report: Report, target: Exclude<ExportTarget, "yaml">): string {
  const config = report.config as {
    chunking?: Record<string, { strategy: string; size: number; overlap: number }>;
    embedding?: { models?: string[] };
    retrieval?: { top_k: number; hybrid_bm25: boolean };
  };
  const docs = config.chunking?.documents ?? { strategy: "recursive", size: 512, overlap: 0 };
  const model = config.embedding?.models?.[0] ?? "bge-m3";
  const k = config.retrieval?.top_k ?? 5;
  const hybrid = Boolean(config.retrieval?.hybrid_bm25);
  const header = `# ragcompass recommendation for ${report.summary.root}`;
  if (target === "langchain") {
    const splitter =
      docs.strategy === "heading"
        ? `MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")])`
        : `RecursiveCharacterTextSplitter.from_tiktoken_encoder(\n    encoding_name="cl100k_base", chunk_size=${docs.size}, chunk_overlap=${docs.overlap}\n)`;
    return `${header}
from langchain.retrievers import EnsembleRetriever
from langchain_community.retrievers import BM25Retriever
from langchain_community.vectorstores import FAISS
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

splitter = ${splitter}
chunks = splitter.split_documents(docs)

vectors = FAISS.from_documents(chunks, OllamaEmbeddings(model="${model}"))
dense = vectors.as_retriever(search_kwargs={"k": ${k}})
${hybrid ? `bm25 = BM25Retriever.from_documents(chunks, k=${k})\nretriever = EnsembleRetriever(retrievers=[bm25, dense], weights=[0.5, 0.5])` : "retriever = dense"}
`;
  }
  if (target === "llamaindex") {
    const parser = docs.strategy === "heading" ? "MarkdownNodeParser()" : `SentenceSplitter(chunk_size=${docs.size}, chunk_overlap=${docs.overlap})`;
    return `${header}
from llama_index.core import VectorStoreIndex
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.retrievers import QueryFusionRetriever
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.retrievers.bm25 import BM25Retriever

nodes = ${parser}.get_nodes_from_documents(documents)
index = VectorStoreIndex(nodes, embed_model=OllamaEmbedding(model_name="${model}"))
dense = index.as_retriever(similarity_top_k=${k})
${hybrid ? `bm25 = BM25Retriever.from_defaults(nodes=nodes, similarity_top_k=${k})\nretriever = QueryFusionRetriever([dense, bm25], similarity_top_k=${k}, num_queries=1, mode="reciprocal_rerank")` : "retriever = dense"}
`;
  }
  return `${header}
from haystack import Pipeline
from haystack.components.joiners import DocumentJoiner
from haystack.components.retrievers.in_memory import InMemoryBM25Retriever, InMemoryEmbeddingRetriever
from haystack.document_stores.in_memory import InMemoryDocumentStore
from haystack_integrations.components.embedders.ollama import OllamaTextEmbedder

store = InMemoryDocumentStore()
query = Pipeline()
query.add_component("embedder", OllamaTextEmbedder(model="${model}"))
query.add_component("dense", InMemoryEmbeddingRetriever(store, top_k=${k}))
query.connect("embedder.embedding", "dense.query_embedding")
${hybrid ? `query.add_component("bm25", InMemoryBM25Retriever(store, top_k=${k}))\nquery.add_component("joiner", DocumentJoiner(join_mode="reciprocal_rank_fusion"))\nquery.connect("bm25", "joiner")\nquery.connect("dense", "joiner")` : ""}
`;
}
