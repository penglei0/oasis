#!/usr/bin/env python3
"""Generate a static index for the multipath benchmark result sets."""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote


PATH_LINE = re.compile(r"^(rpath|dpath):\s*(.+?)\s*$", re.IGNORECASE)
TOPOLOGY_NUMBER = re.compile(r"topology-(\d+)$")


@dataclass(frozen=True)
class ResultRef:
    category: str
    root: Path
    topology_dir: Path
    topology_id: str
    description: str
    paths: dict[str, str]

    @property
    def key(self) -> tuple[str, str] | None:
        if "rpath" not in self.paths or "dpath" not in self.paths:
            return None
        return self.paths["rpath"], self.paths["dpath"]


def canonical_setup(value: str) -> str:
    """Normalize setup text while preserving its meaningful values."""
    return re.sub(r"\s+", " ", value.strip())


def read_result(root: Path, category: str, topology_dir: Path) -> ResultRef | None:
    description_file = topology_dir / "topology_description.txt"
    if not description_file.is_file():
        return None
    description = description_file.read_text(encoding="utf-8", errors="replace")
    paths: dict[str, str] = {}
    for line in description.splitlines():
        match = PATH_LINE.match(line.strip())
        if match:
            paths[match.group(1).lower()] = canonical_setup(match.group(2))
    topology_match = TOPOLOGY_NUMBER.match(topology_dir.name)
    topology_id = topology_match.group(1) if topology_match else topology_dir.name
    return ResultRef(category, root, topology_dir, topology_id, description, paths)


def collect_results(results_dir: Path, category: str) -> list[ResultRef]:
    category_dir = results_dir / category
    if not category_dir.is_dir():
        return []
    results = []
    for topology_dir in sorted(
            (p for p in category_dir.iterdir() if p.is_dir()),
            key=lambda p: (int(TOPOLOGY_NUMBER.match(p.name).group(1))
                           if TOPOLOGY_NUMBER.match(p.name) else 10**9, p.name)):
        result = read_result(results_dir, category, topology_dir)
        if result and result.key:
            results.append(result)
    return results


def rel_url(from_dir: Path, target: Path) -> str:
    return quote(os.path.relpath(target, from_dir), safe="/._-()")


def result_link(report_dir: Path, target: Path, label: str) -> str:
    return (f"<a href='{html.escape(rel_url(report_dir, target), quote=True)}'>"
            f"{html.escape(label)}</a>")


def setup_label(setup: str) -> str:
    match = re.search(
        r"bandwidth\s+([^,]+),\s*latency\s+([^,]+),\s*loss\s+([^,]+),",
        setup,
        re.IGNORECASE,
    )
    if not match:
        return setup.replace(",", ", ")
    bandwidth, one_way_delay, loss = (part.strip() for part in match.groups())
    try:
        rtt = f"{float(one_way_delay.rstrip('ms')) * 2:g}ms"
    except ValueError:
        rtt = one_way_delay
    return f"BW {bandwidth}, RTT {rtt}, loss {loss}"


def short_description(result: ResultRef, include_rpath: bool = True) -> str:
    lines = []
    display_names = {
        "dpath": "直连路径(dpath)",
        "rpath": "中继路径(rpath)",
    }
    for name in ("dpath", "rpath"):
        if name == "rpath" and not include_rpath:
            continue
        if name in result.paths:
            lines.append(f"{display_names[name]}: {setup_label(result.paths[name])}")
    return "\n".join(lines)


def watermark_text(result: ResultRef) -> str:
    """Return compact path attributes for the SVG watermark."""
    values = []
    setup_pattern = re.compile(
        r"bandwidth\s+([^,]+),\s*latency\s+([^,]+),\s*loss\s+([^,]+)",
        re.IGNORECASE,
    )
    path_names = (("dpath",) if "single_path" in result.category
                  else ("dpath", "rpath"))
    for path_name in path_names:
        setup = result.paths.get(path_name)
        if not setup:
            continue
        match = setup_pattern.search(setup)
        if match:
            values.append(" ".join(part.strip() for part in match.groups()))
    return " | ".join(values)


def watermarked_svg(report_dir: Path, result: ResultRef, svg: Path) -> Path:
    """Copy an SVG into the report and add a subtle topology watermark."""
    relative = svg.relative_to(result.topology_dir)
    target = (report_dir / "svg_assets" / result.category /
              result.topology_dir.name / relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    content = svg.read_text(encoding="utf-8", errors="replace")
    text = html.escape(watermark_text(result), quote=True)
    if text and "benchmark-watermark" not in content:
        viewbox = re.search(
            r"<svg\b[^>]*\bviewBox\s*=\s*['\"]\s*"
            r"([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s+"
            r"([-+]?\d*\.?\d+)\s+([-+]?\d*\.?\d+)\s*['\"]",
            content,
            re.IGNORECASE,
        )
        if viewbox:
            min_x, min_y, width, height = (
                float(value) for value in viewbox.groups())
        else:
            min_x, min_y, width, height = 0.0, 0.0, 100.0, 100.0
        center_x = min_x + width / 2
        center_y = min_y + height / 2
        watermark = (
            "<g id='benchmark-watermark' pointer-events='none' "
            f"opacity='0.22' transform='rotate(-24 {center_x:g} {center_y:g})'>"
            f"<text x='{center_x:g}' y='{center_y:g}' "
            "text-anchor='middle' dominant-baseline='middle' "
            "font-family='Arial,sans-serif' font-size='18' "
            "font-weight='600' fill='#5b6670'>"
            f"{text}</text></g>"
        )
        closing_tag = re.search(r"</svg\s*>\s*$", content, re.IGNORECASE)
        if closing_tag:
            content = content[:closing_tag.start()] + watermark + content[closing_tag.start():]
    target.write_text(content, encoding="utf-8")
    return target


def svg_card(report_dir: Path, result: ResultRef, svg: Path) -> str:
    label = str(svg.relative_to(result.topology_dir))
    packaged_svg = watermarked_svg(report_dir, result, svg)
    href = html.escape(rel_url(report_dir, packaged_svg), quote=True)
    chart_class = "chart"
    if "goodput_summary" in svg.stem:
        chart_class += " goodput-summary"
    elif "latency_distribution" in svg.stem:
        chart_class += " latency-distribution"
    return (
        f"<figure class='{chart_class}'>"
        f"<a href='{href}'><img src='{href}' alt='{html.escape(label, quote=True)}'></a>"
        f"<figcaption>{html.escape(label)}</figcaption></figure>")


def svg_gallery(report_dir: Path, result: ResultRef) -> str:
    svg_files = sorted(result.topology_dir.rglob("*.svg"))
    if not svg_files:
        return "<p class='muted'>No SVG results found.</p>"
    return "<div class='gallery'>" + "".join(
        svg_card(report_dir, result, svg) for svg in svg_files) + "</div>"


def comparison_gallery(report_dir: Path, multipath: ResultRef,
                       single_path: ResultRef) -> str:
    multi_svgs = {svg.name: svg for svg in multipath.topology_dir.rglob("*.svg")}
    single_svgs = {svg.name: svg for svg in single_path.topology_dir.rglob("*.svg")}
    names = sorted(set(multi_svgs) | set(single_svgs))
    if not names:
        return "<p class='muted'>No SVG results found.</p>"
    rows = []
    for name in names:
        panes = []
        if name in multi_svgs:
            panes.append("<div class='compare-pane'><h4>多路径</h4>" +
                         svg_card(report_dir, multipath, multi_svgs[name]) + "</div>")
        if name in single_svgs:
            panes.append("<div class='compare-pane'><h4>单路径</h4>" +
                         svg_card(report_dir, single_path, single_svgs[name]) + "</div>")
        rows.append("<div class='comparison-row'>" + "".join(panes) + "</div>")
    return "<div class='comparison-gallery'>" + "".join(rows) + "</div>"


def log_viewer(report_dir: Path, result: ResultRef, log_file: Path) -> Path:
    """Write a browser-renderable HTML view for one plain-text log."""
    relative = log_file.relative_to(result.root)
    viewer = report_dir / "log_pages" / Path(*relative.parts)
    viewer = viewer.with_name(viewer.name + ".html")
    viewer.parent.mkdir(parents=True, exist_ok=True)
    content = log_file.read_text(encoding="utf-8", errors="replace")
    viewer.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{html.escape(log_file.name)}</title>"
        "<style>body{margin:1rem;font-family:monospace}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>"
        f"<h1>{html.escape(str(relative))}</h1>"
        f"<pre>{html.escape(content)}</pre></body></html>",
        encoding="utf-8")
    return viewer


def oasis_log_viewer(report_dir: Path, log_file: Path) -> Path:
    """Write the top-level Oasis log as a browser-renderable HTML page."""
    viewer = report_dir / "log_pages" / "oasis.log.html"
    viewer.parent.mkdir(parents=True, exist_ok=True)
    content = log_file.read_text(encoding="utf-8", errors="replace")
    viewer.write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>oasis.log</title>"
        "<style>body{margin:1rem;font-family:monospace}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style></head><body>"
        "<h1>oasis.log</h1>"
        f"<pre>{html.escape(content)}</pre></body></html>",
        encoding="utf-8")
    return viewer


MARKDOWN_IMAGE = re.compile(r"!\[([^]]*)\]\(([^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
HTML_IMAGE = re.compile(r"(<img\b[^>]*?\bsrc\s*=\s*['\"])([^'\"]+)(['\"])", re.IGNORECASE)


def note_asset(results_dir: Path, report_dir: Path, reference: str) -> str:
    """Copy a local note image and return its report-relative URL."""
    if reference.startswith(("http://", "https://", "data:", "/")):
        return reference
    source = (results_dir / reference).resolve()
    try:
        source.relative_to(results_dir.resolve())
    except ValueError:
        return reference
    if not source.is_file():
        return reference
    target = report_dir / "html_assets" / source.relative_to(results_dir.resolve())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return quote(os.path.relpath(target, report_dir), safe="/._-()")


def render_report_note(results_dir: Path, report_dir: Path) -> str:
    """Render the optional Markdown/HTML note shown on the report index."""
    note_file = results_dir / "html.txt"
    if not note_file.is_file():
        return ""
    source = note_file.read_text(encoding="utf-8", errors="replace").strip()
    if not source:
        return ""

    def replace_markdown_image(match: re.Match[str]) -> str:
        alt, reference = match.groups()
        src = note_asset(results_dir, report_dir, reference)
        return (f"<img class='report-note-image' src='{html.escape(src, quote=True)}' "
                f"alt='{html.escape(alt, quote=True)}'>")

    def replace_html_image(match: re.Match[str]) -> str:
        src = note_asset(results_dir, report_dir, match.group(2))
        return f"{match.group(1)}{html.escape(src, quote=True)}{match.group(3)}"

    rendered_lines = []
    in_list = False
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("<"):
            if in_list:
                rendered_lines.append("</ul>")
                in_list = False
            rendered_lines.append(HTML_IMAGE.sub(replace_html_image, line))
            continue
        if not stripped:
            if in_list:
                rendered_lines.append("</ul>")
                in_list = False
            continue
        heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
        if heading:
            level, text = len(heading.group(1)), heading.group(2)
            rendered_lines.append(f"<h{level}>{html.escape(text)}</h{level}>")
            continue
        item = re.match(r"^[-*+]\s+(.+)$", stripped)
        if item:
            if not in_list:
                rendered_lines.append("<ul>")
                in_list = True
            rendered_lines.append(
                f"<li>{MARKDOWN_IMAGE.sub(replace_markdown_image, html.escape(item.group(1)))}</li>")
            continue
        if in_list:
            rendered_lines.append("</ul>")
            in_list = False
        escaped = html.escape(stripped)
        escaped = MARKDOWN_IMAGE.sub(replace_markdown_image, escaped)
        escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
        rendered_lines.append(f"<p>{escaped}</p>")
    if in_list:
        rendered_lines.append("</ul>")
    return "<section class='report-note'>" + "".join(rendered_lines) + "</section>"


def evidence_links(report_dir: Path, result: ResultRef) -> str:
    files = sorted(
        p for p in result.topology_dir.rglob("*")
        if p.is_file() and p.match("*.log"))
    if not files:
        return "<p class='muted'>No logs or evidence files found.</p>"
    links = []
    for path in files:
        relative = str(path.relative_to(result.topology_dir))
        links.append(
            f"<li>{result_link(report_dir, log_viewer(report_dir, result, path), relative)}</li>")
    return "<ul class='logs'>" + "".join(links) + "</ul>"


def result_block(report_dir: Path, result: ResultRef, title: str,
                 include_rpath: bool = True) -> str:
    description = html.escape(short_description(result, include_rpath))
    return (f"<article class='result'><h3>{html.escape(title)} "
            f"<span class='topology'>topology-{html.escape(result.topology_id)}</span></h3>"
            f"<pre>{description}</pre>{svg_gallery(report_dir, result)}"
            f"<p>{result_link(report_dir, result.topology_dir, 'Logs & Evidences')}</p>"
            f"{evidence_links(report_dir, result)}</article>")


def page_name(case_number: int, index: int) -> str:
    return f"case{case_number}-{index:03d}.html"


def comparison_block(report_dir: Path, multipath: ResultRef | None,
                     single_path: ResultRef, title: str) -> str:
    description = html.escape(short_description(multipath, include_rpath=True))
    if multipath is None:
        return result_block(report_dir, single_path, title, include_rpath=False)
    return (f"<article class='result'><h3>{html.escape(title)} "
            f"<span class='topology'>multi topology-{html.escape(multipath.topology_id)} / "
            f"single topology-{html.escape(single_path.topology_id)}</span></h3>"
            f"<pre>{description}</pre>"
            f"{comparison_gallery(report_dir, multipath, single_path)}"
            "<h4>多路径 Logs &amp; Evidences</h4>"
            f"{evidence_links(report_dir, multipath)}"
            "<h4>单路径 Logs &amp; Evidences</h4>"
            f"{evidence_links(report_dir, single_path)}</article>")


def page_html(
        report_dir: Path,
        key: tuple[str, str],
        multipath: dict[str, ResultRef],
        single_path: dict[str, ResultRef],
        index_file: Path,
        *,
        category_pairs: tuple[tuple[str, str, str], ...]) -> str:
    rpath, dpath = key
    parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        f"<title>HTTP benchmark: {html.escape(setup_label(rpath))} / "
        f"{html.escape(setup_label(dpath))}</title>",
        STYLE,
        "</head><body>",
        f"<p>{result_link(report_dir, index_file, 'Back to result matrix')}</p>",
        "<h2>多路径测试结果</h2>",
    ]
    for category, _single_category, title in category_pairs:
        multi_result = multipath.get(category)
        single_result = single_path.get(_single_category)
        if multi_result and single_result:
            parts.append(comparison_block(report_dir, multi_result, single_result, title))
        elif multi_result:
            parts.append(result_block(report_dir, multi_result, title))
        else:
            parts.append(f"<article class='result'><h3>{title}</h3>"
                         "<p class='muted'>Result not found.</p></article>")

    parts.append("</body></html>")
    return "\n".join(parts)


def matrix_html(keys: list[tuple[str, str]], pages: dict[tuple[str, str], str]) -> str:
    rpaths = sorted({key[0] for key in keys})
    dpaths = sorted({key[1] for key in keys})
    rows = ["<table class='matrix'><thead><tr><th>直连路径\\中继路径</th>"]
    rows.extend(f"<th>{html.escape(setup_label(rpath))}</th>" for rpath in rpaths)
    rows.append("</tr></thead><tbody>")
    for dpath in dpaths:
        rows.append(f"<tr><th>{html.escape(setup_label(dpath))}</th>")
        for rpath in rpaths:
            page = pages.get((rpath, dpath))
            if page:
                rows.append(f"<td><a href='{html.escape(page, quote=True)}'>"
                            "View results</a></td>")
            else:
                rows.append("<td class='empty'>-</td>")
        rows.append("</tr>")
    rows.append("</tbody></table>")
    return "\n".join(rows)


STYLE = """<style>
body{font-family:Arial,'Noto Sans SC',sans-serif;color:#20252b;margin:2rem;line-height:1.45}
h1,h2{color:#17324d}h2{border-bottom:2px solid #d7e1ea;padding-bottom:.35rem;margin-top:2rem}
a{color:#075da8}.muted{color:#68737d}.topology{font-size:.8em;color:#68737d}
pre{background:#f4f6f8;border:1px solid #d9e0e6;padding:.8rem;white-space:pre-wrap}
.report-note{margin:1rem 0}.report-note-image{display:block;max-width:100%;height:auto;margin:.75rem auto}
table{border-collapse:collapse;width:100%;margin:1rem 0}th,td{border:1px solid #ccd5dd;padding:.55rem;vertical-align:top;text-align:left}
th{background:#edf2f6}.matrix{font-size:.9rem}.matrix th{min-width:10rem}.matrix td{min-width:7rem;text-align:center}.empty{color:#9aa5ad;text-align:center!important}
.result{border:1px solid #d5dde5;padding:1rem;margin:1rem 0;background:#fbfcfd}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:1rem}
.gallery.vertical{display:flex;flex-direction:column;align-items:stretch}.gallery.vertical .chart{max-width:100%}
.chart{margin:0;border:1px solid #d5dde5;background:white;padding:.5rem}.chart img{display:block;max-width:100%;width:auto;height:auto;max-height:420px;margin:0 auto}.chart figcaption{font-size:.85rem;margin-top:.4rem;overflow-wrap:anywhere}
.chart.goodput-summary img{max-height:647px}.chart.latency-distribution img{max-height:454px}
.comparison-gallery{display:flex;flex-direction:column;gap:1.5rem;clear:both}.comparison-row{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));align-items:start;gap:1rem;min-width:0}.compare-pane{display:flex;flex-direction:column;align-items:stretch;min-width:0;min-height:0}.compare-pane h4{margin:.25rem 0 .6rem;color:#53616d}.compare-pane .chart{height:auto;min-height:0;box-sizing:border-box}
.logs{display:flex;flex-wrap:nowrap;gap:1.25rem;list-style:none;margin:.5rem 0;padding:0;white-space:nowrap}.logs li{margin:0}
.page-status{font:600 .9rem monospace;color:#53616d;margin-bottom:.75rem}
@media (max-width:800px){.comparison-row{grid-template-columns:1fr}}
</style>"""


PAGE_STATUS = """<div class='page-status' id='page-status'>Visitors: -- | Time on page: 00:00:00</div>
<script>
(function () {
  let visits = '--';
  const started = Date.now();
  const status = document.getElementById('page-status');
  function render() {
    const seconds = Math.floor((Date.now() - started) / 1000);
    const h = String(Math.floor(seconds / 3600)).padStart(2, '0');
    const m = String(Math.floor((seconds % 3600) / 60)).padStart(2, '0');
    const s = String(seconds % 60).padStart(2, '0');
    status.textContent = 'Visitors: ' + visits + ' | Time on page: ' + h + ':' + m + ':' + s;
  }
  async function updateVisitors(increment) {
    const suffix = increment ? '?increment=1' : '';
    try {
      const response = await fetch('/visitor-count' + suffix, {cache: 'no-store'});
      if (response.ok) visits = (await response.json()).count;
      render();
    } catch (_) {
      visits = 'unavailable';
      render();
    }
  }
  render();
  updateVisitors(true);
  setInterval(function () { updateVisitors(false); }, 5000);
  setInterval(render, 1000);
}());
</script>"""


def generate(results_dir: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_file = output_dir / "index.html"
    oasis_log = results_dir / "oasis.log"
    if oasis_log.is_file():
        # Keep the deployment self-contained and refresh the packaged log on
        # every report generation.
        shutil.copy2(oasis_log, output_dir / "oasis.log")
        oasis_log_viewer(output_dir, oasis_log)
    test_cases = (
        ("测试用例1", (
            ("http_goodput", "http_goodput_single_path", "HTTP goodput"),
            ("http_latency", "http_latency_single_path", "HTTP latency"),
        )),
        ("测试用例2(高时延)", (
            ("http_goodput_high_rtt", "http_goodput_single_path_high_rtt", "HTTP goodput"),
            ("http_latency_high_rtt", "http_latency_single_path_high_rtt", "HTTP latency"),
        )),
    )
    index_sections = []
    for case_number, (case_title, category_pairs) in enumerate(test_cases, 1):
        category_names = {name for pair in category_pairs for name in pair[:2]}
        categories = {
            name: collect_results(results_dir, name) for name in category_names
        }
        multipath_by_key: dict[tuple[str, str], dict[str, ResultRef]] = {}
        for category, _single_category, _title in category_pairs:
            for result in categories[category]:
                multipath_by_key.setdefault(result.key, {})[category] = result

        single_by_dpath: dict[str, dict[str, ResultRef]] = {}
        for _category, single_category, _title in category_pairs:
            for result in categories[single_category]:
                # A single-path sweep may contain several directories with
                # the same dpath but different unused rpath settings. Keep
                # one deterministic result for the dpath comparison.
                single_by_dpath.setdefault(result.paths["dpath"], {}).setdefault(
                    single_category, result)

        pages: dict[tuple[str, str], str] = {}
        for index, key in enumerate(sorted(multipath_by_key), 1):
            filename = page_name(case_number, index)
            pages[key] = filename
            single_matches = single_by_dpath.get(key[1], {})
            (output_dir / filename).write_text(
                page_html(output_dir, key, multipath_by_key[key], single_matches,
                          index_file, category_pairs=category_pairs), encoding="utf-8")

        keys = sorted(multipath_by_key)
        index_sections.extend([
            f"<h2>{html.escape(case_title)}</h2>",
            matrix_html(keys, pages),
        ])

    html_parts = [
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>",
        "<title>HTTP benchmark matrix</title>", STYLE,
        "</head><body>", PAGE_STATUS,
        "<h1>HTTP benchmark matrix</h1>",
        render_report_note(results_dir, output_dir),
        *index_sections,
        "<p class='oasis-log'>"
        "<a href='log_pages/oasis.log.html'>Oasis execution log (oasis.log)</a></p>",
        "</body></html>",
    ]
    index_file.write_text("\n".join(html_parts), encoding="utf-8")
    return index_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, default=Path("test_results"))
    parser.add_argument("--output-dir", type=Path,
                        default=Path("test_results/http_benchmark_report"))
    args = parser.parse_args()
    if not args.results_dir.is_dir():
        parser.error(f"results directory does not exist: {args.results_dir}")
    output = generate(args.results_dir.resolve(), args.output_dir.resolve())
    print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
