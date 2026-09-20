# pr-watch

An **outbound ledger + daily harvest digest** for your PRs and issues in *other people's* repos, in one file: [pr_watch.py](pr_watch.py).
One file, stdlib only, needs just the [`gh` CLI](https://cli.github.com/). Zero LLM calls.

## The problem

You contribute across many repositories. GitHub notifications drown. The thread where a
maintainer answered you three days ago is exactly the one you never see. In our own use in 2026, 5 PRs from 3 strangers sat unanswered for 4 days — not out of rudeness, but because no single list of "everything we have out there" existed anywhere.

## What it does

```
python3 pr_watch.py --add https://github.com/owner/repo/pull/123   # register a PR/issue
python3 pr_watch.py                                                # tick: snapshot + alert on changes
python3 pr_watch.py --digest                                       # harvest: who owes whom a reply
```

The **tick** in [pr_watch.py](pr_watch.py) snapshots every registered position and alerts on: new comments and reviews, changed review verdicts, label changes, new commits, CI conclusion changes, title changes, merge/close. Deleted comments and other exotic transitions are deliberately out of scope.

The tick also auto-discovers your open PRs via `gh search prs --author`, so a PR opened from another machine still lands in the ledger kept by [pr_watch.py](pr_watch.py).

The **digest** reads only saved snapshots (0 network calls) and splits the ledger into:

```
harvest 2026-08-15 — 91 positions in the ledger
BALL WITH US (7):
- agno-agi/agno#9570 — last word by bunnysayzz (0d) — THE BALL IS WITH YOU
...
moved in the last day (5):
waiting on them (24):
graves (silent > 3d — no more bumps) (35):
closed (17):
```

**BALL WITH US** is the section that matters: a human wrote after you, and silence past
one day is how contributions die, which is the whole reason [pr_watch.py](pr_watch.py) exists.

## The graves rule

In our own merge history through 2026, every merge happened **0–3 days** after the last maintainer touch.
Nothing merged later, ever. So after the `grave_days` window set in [pr_watch.py](pr_watch.py) a thread goes to the graves section: one polite bump before that is fine, a second one never helped anyone. Spend the
time on living threads instead. Tune `grave_days` if your ecosystem is slower.

## Setup

1. Install and authenticate [`gh`](https://cli.github.com/) (`gh auth login`; for cron
   set `GH_TOKEN` to a read-only token).
2. Create `~/.pr_watch.json`:

```json
{
  "authors": ["your-github-login"],
  "grave_days": 3,
  "alert_cmd": "",
  "prs": []
}
```

3. Register what you already have out there: `python3 pr_watch.py --sync`
4. Cron it (tick nightly, digest in the morning):

```
40 3 * * *  python3 /path/to/pr_watch.py
0  9 * * *  python3 /path/to/pr_watch.py --digest --send
```

`alert_cmd` is any shell command; the alert text arrives on **stdin**, so use commands that
read stdin: `mail -s pr-watch me@example.com`, `curl --data-binary @- <your-webhook-url>`,
or your own script. Empty = print to stdout (fine for cron with mail delivery).

## Design decisions

- **Comment bodies are never stored or relayed.** Snapshots keep only id/author/date —
  external text is data, not instructions, and an alert should not become an injection vector; the rule is enforced in [pr_watch.py](pr_watch.py) and covered by [test_pr_watch.py](test_pr_watch.py).
- **First snapshot is silent** — adopting 30 existing PRs doesn't produce an alert storm.
- **Fetch failures alert once**, on the ok→error transition, and name the remedy.
- **Undelivered alerts are not lost**: if `alert_cmd` fails, state isn't saved, so the same
  events re-alert on the next tick.
- **Ledger writes are merge-writes**: the config is re-read right before saving and unioned
  by `(repo, number)`. This is best-effort — it fixes the common read-modify-write race between
  machines sharing the file through a sync folder, but it is not a lock; truly simultaneous
  writers can still race.
- **"0 new" can't lie**: if autodiscovery couldn't query GitHub at all, [pr_watch.py](pr_watch.py) says so and
  exits non-zero instead of reporting a clean empty result.

## Origin

Extracted from the live infrastructure of [Palo Alto AI Research Lab](https://github.com/tonydzi) —
we run it nightly over ~90 positions across the Anthropic / OpenAI / Google / HuggingFace /
MCP ecosystems. Battle scars from that use are in the comments.

If you try it on your own contribution backlog, open an issue at https://github.com/tonydzi/pr-watch/issues with what broke or what's missing — field reports from other workflows are exactly what we want. We're also happy
to hand test seats of our other tooling to engineers who like breaking things.

## License

MIT

---

<!--ecosystem-map:start-->

## 🧩 One piece of a working system

This repository is one piece lifted out of a live operation: one non-technical founder, an AI
cofounder, and a fleet of machines that reach consensus with each other and wake the human only
for money or the irreversible. It was extracted after it survived production, not written as a
demo — and it runs on its own: nothing here phones home to the rest.

**See how the whole thing fits together → [SYSTEM.md](https://github.com/tonydzi/tonydzi/blob/main/SYSTEM.md)**

<!--ecosystem-map:end-->

## AI contributors

This project is built by a human + AI team, and the git log says so under the rules in
[AI-CONTRIBUTORS.md](https://github.com/tonydzi/.github/blob/main/AI-CONTRIBUTORS.md): Claude writes most of
the code, Codex and Grok review it, Gemini feeds the research. Each is credited on a commit
**only if its output changed that commit's content** — no decorative credits. Lab-wide
policy, one source for every repo: [AI-CONTRIBUTORS.md](https://github.com/tonydzi/.github/blob/main/AI-CONTRIBUTORS.md).

<!-- READ-WITH-AI:START (generated by read_with_ai.py - do not hand-edit) -->

### READ THIS WITH AI

One click and an agent reads the repo, pulls out the patterns and helps you apply them to your own work.

<a href="https://chatgpt.com/codex?prompt=Read%20this%20repo%3A%20https%3A%2F%2Fgithub.com%2Ftonydzi%2Fpr-watch%20%28%E2%80%9Cpr-watch%E2%80%9D%20-%20Outbound%20ledger%20%2B%20daily%20harvest%20digest%20for%20your%20PRs%20and%20issues%20in%20other%20people%27s%20repos.%20One%20file%2C%20stdlib%2C%20gh%20CLI%2C%20zero%20LLM%29.%20Work%20out%20what%20problem%20it%20actually%20solves%2C%20pull%20out%20the%20reusable%20patterns%20and%20help%20me%20apply%20them%20to%20my%20own%20setup.%20Start%20by%20asking%20what%20I%20am%20working%20on."><img alt="Codex - open" src="https://img.shields.io/badge/Codex-open-000000?style=for-the-badge&logo=openai&logoColor=white"></a> <a href="https://chatgpt.com/?q=Read%20this%20repo%3A%20https%3A%2F%2Fgithub.com%2Ftonydzi%2Fpr-watch%20%28%E2%80%9Cpr-watch%E2%80%9D%20-%20Outbound%20ledger%20%2B%20daily%20harvest%20digest%20for%20your%20PRs%20and%20issues%20in%20other%20people%27s%20repos.%20One%20file%2C%20stdlib%2C%20gh%20CLI%2C%20zero%20LLM%29.%20Work%20out%20what%20problem%20it%20actually%20solves%2C%20pull%20out%20the%20reusable%20patterns%20and%20help%20me%20apply%20them%20to%20my%20own%20setup.%20Start%20by%20asking%20what%20I%20am%20working%20on."><img alt="ChatGPT - open" src="https://img.shields.io/badge/ChatGPT-open-10a37f?style=for-the-badge&logo=openai&logoColor=white"></a> <a href="https://claude.ai/new?q=Read%20this%20repo%3A%20https%3A%2F%2Fgithub.com%2Ftonydzi%2Fpr-watch%20%28%E2%80%9Cpr-watch%E2%80%9D%20-%20Outbound%20ledger%20%2B%20daily%20harvest%20digest%20for%20your%20PRs%20and%20issues%20in%20other%20people%27s%20repos.%20One%20file%2C%20stdlib%2C%20gh%20CLI%2C%20zero%20LLM%29.%20Work%20out%20what%20problem%20it%20actually%20solves%2C%20pull%20out%20the%20reusable%20patterns%20and%20help%20me%20apply%20them%20to%20my%20own%20setup.%20Start%20by%20asking%20what%20I%20am%20working%20on."><img alt="Claude - open" src="https://img.shields.io/badge/Claude-open-d97757?style=for-the-badge&logo=anthropic&logoColor=white"></a>

<details>
<summary>Copy the prompt (works in any agent: Gemini, Grok, a local model, your own CLI)</summary>

```text
Read this repo: https://github.com/tonydzi/pr-watch (“pr-watch” - Outbound ledger + daily harvest digest for your PRs and issues in other people's repos. One file, stdlib, gh CLI, zero LLM). Work out what problem it actually solves, pull out the reusable patterns and help me apply them to my own setup. Start by asking what I am working on.
```

</details>

<sub>— TonyDzi, Palo Alto AI Research Lab · second brain, agent coordination, persistent memory: github.com/tonydzi</sub>

<!-- READ-WITH-AI:END -->
