#!/usr/bin/env python3
"""Offline tests for pr_watch.py — no network, no gh. Run: python3 test_pr_watch.py"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "pr_watch.py")


def run(args, env):
    return subprocess.run([sys.executable, SCRIPT] + args, capture_output=True,
                          text=True, env=env, cwd=tempfile.gettempdir())


def iso(days_ago):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days_ago * 86400))


def main():
    sys.path.insert(0, HERE)
    tmp = tempfile.mkdtemp(prefix="prwatch-test-")
    cfg_path = os.path.join(tmp, "pr_watch.json")
    state = os.path.join(tmp, "state")
    env = dict(os.environ, PR_WATCH_CONFIG=cfg_path, PR_WATCH_STATE=state)
    fails, total = [], [0]

    def check(name, cond):
        total[0] += 1
        print(("PASS" if cond else "FAIL") + " " + name)
        if not cond:
            fails.append(name)

    # 1. --add parses PR and issue urls, dedupes, survives a missing config file
    r = run(["--add", "https://github.com/o/r/pull/1",
             "https://github.com/o/r/issues/2", "not-a-url"], env)
    cfg = json.load(open(cfg_path))
    check("add: two rows from pr+issue urls", len(cfg["prs"]) == 2)
    check("add: bad url reported not crashed", "could not parse" in r.stdout and r.returncode == 0)
    r = run(["--add", "https://github.com/o/r/pull/1"], env)
    check("add: idempotent", "already in ledger" in r.stdout
          and len(json.load(open(cfg_path))["prs"]) == 2)

    # 2. digest classification: ball-with-us / graves / waiting / closed / bots
    cfg = {"authors": ["me"], "grave_days": 3, "prs": [
        {"repo": "o/r", "number": 1},   # stranger wrote last -> ball with us
        {"repo": "o/r", "number": 2},   # we wrote last, 10d silence -> grave
        {"repo": "o/r", "number": 3},   # we wrote last, 1d silence -> waiting
        {"repo": "o/r", "number": 4},   # closed+merged
        {"repo": "o/r", "number": 5},   # bot wrote last, fresh -> NOT ball with us
        {"repo": "o/r", "number": 6},   # no snapshot -> ball with us (run a tick)
    ]}
    json.dump(cfg, open(cfg_path, "w"))
    os.makedirs(state, exist_ok=True)
    snaps = {
        1: {"state": "open", "issue_comments": [{"id": 1, "user": "stranger", "at": iso(1)}]},
        2: {"state": "open", "issue_comments": [{"id": 1, "user": "me", "at": iso(10)}]},
        3: {"state": "open", "issue_comments": [{"id": 1, "user": "me", "at": iso(1)}]},
        4: {"state": "closed", "merged": True, "issue_comments": []},
        5: {"state": "open", "issue_comments": [{"id": 1, "user": "ci[bot]", "at": iso(0)}]},
    }
    for n, s in snaps.items():
        s.setdefault("created_at", iso(20))
        json.dump(s, open(os.path.join(state, "o__r-%d.json" % n), "w"))
    r = run(["--digest"], env)
    out = r.stdout
    check("digest: stranger -> BALL WITH US", "o/r#1 — last word by stranger" in out)
    check("digest: 10d our silence -> grave", "o/r#2 — silent 10d" in out)
    check("digest: 1d -> waiting", "o/r#3 — silent 1d" in out)
    check("digest: merged -> closed", "o/r#4 — MERGED" in out)
    check("digest: bot last != ball with us", "o/r#5 — last word" not in out)
    check("digest: no snapshot -> flagged", "o/r#6 — no snapshot" in out)

    # 2b. state filename collision regression: a-b/c vs a/b-c must differ
    import pr_watch as pwmod
    check("state path: a-b/c != a/b-c",
          pwmod.state_path("a-b/c", 1) != pwmod.state_path("a/b-c", 1))

    # 3. break it on purpose: corrupt config
    open(cfg_path, "w").write("{ not json")
    r = run([], env)
    check("broken config: exit 2 + heartbeat", r.returncode == 2 and "config-error" in r.stdout)

    # 4. break it on purpose: corrupt state file is a first-run, not a crash
    json.dump(cfg, open(cfg_path, "w"))
    open(os.path.join(state, "o-r-1.json"), "w").write("garbage")
    r = run(["--digest"], env)
    check("corrupt state: digest survives", r.returncode == 0 and "no snapshot" in r.stdout)

    # 5. merge-write keeps the other writer's rows
    import pr_watch as pw
    base = {"authors": ["me"], "prs": [{"repo": "a/a", "number": 1}]}
    json.dump(base, open(cfg_path, "w"))
    mine = json.load(open(cfg_path))
    # another machine writes a different row between our read and write
    other = {"authors": ["me"], "prs": [{"repo": "a/a", "number": 1}, {"repo": "b/b", "number": 9}]}
    json.dump(other, open(cfg_path, "w"))
    mine["prs"].append({"repo": "c/c", "number": 7})
    os.environ["PR_WATCH_CONFIG"] = cfg_path
    pw.save_config(cfg_path, mine)
    rows = {(p["repo"], p["number"]) for p in json.load(open(cfg_path))["prs"]}
    check("merge-write: no lost rows", rows == {("a/a", 1), ("b/b", 9), ("c/c", 7)})

    shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d checks, %d failed" % (total[0], len(fails)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
