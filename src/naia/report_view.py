"""Shared, script-free markup for the sandboxed report viewer."""

from html import escape
from urllib.parse import quote


def viewer_html(meta, *, back_url="/?view=reports", suite_url=None, task_url=None, edit_token=None):
    """Render a report wrapper; callbacks provide project-specific related links."""
    report_id = str(meta.get("id", ""))
    title = str(meta.get("title") or report_id or "Report")
    source = "/reports/" + quote(report_id, safe="") + "/index.html#theme=dark"

    def text(value):
        return escape(str(value), quote=True)

    def links(label, values, callback, view, key):
        if not isinstance(values, list) or not values:
            return ""
        entries = []
        for value in values:
            if not isinstance(value, str) or not value:
                continue
            href = callback(value) if callback else "/?view=" + view + "&" + key + "=" + quote(value, safe="")
            if href:
                entries.append('<a href="' + text(href) + '">' + text(value) + "</a>")
        if not entries:
            return ""
        return '<span class="nr-viewer-links"><span class="nr-viewer-label">' + label + "</span>" + "".join(entries) + "</span>"

    metadata = []
    date = meta.get("date")
    if isinstance(date, str) and date:
        metadata.append('<time datetime="' + text(date) + '">' + text(date) + "</time>")
    tags = meta.get("tags", [])
    if isinstance(tags, list):
        metadata.extend('<span class="nr-tag nr-tag-static">' + text(tag) + "</span>" for tag in tags if isinstance(tag, str) and tag)
    metadata.append(links("Suites", meta.get("suites", []), suite_url, "suites", "suite"))
    metadata.append(links("Tasks", meta.get("naia_tasks", []), task_url, "queue", "task"))

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>" + text(title) + " · NAIA</title>"
        '<link rel="stylesheet" href="/reports.css">'
        '<script src="/reports_viewer.js" defer></script></head>'
        '<body class="naia-report-viewer" data-theme="dark" data-report-id="' + text(report_id) + '"'
        + (' data-report-edit-token="' + text(edit_token) + '"' if edit_token else '') + '>'
        '<header class="nr-viewer-bar"><a id="reportBack" class="nr-viewer-back" href="' + text(back_url) + '">← NAIA</a>'
        '<div class="nr-viewer-title"><h1>' + text(title) + '</h1><div class="nr-viewer-meta">' + "".join(metadata) + "</div></div>"
        '<div class="nr-viewer-actions"><div class="nr-viewer-edit-controls" role="group" aria-label="Report editing">'
        '<button id="reportEdit" type="button" class="nr-control" disabled aria-describedby="reportEditStatus">Edit report</button>'
        '<button id="reportSave" type="button" class="nr-control nr-save" hidden disabled>Save</button>'
        '<button id="reportCancel" type="button" class="nr-control" hidden>Cancel</button>'
        '<span id="reportDirty" class="nr-edit-dirty" hidden>Unsaved changes</span></div>'
        '<button id="reportTheme" type="button" class="nr-control" aria-pressed="false">Theme: Dark</button>'
        '<a id="reportOpen" class="nr-control" href="' + text(source) + '" target="_blank" rel="noopener">Open alone ↗</a></div></header>'
        '<p id="reportEditStatus" class="nr-edit-status" role="status" aria-live="polite">'
        + ('Checking report editing…' if edit_token else 'Report editing is unavailable in this viewer.') + '</p>'
        '<main class="nr-viewer-content"><iframe id="reportFrame" title="' + text(title) + '" sandbox="allow-scripts allow-popups" src="' + text(source) + '"></iframe>'
        '<p id="reportViewerStatus" class="nr-viewer-status" role="status" aria-live="polite">Loading report…</p></main></body></html>'
    )
