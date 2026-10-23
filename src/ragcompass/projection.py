"""2D map of chunk embeddings: PCA with numpy, deterministic, for plotting in the web app."""

from __future__ import annotations

import random

from ragcompass import embeddings
from ragcompass.analyze import Analysis
from ragcompass.bench import (
    SEED,
    Candidate,
    _languages,
    build_chunks,
    generate_queries,
    main_group,
    recommended_value,
)
from ragcompass.explorer import MAX_SIZE, MIN_SIZE, STRATEGIES, ExplorerError
from ragcompass.simulate import group_of

MAX_POINTS = 2000
QUERIES = 20
NEIGHBORS = 5
PREVIEW = 160
FLAT_VARIANCE = 1e-6  # share of variance below which the second axis is noise


def _pca(matrix):
    """Project rows on the first two principal components, with signs fixed for reproducibility."""
    import numpy as np

    centre = matrix.mean(axis=0)
    centred = matrix - centre
    if len(matrix) < 2:
        return np.zeros((len(matrix), 2)), centre, np.zeros((2, matrix.shape[1])), [0.0, 0.0]
    _, singular, vt = np.linalg.svd(centred, full_matrices=False)
    components = vt[:2]
    if len(components) < 2:
        components = np.vstack([components, np.zeros_like(components)])
    for row in components:  # SVD signs are arbitrary; make the largest loading positive
        if row[np.argmax(np.abs(row))] < 0:
            row *= -1
    energy = float((singular**2).sum()) or 1.0
    explained = [round(float(v**2) / energy, 4) for v in singular[:2]] + [0.0] * (2 - len(singular[:2]))
    return centred @ components.T, centre, components, explained


def project(
    analysis: Analysis,
    group: str | None = None,
    strategy: str | None = None,
    size: int | None = None,
    overlap: int | None = None,
    queries: bool = True,
    seed: int = SEED,
) -> dict:
    if not embeddings.available():
        raise embeddings.EmbeddingsUnavailable(embeddings.INSTALL_HINT)
    import numpy as np

    groups = {group_of(doc.kind) for doc in analysis.docs.values() if len(doc.layout.tokens)} - {None}
    group = group or ("documents" if "documents" in groups else main_group(analysis))
    if group not in groups:
        raise ExplorerError(f"no {group} in this corpus; choose one of {', '.join(sorted(groups))}")
    pick = recommended_value(analysis, group)
    strategy = strategy or pick["strategy"]
    if strategy not in STRATEGIES[group]:
        raise ExplorerError(f"strategy must be one of {', '.join(STRATEGIES[group])} for {group}")
    size = size or pick["size"]
    if not MIN_SIZE <= size <= MAX_SIZE:
        raise ExplorerError(f"size must be between {MIN_SIZE} and {MAX_SIZE}")
    overlap = overlap if overlap is not None else (pick["overlap"] if strategy == pick["strategy"] else 0)
    if strategy not in ("fixed", "recursive"):
        overlap = 0
    if not 0 <= overlap < size:
        raise ExplorerError("overlap must be at least 0 and smaller than size")

    files = {path for path, doc in analysis.docs.items() if group_of(doc.kind) == group}
    chunks = [
        c for c in build_chunks(analysis, Candidate(group, strategy, size, overlap, False)) if c.file in files
    ]
    if len(chunks) > MAX_POINTS:
        keep = sorted(random.Random(seed).sample(range(len(chunks)), MAX_POINTS))
        chunks = [chunks[i] for i in keep]

    embedder = embeddings.get_embedder(embeddings.model_for(_languages(analysis)))
    vectors = embedder.embed([c.text for c in chunks])
    coords, centre, components, explained = _pca(vectors)
    if explained[1] < FLAT_VARIANCE:
        # Nothing meaningful on the second axis (one point, or all points on a line): draw it flat
        # instead of stretching numerical noise to the full height.
        coords[:, 1] = 0.0
        components[1] = 0.0
    scale = np.abs(coords).max(axis=0)
    scale[scale == 0] = 1.0
    coords = coords / scale

    points = [
        {
            "id": i,
            "file": c.file,
            "chunk_index": c.index,
            "x": round(float(coords[i][0]), 4),
            "y": round(float(coords[i][1]), 4),
            "tokens": analysis.docs[c.file].layout.tokens.count(c.start, c.end),
            "preview": " ".join(c.text.split())[:PREVIEW],
        }
        for i, c in enumerate(chunks)
    ]
    result = {
        "model": embedder.name,
        "group": group,
        "strategy": strategy,
        "size": size,
        "overlap": overlap,
        "explained_variance": explained,
        "points": points,
        "queries": [],
    }
    if queries and chunks:
        query_list = [q for q in generate_queries(analysis, QUERIES * 3, seed) if q.file in files][:QUERIES]
        if query_list:
            qvectors = embedder.embed([q.text for q in query_list])
            qcoords = ((qvectors - centre) @ components.T) / scale
            similarity = qvectors @ vectors.T
            for q, xy, row in zip(query_list, qcoords, similarity, strict=True):
                nearest = sorted(range(len(row)), key=lambda j: (-float(row[j]), j))[:NEIGHBORS]
                result["queries"].append(
                    {
                        "id": q.id,
                        "text": q.text,
                        "file": q.file,
                        "x": round(float(xy[0]), 4),
                        "y": round(float(xy[1]), 4),
                        "neighbors": nearest,
                    }
                )
    return result
