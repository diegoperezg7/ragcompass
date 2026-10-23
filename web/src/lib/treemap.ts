export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Squarified treemap (Bruls et al.): lays out values, largest first, keeping tiles close to square. */
export function squarify<T>(items: T[], value: (item: T) => number, box: Rect): (Rect & { item: T })[] {
  const sorted = items.filter((i) => value(i) > 0).sort((a, b) => value(b) - value(a));
  const total = sorted.reduce((sum, i) => sum + value(i), 0);
  if (!total) return [];
  const scale = (box.w * box.h) / total;
  const out: (Rect & { item: T })[] = [];
  let rest = { ...box };
  let row: T[] = [];

  const worst = (candidate: T[], side: number) => {
    const areas = candidate.map((i) => value(i) * scale);
    const sum = areas.reduce((a, b) => a + b, 0);
    const max = Math.max(...areas);
    const min = Math.min(...areas);
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
  };

  const place = (items: T[]) => {
    const sum = items.reduce((a, i) => a + value(i) * scale, 0);
    const horizontal = rest.w >= rest.h;
    const thickness = horizontal ? sum / rest.h : sum / rest.w;
    let offset = 0;
    for (const item of items) {
      const length = (value(item) * scale) / thickness;
      out.push(
        horizontal
          ? { x: rest.x, y: rest.y + offset, w: thickness, h: length, item }
          : { x: rest.x + offset, y: rest.y, w: length, h: thickness, item },
      );
      offset += length;
    }
    rest = horizontal
      ? { x: rest.x + thickness, y: rest.y, w: rest.w - thickness, h: rest.h }
      : { x: rest.x, y: rest.y + thickness, w: rest.w, h: rest.h - thickness };
  };

  for (const item of sorted) {
    const side = Math.min(rest.w, rest.h);
    if (!row.length || worst([...row, item], side) <= worst(row, side)) row.push(item);
    else {
      place(row);
      row = [item];
    }
  }
  if (row.length) place(row);
  return out;
}
