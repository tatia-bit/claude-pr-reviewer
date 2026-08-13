# claude-pr-reviewer

A secondary AI reviewer for pull requests. On PR open it resolves the Jira ticket
named in the PR description, reads the diff against that ticket's **acceptance
criteria**, and posts three things:

1. **Line comments** on the diff.
2. **A requirements checklist** scored criterion by criterion against the ticket.
3. **Demo Q&A** — questions a PM or stakeholder is likely to ask, written for the
   person preparing the demo rather than for the PR author.

It does the thing human reviewers skip: a human skims a diff, but rarely re-reads
the acceptance criteria line by line and checks them off.

Built for **MRP25CCENT-17 (Story 5.2)**.

---

## How it's wired

The reviewer lives here once. Every repo that uses it holds only a trigger.

```
tatia-bit/claude-pr-reviewer                  ← this repo
  .github/workflows/review.yml                  reusable workflow (on: workflow_call)
  prompt/review-prompt.md                       THE prompt — the graded artifact
  scripts/post_review.py                        turns the model's JSON into a review
  scripts/jira_setup.py                         seeds a Jira project from ticket exports
  PROMPT-TUNING-LOG.md                          how the prompt changed, and why

<any reviewed repo>
  .github/workflows/claude-review.yml         ← ~20 lines, calls the above
```

This shape was a deliberate choice over copying the workflow into each repo. With
copies, "the prompt" stops being one thing: three repos drift apart, and the
tuning log stops describing anything real. With a reusable workflow, tuning the
prompt here changes every repo's next review with no propagation step, and
"installed across every repo" is one small file per repo.

The cost is one wrinkle: a job running in repo *X* has to fetch the prompt from
this repo. That's why **this repo is public** — a caller's default `GITHUB_TOKEN`
can check out a public repo, so there's no personal access token to provision and
rotate in every reviewed repo. Nothing sensitive lives here: no credentials, and
no ticket content (that's fetched from Jira at runtime).

### Installing it in a repo

Add `.github/workflows/claude-review.yml`:

```yaml
name: claude-pr-review

on:
  pull_request:
    types: [opened, labeled]

permissions:
  contents: read
  pull-requests: write
  issues: write
  id-token: write

jobs:
  review:
    if: >-
      github.event.action == 'opened' ||
      (github.event.action == 'labeled' && github.event.label.name == 'claude-review')
    uses: tatia-bit/claude-pr-reviewer/.github/workflows/review.yml@main
    secrets: inherit
```

**All four permissions are required**, and they must be set on the caller — a
reusable workflow can never hold more permission than the workflow calling it.
`id-token: write` is the non-obvious one: `claude-code-action` exchanges the
workflow's OIDC token to authenticate as the Claude GitHub App, and without it the
action fails with `Could not fetch an OIDC token`. `issues: write` covers the
posting script's fallback path, which comments through the issues endpoint when a
review carrying line anchors is rejected.

Then add two secrets and two variables:

| Kind | Name | Where it comes from |
|---|---|---|
| Secret | `CLAUDE_CODE_OAUTH_TOKEN` | `claude setup-token` locally (Claude Pro/Max) |
| Secret | `JIRA_API_TOKEN` | https://id.atlassian.com/manage-profile/security/api-tokens |
| Variable | `JIRA_BASE_URL` | e.g. `https://your-site.atlassian.net` |
| Variable | `JIRA_EMAIL` | the Atlassian account that can read the project |

```bash
gh variable set JIRA_BASE_URL --body "https://your-site.atlassian.net" --repo OWNER/REPO
gh variable set JIRA_EMAIL    --body "you@example.com"                 --repo OWNER/REPO
gh secret   set JIRA_API_TOKEN --repo OWNER/REPO           # paste at the prompt
gh secret   set CLAUDE_CODE_OAUTH_TOKEN --repo OWNER/REPO  # paste at the prompt
```

**The URL and email are variables, not secrets, on purpose.** Neither is
sensitive, and secrets are write-only — a typo in a secret is invisible and
resurfaces later as an unexplained HTTP 404 from Jira. As variables they can be
read back (`gh variable list`) and verified. Only genuine credentials are secrets.

Both resolve in the **calling** repo, so each reviewed repo needs its own copy.
The Jira three are optional — without them the reviewer still reviews the diff and
still writes demo questions, it just can't score a checklist, and says so.

Optional inputs, if a caller wants to pin or economise:

```yaml
    with:
      model: claude-opus-5      # default
      max_turns: 40             # runaway-cost guard
      reviewer_ref: main        # pin the prompt version
```

### Gating, and why it matters here

The workflow triggers on `opened` and on the `claude-review` label — **never on
`synchronize`**. Authentication is a Claude subscription token, so every run
spends personal usage quota rather than metered API credit. An ungated reviewer
firing on every push across several repos would quietly consume the same quota its
author needs for their own work. Re-running is a deliberate act: apply the label.

---

## The implementation choice, and what was rejected

The ticket pins the outcome, not the mechanism. Three routes were considered.

**Chosen — `anthropics/claude-code-action` with subscription OAuth.** No Anthropic
API key was available, and `claude-code-action` accepts a `CLAUDE_CODE_OAUTH_TOKEN`
minted by `claude setup-token` on a Pro/Max plan. It runs Claude Code on the
runner with the repository checked out, so the reviewer can read files the diff
doesn't show — which matters, because judging a diff against acceptance criteria
usually requires context the diff omits.

**Rejected — calling the Messages API directly.** This was the first choice on
technical merit: it supports `output_config.format`, which would have made the
three outputs a *schema guarantee* rather than a prompt instruction. It needs an
API key, and there isn't one. Recorded as the honest trade-off it is, not as a
design preference: the output shape here rests on prompt discipline, and a
malformed response degrades (see below) rather than being structurally impossible.

**Rejected — an off-the-shelf reviewer (CodeRabbit and similar).** No control over
the prompt, and no way to score against a specific Jira ticket's criteria. The
prompt *is* the deliverable here, so handing it to a vendor would remove the work.

### Claude writes JSON; the workflow posts it

Rather than trusting the model to drive `gh` correctly, the prompt requires a
single `review.json`, and `scripts/post_review.py` turns it into a GitHub review.
Posting is deterministic, and there's one place to handle failure:

| Situation | Behaviour |
|---|---|
| Valid JSON, comments anchor to changed lines | Full review with inline comments |
| GitHub rejects the anchors (422) | Same review, comments folded into the body |
| `review.json` missing or unparseable | Plain comment saying the reviewer failed |

Every path exits 0. A broken reviewer must not fail a PR's checks — a red X that
says nothing about the code is worse than no reviewer.

### When no ticket resolves

Four ways this happens: no key in the description, a malformed key, a key Jira
doesn't recognise, or Jira credentials missing. All four produce a review that
reviews the diff, writes demo questions, and is **explicitly labelled unscored**
with the reason. The model is instructed to return an empty requirements array
rather than inventing criteria — a plausible-looking checklist scored against
guessed criteria is worse than no checklist.

---

## Issues faced

**The real Jira was gone.** The tickets came from `312school.atlassian.net`, and
that account is now marked inactive by their admin — not recoverable from this
side. Rebuilt on a personal free Jira Cloud site instead, seeded from the `.doc`
exports with `scripts/jira_setup.py`.

**Jira issue keys can't be chosen, only earned.** The reviewer resolves
`MRP25CCENT-12` from an existing PR description, so the recreated tickets had to
land on their original numbers. Jira assigns numbers sequentially and **never
rewinds** — deleting issues doesn't free their numbers. The project already held a
few onboarding issues, so the script consumes one number as a probe to learn where
the counter sits, then creates the remaining tickets from there; everything from
the probe upward lands on its original key. Counting existing issues would have
been the obvious approach and is wrong: deletions leave gaps, so a count doesn't
tell you the counter's position.

**`GET /rest/api/2/search` returns 410 Gone.** Atlassian retired it. It was being
used to check whether the project was empty, and it failed *open* — the guard
silently did nothing. Replaced with a probe for `PROJECT-1`, which needs no search
endpoint at all, plus an abort on the first key that lands on an unexpected
number.

**Jira Cloud's REST v3 returns descriptions as ADF.** v3 gives `description` as an
Atlassian Document Format JSON tree, which would need flattening before a model
could read it. v2 returns plain text and still works on Cloud, so the fetch uses
v2 deliberately.

**A PR body is untrusted input.** Interpolating `${{ github.event.pull_request.body }}`
into a `run:` block lets anyone who opens a PR execute shell in the runner. It's
passed through `env:` and quoted instead.

**macOS blocked the setup script.** `Operation not permitted` running a script
from `~/Desktop` — the terminal lacked TCC access to that folder. Moved the files
rather than granting Full Disk Access.

---

## The prompt

`prompt/review-prompt.md` is the graded artifact, and
[`PROMPT-TUNING-LOG.md`](PROMPT-TUNING-LOG.md) records how it changed and why.

The decision worth reading first: the prompt tells the reviewer to **report every
finding without filtering for importance**, attaching `severity` and `confidence`
instead. That's deliberately counter-intuitive. Anthropic's model documentation
records that current models follow severity filters *literally* — told to report
only high-severity issues, a model investigates just as thoroughly, finds the
bugs, then withholds the ones it judges below the bar. Precision rises while
coverage silently falls. So coverage is requested here and ranking is pushed into
the fields, where a human or a later pass can filter without anything having been
hidden.
