# Prompt-tuning log — MRP25CCENT-17 (Claude PR reviewer)

The record of how the review prompt changed and why. This is a graded artifact:
the point is not that the reviewer works, it's that its output became *useful
instead of noisy*, and that the reasoning behind each change is written down.

Every entry pairs a change with the observation that motivated it. Entries marked
**untested** are design decisions made before any real PR ran — they become
findings only once there's evidence.

---

## v1 — initial prompt

Written before the first run. Four decisions, each with a reason.

### 1. Report everything; filter downstream. **(untested — but grounded)**

The prompt explicitly tells the reviewer *not* to filter for importance or
confidence, and to attach `severity` and `confidence` to every finding instead.

This is deliberately the opposite of the instinctive framing ("only report what
matters"), and it isn't a guess. Anthropic's own model documentation records that
current models follow severity filters **literally**: told to report only
high-severity issues, the model investigates just as thoroughly, finds the bugs,
then declines to report the ones it judges below the bar. Precision rises and
measured recall falls, even though bug-finding did not get worse. The documented
fix is coverage-first reporting with filtering as a separate pass.

So v1 asks for coverage and pushes ranking into the fields. If the output turns
out too noisy in practice, the correct next move is a downstream filter or a
tighter definition of the bar — **not** re-adding "be conservative", which is the
change that would silently hide real findings.

### 2. A `not-verifiable` status, so the checklist can be honest. **(untested)**

Scoring a diff against acceptance criteria has two failure modes and both make
the checklist worthless: over-strict ("no test proves it → missing") fails every
PR and trains people to ignore the output; over-lenient ("the file exists → met")
rubber-stamps.

Several criteria on these tickets genuinely cannot be judged from a diff — "a
teammate signs up through the Cognito flow", "the PM agrees the output was
useful", anything demoed live. Without a fourth status the model must lie in one
direction or the other. `not-verifiable` lets it say *this needs a human to
observe it*, and name what they'd need to look at.

### 3. Demo Q&A is written for a different reader. **(untested)**

The ticket asks for questions the PM can use, not feedback for the author. The
prompt says so explicitly and constrains them to judgment questions — why this
choice over the alternative, why is this gap safe, what happens at the edge of
this boundary — rather than comprehension questions about what the code does.
Each carries a `why` naming what in the diff invites it, so the reader can trace
it.

### 4. Claude writes JSON; the workflow posts. **(untested)**

Not a prompt-quality decision, but it shapes the prompt. Because auth is a
subscription OAuth token through `claude-code-action`, the Messages API's
structured-output schema isn't available, so the prompt itself carries the output
contract. Posting stays in `post_review.py`, which means a malformed response
degrades visibly (comments folded into the body, or an explicit failure comment)
instead of producing a half-posted review.

**Cost of this approach, recorded honestly:** the three outputs are guaranteed by
prompt discipline rather than by a schema. An API-key implementation could have
used `output_config.format` and made the shape structurally impossible to get
wrong. That's a real trade-off accepted for auth reasons, not a design ideal.

---

## v2 — after run 1

Three changes, all caused by the first real output rather than anticipated.

### 1. Require claims to be grounded in evidence. **(fixes an observed error)**

Run 1's demo Q&A asserted that an exhausted token "fails the run before the
posting step can explain itself." That is false, and disprovably so: the posting
step runs on `if: always()`, and two `## Claude review — failed` comments from
earlier failed runs were sitting on the very PR being reviewed. The model reasoned
about a failure path from the diff instead of checking evidence already in front of
it.

This is the failure mode worth guarding against, because it is *confident* and
plausible — far more damaging in a review than a missed nit. The prompt now
requires claims about runtime behaviour to be checked against the repository and
the PR's own history, and requires any claim that couldn't be checked to say so.

### 2. Ticket resolution takes the strongest signal, not the first match. **(fixes a real defect)**

Run 1's own demo Q&A caught this: key extraction took the first `PROJ-123`-shaped
match anywhere in the PR body, so a description opening with "follows on from
MRP25CCENT-9" would have scored the diff against the wrong ticket's criteria — a
full, confident, wrong checklist. Worse than the no-ticket path, which at least
labels itself unscored.

Now a precedence chain: a Jira browse link, then an intent keyword
(`implements` / `closes` / `fixes` / `resolves` / `part of`), then a key at the
start of a line, then a bare match as a last resort. The run logs every key found
and which rule matched, so a mis-resolution is visible rather than silent. Not a
prompt change — but found by the prompt, which is the point.

### 3. Trigger and permission corrections. **(found by the reviewer, in its own caller)**

Run 1 flagged, correctly: `opened` fires for draft PRs, so a draft opened for early
feedback spent a full review; a PR created with the label already applied fires
both `opened` and `labeled`; and two of the caller's own justification comments were
inaccurate — the `issues: write` rationale described the wrong fallback path, and
the `id-token` rationale still cited GitHub App authentication after we'd switched
to passing `github_token` explicitly. All fixed in the caller.

---

## Runs

What to capture each time: which PR, which ticket, how many findings, how many were
genuinely useful, and — the part that matters — what changed as a result.

| Run | PR | Ticket | Findings | Useful | Checklist | Change made |
|---|---|---|---|---|---|---|
| 1 | serverless-memo #3 | MRP25CCENT-17 | 7 inline + 6 demo questions | 7/7 inline legitimate; 2 caught real errors in the caller's own comments | 4 met / 2 partial / 3 not-verifiable of 9 — matched my own reading, including marking this log **partial** | v2 §1–3 above |

### Run 1 in detail

**What went right.** The checklist was well calibrated. It refused to score "PM
agrees the output was useful" and named the evidence a human would need instead,
and it marked this log *partial* on the grounds that it "records what was decided,
not what was tried" — which was exactly true at the time.

**The report-everything instruction did not produce noise here** — 7 findings on a
26-line workflow file, all legitimate, two of them errors in comments I wrote
myself. A genuine result, but a weak test: this diff was dense configuration where
nearly every line carries an edge case. The instruction still needs testing against
a large, code-heavy diff, where volume is the real risk.

**What went wrong.** One confidently false claim about the failure path (§1). The
shape of the error matters more than the error: not a hallucinated fact, but a
plausible inference it didn't check. So the fix targets *checking*, not accuracy in
the abstract.

**Not yet tested at all:** the unscored path on a real PR with no ticket key; a diff
large enough to stress finding volume; and whether the `severity`/`confidence`
fields actually get used to filter, which is the entire justification for v1 §1.
