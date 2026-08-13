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

## Runs

Filled in as the reviewer runs on real PRs. What to capture each time: which PR,
which ticket, how many findings, how many were genuinely useful, and — the part
that matters — what in the prompt you changed as a result.

| Run | PR | Ticket | Findings | Useful | Checklist accuracy | Change made |
|---|---|---|---|---|---|---|
| | | | | | | |
