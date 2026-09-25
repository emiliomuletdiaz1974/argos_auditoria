// The Markdown of the runbooks, as React elements. Only what the book of operation uses: headings,
// paragraphs, lists, code blocks, inline code and bold. Nothing is ever inserted as raw HTML: a
// tag in the text is shown as text.
import type { ReactNode } from "react";

function inline(text: string, key: string): ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*)/g).filter(Boolean);
  return parts.map((part, n) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return <code key={`${key}-${n}`}>{part.slice(1, -1)}</code>;
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={`${key}-${n}`}>{part.slice(2, -2)}</strong>;
    }
    return part;
  });
}

const LIST_ITEM = /^\s*(?:(-)|\d+\.) (.*)$/;

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; ordered: boolean; items: string[] }
  | { kind: "code"; text: string };

function blocks(text: string): Block[] {
  const found: Block[] = [];
  const lines = text.split("\n");
  let n = 0;
  while (n < lines.length) {
    const line = lines[n]!;
    if (line.startsWith("```")) {
      const code: string[] = [];
      n += 1;
      while (n < lines.length && !lines[n]!.startsWith("```")) {
        code.push(lines[n]!);
        n += 1;
      }
      found.push({ kind: "code", text: code.join("\n") });
      n += 1;
      continue;
    }
    const heading = /^(#{1,4}) (.*)$/.exec(line);
    if (heading) {
      found.push({ kind: "heading", level: heading[1]!.length, text: heading[2]! });
      n += 1;
      continue;
    }
    const item = LIST_ITEM.exec(line);
    if (item) {
      const ordered = !item[1];
      const items: string[] = [];
      while (n < lines.length) {
        const next = LIST_ITEM.exec(lines[n]!);
        // A list ends at the first line that is not an item of the same kind.
        if (!next || !next[1] !== ordered) break;
        items.push(next[2]!);
        n += 1;
      }
      found.push({ kind: "list", ordered, items });
      continue;
    }
    if (line.trim() === "") {
      n += 1;
      continue;
    }
    const paragraph: string[] = [];
    while (n < lines.length && lines[n]!.trim() !== "" && !/^(#|```|\s*(-|\d+\.) )/.test(lines[n]!)) {
      paragraph.push(lines[n]!);
      n += 1;
    }
    found.push({ kind: "paragraph", text: paragraph.join(" ") });
  }
  return found;
}

const HEADINGS = ["h1", "h2", "h3", "h4"] as const;

export function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      {blocks(text).map((block, n) => {
        const key = `b${n}`;
        switch (block.kind) {
          case "heading": {
            const Tag = HEADINGS[block.level - 1] ?? "h4";
            return <Tag key={key}>{inline(block.text, key)}</Tag>;
          }
          case "list": {
            const items = block.items.map((item, i) => <li key={`${key}-${i}`}>{inline(item, `${key}-${i}`)}</li>);
            return block.ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>;
          }
          case "code":
            return (
              <pre key={key}>
                <code>{block.text}</code>
              </pre>
            );
          default:
            return <p key={key}>{inline(block.text, key)}</p>;
        }
      })}
    </div>
  );
}
