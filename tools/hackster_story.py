"""Make the paste-ready hackster.io story from docs/hackster-article.md.

hackster's editor takes neither relative links nor Markdown tables, so this
rewrites links and images to absolute GitHub URLs and turns each table into a
bullet list ("**first cell**: header: value; ...").

    python tools/hackster_story.py   # -> docs/submissions/hackster_story.md
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOB = "https://github.com/ljw22112/Edgeguard/blob/main/"
RAW = "https://raw.githubusercontent.com/ljw22112/Edgeguard/main/"


def absolute(target, image):
    if re.match(r"^[a-z]+://|^#|^mailto:", target):
        return target
    path = os.path.normpath(os.path.join("docs", target)).replace(os.sep, "/")
    return (RAW if image else BLOB) + path


def links(line):
    line = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", lambda m: f"![{m[1]}]({absolute(m[2], True)})", line)
    return re.sub(r"(?<!!)\[([^\]]*)\]\(([^)]+)\)", lambda m: f"[{m[1]}]({absolute(m[2], False)})", line)


def cells(row):
    return [c.strip() for c in row.strip().strip("|").split("|")]


def table_to_list(rows):
    head = cells(rows[0])
    out = []
    for r in rows[2:]:
        c = cells(r)
        first = c[0] if c[0] else "-"
        if not first.startswith("**"):
            first = f"**{first}**"
        rest = "; ".join(f"{h}: {v}" if h else v for h, v in zip(head[1:], c[1:]) if v)
        out.append(f"- {first}: {rest}" if rest else f"- {first}")
    return out


def convert(text):
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            j = i
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                j += 1
            out += table_to_list(lines[i:j])
            i = j
            continue
        out.append(lines[i])
        i += 1
    in_code, res = False, []
    for ln in out:
        if ln.startswith("```"):
            in_code = not in_code
        res.append(ln if in_code else links(ln))
    return "\n".join(res) + "\n"


def main():
    src = open(os.path.join(ROOT, "docs", "hackster-article.md"), encoding="utf-8").read()
    dst = os.path.join(ROOT, "docs", "submissions", "hackster_story.md")
    open(dst, "w", encoding="utf-8").write(convert(src))
    print("wrote", dst)


if __name__ == "__main__":
    main()
