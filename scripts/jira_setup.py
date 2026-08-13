#!/usr/bin/env python3
"""Seed a fresh Jira project with the MRP25CCENT tickets, preserving issue keys.

Why the API instead of the CSV importer: Jira assigns issue numbers sequentially,
so creating the tickets in order into an EMPTY project yields exactly the original
keys (MRP25CCENT-9 for Versus, MRP25CCENT-12 for Serverless-memo) with no field
mapping to get wrong. Story 5.1's export was never in the tickets folder, so a
placeholder is created at position 16 purely to keep 17 and 18 aligned.

Uses REST v2 deliberately: on Jira Cloud, v2 accepts `description` as plain text,
while v3 requires Atlassian Document Format (a JSON tree).

Usage:
    python3 jira_setup.py            # diagnose only — safe, read-only
    python3 jira_setup.py --create   # create the issues

Credentials are prompted for and never written anywhere.
"""

import base64
import csv
import getpass
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE = "https://trazmadze89.atlassian.net"
PROJECT = "MRP25CCENT"
CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jira-import.csv")
PLACEHOLDER_AT = 16  # Story 5.1 — export not available
FIRST_NEEDED = 9     # MRP25CCENT-9 (Versus) is the lowest key any PR references


def request(method, path, auth, payload=None):
    url = f"{BASE}{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Basic {auth}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode()
            return resp.status, (json.loads(body) if body.strip() else {})
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"raw": body[:500]}
    except Exception as e:  # network, DNS, timeout
        return 0, {"error": str(e)}


def load_rows():
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    def num(r):
        return int(re.search(r"-(\d+)$", r["Issue Key"]).group(1))
    return sorted(rows, key=num)


def main():
    create = "--create" in sys.argv

    print(f"Site:    {BASE}")
    print(f"Project: {PROJECT}")
    email = input("Atlassian email: ").strip()
    token = getpass.getpass("API token (hidden): ").strip()
    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    print()

    # 1. Does the credential work at all?
    status, me = request("GET", "/rest/api/2/myself", auth)
    if status != 200:
        print(f"FAIL  auth: HTTP {status} — {me}")
        print("      Check the email matches the account that owns this site, and")
        print("      that the token was created while signed in as that account.")
        return 1
    print(f"OK    authenticated as {me.get('displayName')} <{me.get('emailAddress', email)}>")

    # 2. Does the project exist, and what issue type should we use?
    status, proj = request("GET", f"/rest/api/2/project/{PROJECT}", auth)
    if status != 200:
        print(f"FAIL  project {PROJECT}: HTTP {status} — {proj}")
        print("      Create a project whose key is exactly MRP25CCENT, then re-run.")
        return 1
    types = [t for t in proj.get("issueTypes", []) if not t.get("subtask")]
    if not types:
        print("FAIL  project has no non-subtask issue types")
        return 1
    chosen = next((t for t in types if t["name"] in ("Story", "Task")), types[0])
    print(f"OK    project '{proj.get('name')}' — using issue type '{chosen['name']}'")

    # 3. Is it already populated? Sequential keys only work from empty.
    #
    # Probing for issue #1 rather than searching: GET /rest/api/2/search now
    # returns 410 Gone on Jira Cloud, and the replacement search endpoints don't
    # report totals. Issue numbers start at 1 and are never reused, so a 404 on
    # PROJECT-1 means nothing has been created in this project.
    status, _ = request("GET", f"/rest/api/2/issue/{PROJECT}-1?fields=key", auth)
    if status == 404:
        empty = True
        print("OK    project is empty (no PROJECT-1)")
    elif status == 200:
        empty = False
        print(f"OK    {PROJECT}-1 already exists — project is not empty")
    else:
        empty = None
        print(f"WARN  could not determine whether the project is empty (HTTP {status})")

    # 4. Did a previous import already land the keys we need?
    for key in (f"{PROJECT}-9", f"{PROJECT}-12"):
        status, issue = request(
            "GET", f"/rest/api/2/issue/{key}?fields=summary,description", auth)
        if status == 200:
            desc = issue["fields"].get("description") or ""
            has_ac = "Acceptance criteria" in desc
            print(f"OK    {key} exists — {issue['fields']['summary'][:52]}")
            print(f"      description {len(desc)} chars, acceptance criteria: "
                  f"{'PRESENT' if has_ac else 'MISSING — reviewer cannot score against this'}")
        else:
            print(f"--    {key} does not exist yet (HTTP {status})")

    if not create:
        print("\nDiagnosis only. If the keys above are missing and the project is")
        print("empty, re-run with --create to seed them:")
        print("    python3 jira_setup.py --create")
        return 0

    if empty is None:
        print("\nREFUSING to create: could not reach the project to check its state.")
        return 1

    rows = load_rows()
    by_num = {int(re.search(r"-(\d+)$", r["Issue Key"]).group(1)): r for r in rows}
    highest = max(by_num)

    # Where does the counter sit? If the project is empty it's at 0. Otherwise the
    # only reliable way to find out is to consume one number and read it back:
    # numbers are never reused, and deletions leave gaps, so counting or scanning
    # existing issues can both mislead.
    if empty:
        start = 1
        print(f"\nProject is empty — creating keys 1..{highest} in order.\n")
    else:
        print("\nProject is not empty. Consuming one number to locate the counter...")
        status, res = request("POST", "/rest/api/2/issue", auth, {"fields": {
            "project": {"key": PROJECT},
            "summary": "(placeholder — created to align issue keys)",
            "description": "Disposable. Created only to discover where Jira's issue "
                           "counter sat, so that the real tickets land on their "
                           "original key numbers.",
            "issuetype": {"id": chosen["id"]},
        }})
        if status not in (200, 201):
            print(f"FAIL  probe issue: HTTP {status} — {res}")
            return 1
        probe = int(res["key"].rsplit("-", 1)[1])
        print(f"  {res['key']}  <- counter was here")
        start = probe + 1
        if start > FIRST_NEEDED:
            print(f"\nABORTING: the next key will be {PROJECT}-{start}, so "
                  f"{PROJECT}-{FIRST_NEEDED} can never be created in this project.")
            print("Create a fresh project and give it the key MRP25CCENT instead")
            print("(rename this project's key first so the name is free).")
            return 1
        print(f"\nCreating keys {start}..{highest}. Tickets below {start} are skipped —")
        print(f"none of them is referenced by a pull request.\n")

    failures = []
    for n in range(start, highest + 1):
        if n == PLACEHOLDER_AT and n not in by_num:
            summary = "Story 5.1 — (export not available)"
            description = ("Placeholder. This ticket's export was not present in the "
                           "source folder; the issue exists only so that subsequent "
                           "keys line up with the original numbering.")
        else:
            row = by_num.get(n)
            if row is None:
                summary = f"(placeholder {n})"
                description = "Placeholder to preserve issue numbering."
            else:
                summary, description = row["Summary"], row["Description"]

        status, res = request("POST", "/rest/api/2/issue", auth, {
            "fields": {
                "project": {"key": PROJECT},
                "summary": summary[:250],
                "description": description,
                "issuetype": {"id": chosen["id"]},
            }
        })
        if status in (200, 201):
            got = res.get("key", "?")
            print(f"  {got:<16} {summary[:56]}")
            # Abort immediately on a mismatch rather than creating 17 more issues
            # on the wrong numbers. Numbering never rewinds, so continuing cannot
            # recover — the fix is to clear the project and start over.
            if got != f"{PROJECT}-{n}":
                print(f"\nABORTING: expected {PROJECT}-{n} but Jira assigned {got}.")
                print("Issue numbering does not rewind, so the remaining keys cannot")
                print("line up. Delete every issue in the project and re-run.")
                return 1
        else:
            print(f"  FAILED at position {n}: HTTP {status} — {res}")
            failures.append(f"position {n}")
            break

    print()
    if failures:
        print("Finished with problems:", ", ".join(map(str, failures)))
        return 1
    print(f"Done. Check {BASE}/browse/{PROJECT}-12")
    return 0


if __name__ == "__main__":
    sys.exit(main())
