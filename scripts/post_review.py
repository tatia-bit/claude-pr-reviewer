#!/usr/bin/env python3
"""Turn review.json into a GitHub pull request review.

Claude produces the content; this script owns the posting. Keeping the two apart
means the output shape is enforced by code rather than by hoping the model drives
`gh` correctly, and it gives us one place to degrade gracefully when it doesn't.

Degradation ladder, so a failure is always visible and never silent:
  1. Valid JSON, line comments anchor cleanly  -> full review with inline comments
  2. GitHub rejects the inline comments (422)  -> same review, comments in the body
  3. review.json missing or unparseable       -> plain comment saying so
Every path exits 0: a broken reviewer must not fail the PR's checks.
"""

from __future__ import annotations  # keeps the `X | None` annotations valid on 3.9

import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"
REPO = os.environ["GITHUB_REPOSITORY"]
PR = os.environ["PR_NUMBER"]
TOKEN = os.environ["GH_TOKEN"]
KEY = os.environ.get("TICKET_KEY") or ""
RESOLVED = os.environ.get("TICKET_RESOLVED") == "true"

STATUS_MARK = {
    "met": "met",
    "partial": "partial",
    "missing": "MISSING",
    "not-verifiable": "not verifiable from the diff",
}


def post(path: str, payload: dict) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{API}{path}",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def comment(body: str) -> None:
    status, detail = post(f"/repos/{REPO}/issues/{PR}/comments", {"body": body})
    print(f"issue comment -> HTTP {status}")
    if status >= 300:
        print(detail, file=sys.stderr)


def load() -> dict | None:
    try:
        with open("review.json", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print("review.json not found", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"review.json is not valid JSON: {e}", file=sys.stderr)
        return None
    return data if isinstance(data, dict) else None


def render_body(data: dict) -> str:
    reqs = data.get("requirements") or []
    qa = data.get("demo_qa") or []
    comments = data.get("line_comments") or []

    out = ["## Claude review"]

    if RESOLVED and KEY:
        out.append(f"Reviewed against **{KEY}**.")
    elif KEY:
        out.append(
            f"**Unscored.** A ticket key (`{KEY}`) was found in the description but "
            "could not be fetched from Jira, so there are no acceptance criteria to "
            "score against. The diff review and demo questions below still apply."
        )
    else:
        out.append(
            "**Unscored.** No Jira issue key was found in the pull request "
            "description, so there are no acceptance criteria to score against. "
            "The diff review and demo questions below still apply."
        )

    if reqs:
        met = sum(1 for r in reqs if r.get("status") == "met")
        out += [
            "",
            f"### Requirements — {met}/{len(reqs)} met",
            "",
            "| Status | Criterion | Evidence |",
            "|---|---|---|",
        ]
        for r in reqs:
            mark = STATUS_MARK.get(r.get("status", ""), r.get("status", "?"))
            crit = str(r.get("criterion", "")).replace("|", "\\|").replace("\n", " ")
            ev = str(r.get("evidence", "")).replace("|", "\\|").replace("\n", " ")
            out.append(f"| {mark} | {crit} | {ev} |")

    if qa:
        out += ["", "### Demo questions to be ready for", ""]
        for item in qa:
            out.append(f"- **{item.get('question', '')}**")
            if item.get("why"):
                out.append(f"  <br>{item['why']}")

    if comments:
        out += ["", f"{len(comments)} inline comment(s) on the diff."]
    else:
        out += ["", "No issues found in the diff."]

    out += ["", "<sub>Automated secondary review. A human still reviews this PR.</sub>"]
    return "\n".join(out)


def to_review_comments(data: dict) -> list[dict]:
    result = []
    for c in data.get("line_comments") or []:
        path, line = c.get("path"), c.get("line")
        if not path or not isinstance(line, int):
            print(f"dropping comment with bad anchor: {c!r}", file=sys.stderr)
            continue
        sev = c.get("severity", "?")
        conf = c.get("confidence", "?")
        result.append({
            "path": path,
            "line": line,
            "side": "RIGHT",
            "body": f"**{sev} severity** · confidence: {conf}\n\n{c.get('comment', '')}",
        })
    return result


def main() -> int:
    data = load()
    if data is None:
        comment(
            "## Claude review — failed\n\n"
            "The reviewer did not produce a readable `review.json`, so there is "
            "nothing to report. This is a reviewer failure, not a finding about "
            "this PR — check the workflow logs.\n\n"
            "<sub>Automated secondary review.</sub>"
        )
        return 0

    body = render_body(data)
    inline = to_review_comments(data)

    status, detail = post(
        f"/repos/{REPO}/pulls/{PR}/reviews",
        {"body": body, "event": "COMMENT", "comments": inline},
    )
    print(f"review (with {len(inline)} inline comments) -> HTTP {status}")
    if status < 300:
        return 0

    # 422 is the common case: a comment anchored to a line not in the diff.
    # Don't lose the findings — fold them into the body and post without anchors.
    print(detail, file=sys.stderr)
    print("retrying without inline comments", file=sys.stderr)

    if inline:
        body += "\n\n### Inline comments\n"
        body += (
            "\n_Posted here rather than on the diff: GitHub rejected the line "
            "anchors, usually because a comment referenced a line this diff did "
            "not change._\n"
        )
        for c in inline:
            body += f"\n- `{c['path']}:{c['line']}` — {c['body']}\n"

    status, detail = post(
        f"/repos/{REPO}/pulls/{PR}/reviews", {"body": body, "event": "COMMENT"}
    )
    print(f"review (body only) -> HTTP {status}")
    if status >= 300:
        print(detail, file=sys.stderr)
        comment(body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
