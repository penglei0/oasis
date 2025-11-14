#!/usr/bin/env python3
import os
import sys
import html
import re
from pathlib import Path


def build_topology_map(tops):
    """
    Build map: (loss_float, latency_int) -> topology_num (string)
    reads topology_description.txt under each topology dir.
    """
    topo_map = {}
    for t in tops:
        desc_file = t / "topology_description.txt"
        if not desc_file.exists():
            continue
        desc = desc_file.read_text(encoding="utf-8")
        # find loss (e.g. loss 2% or loss 2.0%)
        m_loss = re.search(r"loss\s+(\d+(?:\.\d+)?)\s*%", desc)
        m_lat = re.search(r"latency\s+(\d+)\s*ms", desc)
        if not m_loss or not m_lat:
            continue
        loss = float(m_loss.group(1))
        # normalize loss to one decimal to match table like "2.0%"
        loss_norm = round(loss, 1)
        lat = int(m_lat.group(1))
        m = re.match(r'^topology-(\d+)$', t.name)
        if m:
            topo_map[(loss_norm, lat)] = m.group(1)
    return topo_map


def render_throughput_table(md: str, topo_map):
    """
    Parse the markdown throughput table and render an HTML table.
    Link each numeric cell to corresponding topology anchor if found.
    """
    import re
    lines = [ln.strip() for ln in md.splitlines() if ln.strip()]
    table_lines = [ln for ln in lines if ln.startswith("|")]
    if not table_lines:
        return "<pre>{}</pre>".format(html.escape(md))

    header = [c.strip() for c in table_lines[0].strip().strip("|").split("|")]
    latencies = []
    for h in header[1:]:
        m = re.match(r"(\d+)\s*ms", h)
        latencies.append(int(m.group(1)) if m else None)

    data_rows = []
    for ln in table_lines[1:]:
        if re.match(r'^\|\s*-+', ln):  # separator row
            continue
        cols = [c.strip() for c in ln.strip().strip("|").split("|")]
        data_rows.append(cols)

    html_t = ["<table>"]
    html_t.append("<thead><tr>")
    for col in header:
        html_t.append(f"<th>{html.escape(col)}</th>")
    html_t.append("</tr></thead>")
    html_t.append("<tbody>")
    for row in data_rows:
        if not row:
            continue
        loss_txt = row[0]
        m_loss = re.match(r'(\d+(?:\.\d+)?)\s*%', loss_txt)
        loss_val = round(float(m_loss.group(1)), 1) if m_loss else None
        html_t.append("<tr>")
        html_t.append(f"<td>{html.escape(loss_txt)}</td>")
        for i, cell in enumerate(row[1:]):
            lat = latencies[i] if i < len(latencies) else None
            link_html = html.escape(cell)
            if loss_val is not None and lat is not None:
                key = (loss_val, lat)
                topo_num = topo_map.get(key)
                if topo_num is not None:
                    anchor = f"topology-{topo_num}"
                    link_html = f"<a href='#{anchor}'>{html.escape(cell)}</a>"
            html_t.append(f"<td>{link_html}</td>")
        html_t.append("</tr>")
    html_t.append("</tbody></table>")
    return "\n".join(html_t)


def md_table_to_html(md: str) -> str:
    """
    Convert the first Markdown table in md to an HTML table.
    Simple implementation: lines starting with '|' are considered table rows.
    The separator row (|---|) is used to mark header/body split.
    """
    lines = md.splitlines()
    table_lines = []
    start = None
    for i, L in enumerate(lines):
        if L.strip().startswith("|"):
            if start is None:
                start = i
            table_lines.append(L.rstrip())
        elif start is not None:
            break
    if not table_lines:
        return "<pre>{}</pre>".format(html.escape(md))

    # normalize rows: remove leading/trailing '|', split by '|' and strip cells
    rows = []
    for L in table_lines:
        parts = [c.strip() for c in L.strip().strip("|").split("|")]
        rows.append(parts)

    # find separator row index (---)
    sep_idx = None
    for i, row in enumerate(rows):
        if all(re.match(r"^-{1,}\s*$", cell) for cell in row):
            sep_idx = i
            break

    html_table = ["<table>"]
    if sep_idx is None:
        # treat first row as header if no separator
        header = rows[0]
        html_table.append(
            "<thead><tr>{}</tr></thead>".format("".join(f"<th>{html.escape(h)}</th>" for h in header)))
        body_rows = rows[1:]
    else:
        header = rows[0]
        html_table.append(
            "<thead><tr>{}</tr></thead>".format("".join(f"<th>{html.escape(h)}</th>" for h in header)))
        body_rows = rows[sep_idx+1:]

    html_table.append("<tbody>")
    for r in body_rows:
        html_table.append(
            "<tr>{}</tr>".format("".join(f"<td>{html.escape(cell)}</td>" for cell in r)))
    html_table.append("</tbody></table>")
    return "\n".join(html_table)


def collect_topologies(base: Path):
    tops = []
    for entry in sorted(base.iterdir()):
        if entry.is_dir() and entry.name.startswith("topology-"):
            tops.append(entry)
    return tops


def read_text_file(p: Path):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def make_rel(a: Path, b: Path):
    try:
        return os.path.relpath(str(b), start=str(a))
    except Exception:
        return str(b)


def gather_logs_for_topology(top_dir: Path):
    # find relevant text/log files under topology dir, ignore .svg
    files = []
    for root, _, fnames in os.walk(top_dir):
        for f in sorted(fnames):
            if f.endswith(".svg"):
                continue
            # skip topology_description.txt (it's shown separately)
            if f == "topology_description.txt":
                continue
            if f.endswith(".log") or f.endswith(".txt") or f.endswith(".md"):
                files.append(Path(root) / f)
    return files


def gather_root_logs(base: Path):
    files = []
    for p in sorted(base.iterdir()):
        if p.is_file() and not p.name.endswith(".svg"):
            if p.name == "index.html":
                continue
            files.append(p)
    return files


def generate_index(base_dir: str):
    base = Path(base_dir).resolve()
    if not base.exists():
        print("ERROR: base dir not found:", base)
        return 2

    index_path = base / "index.html"
    tops = collect_topologies(base)
    root_files = gather_root_logs(base)
    throughput_md = base / "throughput_latency_loss.md"
    md_content = ""
    if throughput_md.exists():
        md_content = read_text_file(throughput_md)

    # build topology map for linking
    topo_map = build_topology_map(tops)

    html_lines = []
    html_lines.append("<!doctype html>")
    # ...existing code...
    html_lines.append(f"<h1>Test results: {html.escape(base.name)}</h1>")
    html_lines.append("<html lang='en'><head><meta charset='utf-8'>")
    html_lines.append(
        "<title>Test results index: {}</title>".format(html.escape(base.name)))
    html_lines.append("<style>body{font-family:Segoe UI,Arial,Helvetica,sans-serif;margin:20px}h1,h2{color:#003366}pre{background:#f7f7f7;padding:10px;border-radius:4px;overflow:auto}table{border-collapse:collapse;width:100%}th,td{padding:6px;border:1px solid #ddd;text-align:left}a.small{font-size:0.9em;color:#0066cc}</style>")
    html_lines.append("</head><body>")

    # throughput_md section - render with links to topologies
    if md_content:
        try:
            table_html = render_throughput_table(md_content, topo_map)
            html_lines.append("<h2>Throughput summary</h2>")
            html_lines.append(table_html)
        except Exception:
            html_lines.append("<pre>")
            html_lines.append(html.escape(md_content))
            html_lines.append("</pre>")
    # Per-topology sections
    for t in tops:
        # show topology name with an inline short summary (first non-empty line)
        desc = ""
        desc_file = t / "topology_description.txt"
        short = ""
        if desc_file.exists():
            desc = read_text_file(desc_file)
            # extract first non-empty line as short summary
            for ln in desc.splitlines():
                s = ln.strip()
                if s:
                    short = s
                    break
        m = re.match(r'^topology-(\d+)$', t.name)
        if m:
            num = m.group(1)
            display_name = f"{num}. topology"
        else:
            display_name = t.name
        if short:
            html_lines.append(
                f"<h2 id='{html.escape(display_name)}'>{html.escape(display_name)}</h2>")
        else:
            html_lines.append(
                f"<h2 id='{html.escape(display_name)}'>{html.escape(display_name)}</h2>")
        # if full description exists and has more than the short line, show it (no extra heading)
        html_lines.append("<h3>Description</h3>")
        if desc:
            html_lines.append("<pre>{}</pre>".format(html.escape(desc)))
        # list logs & relevant files
        files = gather_logs_for_topology(t)
        if files:
            html_lines.append("<h3>Files</h3>")
            html_lines.append(
                "<table><thead><tr><th>Path</th><th>Type</th></tr></thead><tbody>")
            for f in files:
                rel = make_rel(base, f)
                html_lines.append("<tr><td><a href='{}'>{}</a></td><td>{}</td></tr>".format(
                    html.escape(rel), html.escape(rel), html.escape(f.suffix.lstrip('.'))))
            html_lines.append("</tbody></table>")
        else:
            html_lines.append(
                "<p>No log/text files found in this topology (SVGs ignored).</p>")

    # footer
    html_lines.append("<hr><p>Generated by tools/generate_index.py</p>")
    html_lines.append("</body></html>")

    index_path.write_text("\n".join(html_lines), encoding="utf-8")
    print("Wrote", index_path)
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: generate_index.py <test_results_dir>")
        sys.exit(1)
    sys.exit(generate_index(sys.argv[1]))
