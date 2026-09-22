import type { NodeOut } from "./nodeApi";

export interface Tag {
  id: string;
  name: string;
  description?: string;
  color?: string;
  node_count: number;
  summary?: string;
}

export type NodeMeta = {
  id: string;
  label: string;
  pos_x: number;
  pos_y: number;
  parentId?: string;
  depth: number;
  order: number;
  opacity?: number;
  frozen?: boolean;
  status?: "ACTIVE" | "GHOST" | "ARCHIVED";
  generated?: boolean;
  tags?: string[];
  version: number;
  // 자동 크기 조절용
  width?: number;   // 👈 추가!
  height?: number;  // 👈 추가!
};

export function measureNodeSize(label: string, maxWidth = 220, font = "bold 18px Arial") {
  // 텍스트 줄수와 최대 가로길이에 따라 width, height 산출
  const canvas = document.createElement("canvas");
  const ctx = canvas.getContext("2d")!;
  ctx.font = font;

  // 줄 단위로 나누기 (text-wrap용)
  const words = label.split(' ');
  const lines: string[] = [];
  let curLine = '';

  for (const word of words) {
    const testLine = curLine ? curLine + ' ' + word : word;
    if (ctx.measureText(testLine).width > maxWidth && curLine) {
      lines.push(curLine);
      curLine = word;
    } else {
      curLine = testLine;
    }
  }
  if (curLine) lines.push(curLine);

  const widest = Math.max(...lines.map(l => ctx.measureText(l).width), 70);
  const width = Math.min(Math.max(widest + 40, 110), 350); // min/max clamp
  const height = lines.length * 26 + 30; // 한 줄 26px, +패딩

  return { width, height };
}

export function toNodeMeta(n: NodeOut, previous?: NodeMeta): NodeMeta {
  // GET snapshots can predate an already acknowledged PATCH or event.
  if (previous && previous.version > n.version) return previous;
  const { width, height } = measureNodeSize(n.content ?? "");
  return {
    id: String(n.id),
    label: n.content,
    pos_x: n.pos_x ?? 400 + Math.min(n.depth, 5) * 120,
    pos_y: n.pos_y ?? 300 + Math.min(n.order_index, 8) * 80,
    parentId: n.parent_id ? String(n.parent_id) : undefined,
    depth: n.depth,
    order: n.order_index,
    status: n.state,
    opacity: n.state === "GHOST" ? 0.3 : 1,
    frozen: n.state === "ACTIVE" ? true : previous?.frozen ?? true,
    generated: previous?.generated,
    version: n.version,
    width,
    height,
    tags: (n.tags ?? []).map(String),
  };
}
