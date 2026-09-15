/** Display-only model: never mutates server nodes, edges, or saved positions. */
export interface ViewNode { id: string; parentId?: string; label: string; tags?: string[]; order: number }
export const normalizeSearch = (value: string) => value.normalize("NFC").trim().toLocaleLowerCase("en-US");

export function graphView<T extends ViewNode>(source: T[], query: string, tagIds: string[], collapsedIds: string[], focus?: string | null) {
  const byId = new Map(source.map(n => [n.id, n]));
  const nodes = [...byId.values()];
  const children = new Map<string, T[]>();
  for (const n of nodes) {
    const parent = n.parentId && byId.has(n.parentId) ? n.parentId : "";
    const list = children.get(parent) ?? []; list.push(n); children.set(parent, list);
  }
  for (const list of children.values()) list.sort((a, b) => a.order - b.order || a.id.localeCompare(b.id, "en", { numeric: true }));
  const text = normalizeSearch(query);
  const filtering = !!text || tagIds.length > 0;
  const matches = new Set(nodes.filter(n => (!text || normalizeSearch(n.label).includes(text)) &&
    (!tagIds.length || n.tags?.some(t => tagIds.includes(t)))).map(n => n.id));
  const ancestors = (id: string, into: Set<string>) => {
    const seen = new Set<string>();
    let parent = byId.get(id)?.parentId;
    while (parent && byId.has(parent) && !seen.has(parent)) {
      seen.add(parent); into.add(parent); parent = byId.get(parent)?.parentId;
    }
  };
  const context = new Set<string>();
  if (filtering) for (const id of matches) ancestors(id, context);
  const expanded = new Set<string>();
  if (filtering && focus && matches.has(focus)) ancestors(focus, expanded);
  const collapsed = new Set(collapsedIds.filter(id => byId.has(id)));
  const visible = new Set<string>();
  const ordered: T[] = [];
  const hiddenCounts = new Map<string, number>();
  // Iterative traversal stays bounded even if legacy data has cycles or missing parents.
  const seen = new Set<string>();
  const stack = [...(children.get("") ?? [])].reverse().map(n => ({ n, hidden: false }));
  while (stack.length) {
    const { n, hidden } = stack.pop()!;
    if (seen.has(n.id)) continue;
    seen.add(n.id); ordered.push(n);
    if (!hidden && (!filtering || matches.has(n.id) || context.has(n.id))) visible.add(n.id);
    const hide = hidden || (collapsed.has(n.id) && !expanded.has(n.id));
    for (const child of [...(children.get(n.id) ?? [])].reverse()) stack.push({ n: child, hidden: hide });
  }
  // Count descendants once, bottom-up. Invalid cycles remain absent from the canvas.
  for (const n of [...ordered].reverse()) {
    hiddenCounts.set(n.id, (children.get(n.id) ?? []).reduce((sum, c) => sum + 1 + (hiddenCounts.get(c.id) ?? 0), 0));
  }
  return { nodes, ordered, visible, matches, context, collapsed, expanded, hiddenCounts, filtering,
    results: ordered.filter(n => matches.has(n.id)) };
}
