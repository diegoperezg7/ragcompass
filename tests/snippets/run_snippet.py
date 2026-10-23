"""Execute a generated snippet with fake embeddings. Run with an interpreter that has the framework.

Usage: python run_snippet.py <target> <snippet.py>
Exits non-zero if splitting or retrieval fails.
"""

import hashlib
import sys

TEXT = (
    """# Maintenance manual

## Safety

Wait two minutes after switching off before opening the enclosure. Wear insulated gloves.

## Air filter

Remove the four screws of the rear grille with a T10 driver and clean the filter HX-FLT-021.
Replace it when the foam is torn. Record the cleaning in the service log.

## Fan

A worn fan raises warning W-212. Order the fan assembly HX-FAN-118 and unplug connector J14.
"""
    * 3
)


def vector(text: str, size: int = 32) -> list[float]:
    digest = hashlib.sha256(text.encode()).digest()
    return [b / 255 for b in digest[:size]]


def main(target: str, path: str) -> None:
    namespace: dict = {"__name__": "snippet"}
    with open(path, encoding="utf-8") as handle:
        exec(compile(handle.read(), path, "exec"), namespace)
    split, make = namespace["split"], namespace["make_retriever"]
    if target == "langchain":
        from langchain_core.documents import Document
        from langchain_core.embeddings import DeterministicFakeEmbedding

        chunks = split([Document(page_content=TEXT, metadata={"source": "manual.md"})])
        hits = make(chunks, DeterministicFakeEmbedding(size=32)).invoke("fan assembly HX-FAN-118")
    elif target == "llamaindex":
        from llama_index.core import Document, MockEmbedding

        chunks = split([Document(text=TEXT, metadata={"source": "manual.md"})])
        hits = make(chunks, MockEmbedding(embed_dim=32)).retrieve("fan assembly HX-FAN-118")
    else:
        from haystack import Document

        class DocumentEmbedder:
            def run(self, documents):
                for doc in documents:
                    doc.embedding = vector(doc.content)
                return {"documents": documents}

        class TextEmbedder:
            def run(self, text):
                return {"embedding": vector(text)}

        chunks = split([Document(content=TEXT, meta={"source": "manual.md"})])
        hits = make(chunks, DocumentEmbedder(), TextEmbedder())("fan assembly HX-FAN-118")
    assert len(chunks) > 1, "nothing was split"
    assert hits, "the retriever returned nothing"
    print(f"{target}: {len(chunks)} chunks, {len(hits)} hits")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
