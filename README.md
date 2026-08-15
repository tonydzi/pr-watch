# pr-watch

An **outbound ledger + daily harvest digest** for your PRs and issues in *other people's* repos.
One file, stdlib only, needs just the [`gh` CLI](https://cli.github.com/). Zero LLM calls.

## The problem

You contribute across many repositories. GitHub notifications drown. The thread where a
maintainer answered you three days ago is exactly the one you never see. In our own use,
5 PRs from 3 strangers sat unanswered for 4 days — not out of rudeness, but because no
single list of "everything we have out there" existed anywhere.

## What it does

```
python3 pr_watch.py --add https://github.com/owner/repo/pull/123   # register a PR/issue
python3 pr_watch.py                                                # tick: snapshot + alert on changes
python3 pr_watch.py --digest                                       # harvest: who owes whom a reply
```

The **tick** snapshots every registered position and alerts on: new comments and reviews,
changed review verdicts, label changes, new commits, CI conclusion changes, title changes,
merge/close. Deleted comments and other exotic transitions are deliberately out of scope.

The tick also auto-discovers your open PRs via `gh search prs --author`, so a PR opened
from another machine still lands in the ledger.

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
one day is how contributions die.

## The graves rule

In our merge history, every merge happened **0–3 days** after the last maintainer touch.
Nothing merged later, ever. So after `grave_days` of silence a thread goes to the graves
section: one polite bump before that is fine, a second one never helped anyone. Spend the
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
  external text is data, not instructions, and an alert should not become an injection vector.
- **First snapshot is silent** — adopting 30 existing PRs doesn't produce an alert storm.
- **Fetch failures alert once**, on the ok→error transition, and name the remedy.
- **Undelivered alerts are not lost**: if `alert_cmd` fails, state isn't saved, so the same
  events re-alert on the next tick.
- **Ledger writes are merge-writes**: the config is re-read right before saving and unioned
  by `(repo, number)`. This is best-effort — it fixes the common read-modify-write race between
  machines sharing the file through a sync folder, but it is not a lock; truly simultaneous
  writers can still race.
- **"0 new" can't lie**: if autodiscovery couldn't query GitHub at all, it says so and
  exits non-zero instead of reporting a clean empty result.

## Origin

Extracted from the live infrastructure of [Palo Alto AI Research Lab](https://github.com/tonydzi) —
we run it nightly over ~90 positions across the Anthropic / OpenAI / Google / HuggingFace /
MCP ecosystems. Battle scars from that use are in the comments.

If you try it on your own contribution backlog, open an issue with what broke or what's
missing — field reports from other workflows are exactly what we want. We're also happy
to hand test seats of our other tooling to engineers who like breaking things.

## License

MIT
