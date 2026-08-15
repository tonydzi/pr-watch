#!/usr/bin/env python3
"""pr_watch.py — an outbound ledger + daily harvest digest for YOUR PRs and issues
in OTHER people's repos. Zero LLM, zero dependencies beyond the `gh` CLI.

The problem it fixes: you contribute across many repositories, GitHub notifications
drown, and the thread where a maintainer answered you three days ago is the one you
never see. In our own measurement, 5 PRs from 3 strangers sat unanswered for 4 days
simply because no single list of "everything we have out there" existed.

Three commands:

  python3 pr_watch.py                 # tick: snapshot every registered PR/issue,
                                      #       alert on changes (comment/review/CI/
                                      #       label/commits/merge/close)
  python3 pr_watch.py --add <url>     # register a PR or issue by its GitHub URL
  python3 pr_watch.py --digest        # harvest: split the ledger into
                                      #   BALL WITH US  (they replied last — answer!)
                                      #   moved lately  (activity in the last day)
                                      #   waiting       (our move made, silence so far)
                                      #   graves        (silent > grave_days — let go)
                                      #   closed        (merged / closed)

The tick also auto-discovers your open PRs (`gh search prs --author ...`) so a PR
opened from another machine or session still lands in the ledger.

Design notes:
- Snapshots store only ids/authors/dates of comments, never bodies: external text
  is data, not instructions, and an alert should not relay it.
- First snapshot of a position is silent (no alert storm on adoption).
- A fetch failure alerts once on the ok->error transition, not nightly.
- If the alert command fails, state is NOT saved, so the same events re-alert on
  the next tick instead of being silently lost.
- The graves rule is empirical: in our sample every merge happened 0-3 days after
  the last maintainer touch; nothing merged later. One polite bump before the
  grave is fine; a second one never helped.

Config (JSON, first found wins: $PR_WATCH_CONFIG, ./pr_watch.json, ~/.pr_watch.json):

  {
    "authors": ["your-github-login"],        // for --sync and digest "ours" test
    "grave_days": 3,                         // silence threshold for graves
    "alert_cmd": "mail -s pr-watch me@x.io",  // optional; alert text on stdin
    "prs": [ {"repo": "owner/name", "number": 123}, ... ]
  }

State: one JSON snapshot per position in $PR_WATCH_STATE (default ~/.pr_watch_state).
Auth: whatever `gh auth status` says; set GH_TOKEN for cron/scheduled runs.
Exit codes: 0 ok · 2 bad config · 4 every fetch failed (the watcher is blind).
"""
import calendar
import io
import json
import os
import re
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STATE_DIR = os.environ.get("PR_WATCH_STATE", os.path.join(HOME, ".pr_watch_state"))
GH_TIMEOUT = 120
URL_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)")


def resolve_config():
    # An explicit env path wins even if the file does not exist yet — otherwise
    # the first --add on a fresh config silently writes to the home fallback
    # (caught by test_pr_watch.py before release).
    env = os.environ.get("PR_WATCH_CONFIG")
    if env:
        return env
    for p in ("pr_watch.json", os.path.join(HOME, ".pr_watch.json")):
        if os.path.isfile(p):
            return p
    return os.path.join(HOME, ".pr_watch.json")


def load_config(path):
    # utf-8-sig: a config re-saved by Notepad/PowerShell arrives with a BOM
    if os.path.isfile(path):
        return json.loads(io.open(path, encoding="utf-8-sig").read())
    return {"prs": []}


def save_config(path, cfg):
    """Merge-write: re-read right before writing and union by (repo, number).
    The config may live in a synced folder written by several machines; a plain
    read-modify-write loses the other writer's rows (found by adversarial review)."""
    try:
        fresh = load_config(path)
    except Exception:
        fresh = {"prs": []}
    merged, seen = [], set()
    for row in (cfg.get("prs") or []) + (fresh.get("prs") or []):
        key = (row.get("repo"), row.get("number"))
        if key in seen or not key[0]:
            continue
        seen.add(key)
        merged.append(row)
    out = dict(fresh)
    for k, v in cfg.items():
        if k != "prs" and k not in out:
            out[k] = v
    out["prs"] = merged
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(out, ensure_ascii=False, indent=1))
    os.replace(tmp, path)


def log(msg):
    print("[%s] %s" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))


def gh_json(path, paginate=False):
    cmd = ["gh", "api", path]
    if paginate:
        cmd += ["--paginate", "--slurp"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=GH_TIMEOUT)
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found in PATH")
    except subprocess.TimeoutExpired:
        raise RuntimeError("gh api %s: timeout %ss" % (path, GH_TIMEOUT))
    if r.returncode != 0:
        raise RuntimeError("gh api %s: exit %s: %s"
                           % (path, r.returncode, (r.stderr or "")[:200].strip()))
    try:
        data = json.loads(r.stdout)
    except Exception:
        raise RuntimeError("gh api %s: non-JSON response" % path)
    if paginate:
        flat = []
        for page in data:
            flat.extend(page if isinstance(page, list) else [page])
        return flat
    return data


def snapshot(repo, number):
    """Snapshot of the watched fields of a PR OR an issue. Bodies are never stored:
    only id/author/date per comment (external text is data, not instructions)."""
    is_pr = True
    try:
        pr = gh_json("repos/%s/pulls/%s" % (repo, number))
    except RuntimeError as exc:
        if "HTTP 404" not in str(exc):
            raise
        is_pr = False
        pr = gh_json("repos/%s/issues/%s" % (repo, number))
        if pr.get("pull_request"):
            raise RuntimeError("repos/%s/pulls/%s: 404 but object is a PR" % (repo, number))
    head_sha = (pr.get("head") or {}).get("sha") or ""
    snap = {
        "kind": "pr" if is_pr else "issue",
        "state": pr.get("state"),
        "merged": bool(pr.get("merged")),
        "head_sha": head_sha,
        "title": pr.get("title") or "",
        "created_at": pr.get("created_at") or "",
        "labels": sorted(l.get("name", "") for l in pr.get("labels") or []),
    }

    def _slim(items):
        return [{"id": c.get("id"), "user": (c.get("user") or {}).get("login", "?"),
                 "at": c.get("created_at") or c.get("submitted_at") or ""} for c in items]

    snap["issue_comments"] = _slim(
        gh_json("repos/%s/issues/%s/comments" % (repo, number), paginate=True))
    if is_pr:
        snap["review_comments"] = _slim(
            gh_json("repos/%s/pulls/%s/comments" % (repo, number), paginate=True))
        reviews = gh_json("repos/%s/pulls/%s/reviews" % (repo, number), paginate=True)
        snap["reviews"] = [{"id": r.get("id"),
                            "user": (r.get("user") or {}).get("login", "?"),
                            "at": r.get("submitted_at") or "",
                            "verdict": r.get("state", "?")} for r in reviews]
    else:
        snap["review_comments"] = []
        snap["reviews"] = []
    checks = {}
    if head_sha:
        try:
            cr = gh_json("repos/%s/commits/%s/check-runs?per_page=100" % (repo, head_sha))
            for run in cr.get("check_runs") or []:
                checks[run.get("name", "?")] = run.get("conclusion") or run.get("status") or "?"
        except RuntimeError as exc:
            log("[!] check-runs unavailable for %s#%s: %s" % (repo, number, exc))
    snap["ci_checks"] = checks
    return snap


def diff(old, new):
    """Human-readable events between two snapshots (names only, no external text)."""
    ev = []
    if old.get("state") != new.get("state") or old.get("merged") != new.get("merged"):
        if new.get("merged"):
            ev.append("MERGED")
        elif new.get("state") == "closed":
            ev.append("CLOSED (without merge)")
        else:
            ev.append("state: %s -> %s" % (old.get("state"), new.get("state")))
    for kind, label in (("issue_comments", "comment"), ("review_comments", "review comment")):
        old_ids = {c["id"] for c in old.get(kind, [])}
        for c in new.get(kind, []):
            if c["id"] not in old_ids:
                ev.append("new %s by %s" % (label, c["user"]))
    old_rev = {r["id"]: r.get("verdict") for r in old.get("reviews", [])}
    for r in new.get("reviews", []):
        if r["id"] not in old_rev:
            ev.append("new review by %s: %s" % (r["user"], r["verdict"]))
        elif old_rev[r["id"]] != r.get("verdict"):
            # APPROVED -> DISMISSED etc.: same id, changed verdict is an event too
            ev.append("review by %s changed: %s -> %s"
                      % (r["user"], old_rev[r["id"]], r.get("verdict")))
    old_l, new_l = set(old.get("labels", [])), set(new.get("labels", []))
    for l in sorted(new_l - old_l):
        ev.append("label added: %s" % l)
    for l in sorted(old_l - new_l):
        ev.append("label removed: %s" % l)
    if old.get("title") != new.get("title"):
        ev.append("title changed")
    if old.get("head_sha") != new.get("head_sha"):
        ev.append("new commits (head %s -> %s)"
                  % ((old.get("head_sha") or "")[:7], (new.get("head_sha") or "")[:7]))
    old_ci, new_ci = old.get("ci_checks", {}), new.get("ci_checks", {})
    for name, concl in sorted(new_ci.items()):
        if old_ci.get(name) != concl:
            ev.append("CI %s: %s -> %s" % (name, old_ci.get(name, "-"), concl))
    return ev


_CTRL = re.compile(r"[\x00-\x09\x0b-\x1f\x7f]")


def sanitize(text):
    """Strip control characters (keep newlines): usernames/labels/CI names come from
    the outside world and must not smuggle terminal escape sequences into alerts."""
    return _CTRL.sub("", text)


def send_alert(cfg, text):
    """Pipe the alert text to the configured shell command. True = delivered."""
    text = sanitize(text)
    cmd = cfg.get("alert_cmd")
    if not cmd:
        print(text)
        return True
    try:
        r = subprocess.run(cmd, shell=True, input=text, text=True,
                           encoding="utf-8", timeout=180)
        return r.returncode == 0
    except Exception as exc:
        log("[!] alert_cmd failed: %s" % exc)
        return False


def state_path(repo, number):
    # "__" separator: repo.replace("/","-") collided a-b/c with a/b-c
    # (found by adversarial review before release)
    return os.path.join(STATE_DIR, "%s-%s.json" % (repo.replace("/", "__"), number))


def load_state(path):
    if not os.path.exists(path):
        return None
    try:
        return json.loads(io.open(path, encoding="utf-8-sig").read())
    except Exception as exc:
        log("[!] corrupt state %s (%s) — treating as first run" % (path, exc))
        return None


def save_state(path, data):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False, indent=1))
    os.replace(tmp, path)  # atomic: a half-written state never kills the next run


def cmd_add(argv):
    note = ""
    args = list(argv)
    if "--note" in args:
        i = args.index("--note")
        note = args[i + 1] if i + 1 < len(args) else ""
        del args[i:i + 2]
    # every positional must parse as a GitHub url — a typo'd argument must be
    # named, not silently dropped (caught by test_pr_watch.py before release)
    urls = [a for a in args if not a.startswith("--")]
    if not urls:
        print("usage: pr_watch.py --add <github-url> [<url> ...] [--note '...']")
        return 2
    path = resolve_config()
    cfg = load_config(path)
    have = {(p["repo"], int(p["number"])) for p in cfg.get("prs", [])}
    added = 0
    for u in urls:
        m = URL_RE.search(u)
        if not m:
            print("[!] could not parse url: %s" % u)
            continue
        repo, num = m.group(1), int(m.group(2))
        if (repo, num) in have:
            print("already in ledger: %s#%s" % (repo, num))
            continue
        row = {"repo": repo, "number": num, "added": time.strftime("%Y-%m-%d")}
        if note:
            row["note"] = note
        cfg.setdefault("prs", []).append(row)
        have.add((repo, num))
        added += 1
        print("+ %s#%s" % (repo, num))
    if added:
        save_config(path, cfg)
        print("ledger: %s (%d positions)" % (path, len(load_config(path)["prs"])))
    return 0


def cmd_sync(cfg, path, dry=False):
    """Self-feeding: ask GitHub for all open PRs by the configured authors and add
    the missing ones. A hand-maintained list is hope, not a rail — in our own use
    28 of 36 live positions were missing before this existed. Returns count added,
    or -1 if NO author could be queried (so '0 new' can't masquerade as 'checked')."""
    authors = cfg.get("authors") or []
    if not authors:
        return 0
    found, added, asked = set(), 0, 0
    for author in authors:
        try:
            r = subprocess.run(
                ["gh", "search", "prs", "--author", author, "--state", "open",
                 "--limit", "100", "--json", "number,repository"],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=GH_TIMEOUT)
            if r.returncode != 0:
                # an empty stdout on failure must not count as "queried clean"
                raise RuntimeError("gh search exit %s: %s"
                                   % (r.returncode, (r.stderr or "")[:120].strip()))
            for row in json.loads(r.stdout or "[]"):
                found.add((row["repository"]["nameWithOwner"], int(row["number"])))
            asked += 1
        except Exception as exc:
            log("[!] autodiscover: author %s not queried: %s" % (author, str(exc)[:120]))
    if not asked:
        log("[!] autodiscover: no author queried — the ledger was NOT verified")
        return -1
    have = {(p["repo"], int(p["number"])) for p in cfg.get("prs", [])
            if p.get("repo") and p.get("number")}
    for repo, num in sorted(found - have):
        if not dry:
            cfg.setdefault("prs", []).append(
                {"repo": repo, "number": num,
                 "added": time.strftime("%Y-%m-%d"), "by": "autodiscover"})
        added += 1
        log("+ autodiscover %s#%s" % (repo, num))
    if added and not dry:
        save_config(path, cfg)
    return added


def cmd_digest(argv):
    """Daily harvest. Reads only saved snapshots: 0 network calls. Silence is NOT
    ok — quiet positions are printed with their age, because a forgotten thread is
    exactly the loss this ledger exists to prevent."""
    path = resolve_config()
    cfg = load_config(path)
    ours = set(cfg.get("authors") or [])
    grave_days = int(cfg.get("grave_days", 3))
    now = time.time()
    moved, ball_them, ball_us, closed, graves = [], [], [], [], []
    for item in cfg.get("prs", []):
        repo, num = item["repo"], item["number"]
        st = load_state(state_path(repo, num))
        if not st:
            ball_us.append((repo, num, "no snapshot yet — run a tick first"))
            continue
        allc = ((st.get("issue_comments") or []) + (st.get("review_comments") or [])
                + (st.get("reviews") or []))
        last = max((c.get("at") or "" for c in allc), default="")
        last_user = ""
        for c in allc:
            if (c.get("at") or "") == last:
                last_user = c.get("user", "")
        age, days = "", None
        # No comments at all -> measure silence from PR creation, otherwise an
        # empty thread can never become a grave.
        basis = last or (st.get("created_at") or "")
        if basis:
            try:
                # GitHub dates are UTC ('Z'): timegm, not mktime — mktime reads
                # them as local time and lies by the timezone offset.
                t = calendar.timegm(time.strptime(basis[:19], "%Y-%m-%dT%H:%M:%S"))
                days = int((now - t) // 86400)
                age = "%dd" % days
                if last and now - t < 86400 * 1.5:
                    moved.append((repo, num, "activity %s ago by %s" % (age, last_user or "?")))
            except Exception:
                pass
        if st.get("state") == "closed":
            closed.append((repo, num, "MERGED" if st.get("merged") else "closed"))
        elif last_user and last_user not in ours and not last_user.endswith("[bot]"):
            ball_us.append((repo, num,
                            "last word by %s (%s) — THE BALL IS WITH YOU" % (last_user, age)))
        elif days is not None and days > grave_days:
            # Graves rule: in our merges-sample everything merged 0-3 days after
            # the last maintainer touch; later — never. One bump before the grave
            # is fine; a second never helped. Spend the time on living threads.
            graves.append((repo, num, "silent %s — let it rest" % age))
        else:
            ball_them.append((repo, num, "silent %s" % (age or "since opening")))

    def block(title, rows):
        if not rows:
            return ""
        return "\n%s (%d):\n" % (title, len(rows)) + "\n".join(
            "- %s#%s — %s" % r for r in rows)

    text = "harvest %s — %d positions in the ledger" % (
        time.strftime("%Y-%m-%d"), len(cfg.get("prs", [])))
    text += block("BALL WITH US", ball_us)
    text += block("moved in the last day", moved)
    text += block("waiting on them", ball_them)
    text += block("graves (silent > %dd — no more bumps)" % grave_days, graves)
    text += block("closed", closed)
    print(text)
    if "--send" in argv and not send_alert(cfg, text):
        return 3
    return 0


def main():
    dry = "--dry-run" in sys.argv
    if "--add" in sys.argv:
        return cmd_add(sys.argv[1:])
    if "--digest" in sys.argv:
        return cmd_digest(sys.argv[1:])
    path = resolve_config()
    try:
        cfg = load_config(path)
        prs = cfg["prs"]
        assert isinstance(prs, list)
    except Exception as exc:
        log("[!] config %s unreadable: %s" % (path, exc))
        print("heartbeat config-error prs=0 events=0")
        return 2
    if "--sync" in sys.argv:
        n = cmd_sync(cfg, path, dry=dry)
        if n < 0:
            print("autodiscover: NOT QUERIED (gh down / rate limit) — ledger unverified")
            return 4
        print("autodiscover: +%d positions" % n)
        return 0
    try:
        cmd_sync(cfg, path, dry=dry)
        cfg = load_config(path)
        prs = cfg["prs"]
    except Exception as exc:
        log("[!] autodiscover skipped: %s" % str(exc)[:160])

    total_events, fetched, failed = 0, 0, 0
    for item in prs:
        repo, number = item.get("repo"), item.get("number")
        if not repo or not number:
            log("[!] malformed config row: %r" % (item,))
            continue
        spath = state_path(repo, number)
        old = load_state(spath)
        kind = "issues" if (old or {}).get("kind") == "issue" else "pull"
        url = "https://github.com/%s/%s/%s" % (repo, kind, number)
        health_was = (old or {}).get("_health", "ok")
        try:
            snap = snapshot(repo, number)
            fetched += 1
        except RuntimeError as exc:
            failed += 1
            log("[!] fetch %s#%s failed: %s" % (repo, number, exc))
            # alert only on the ok->error transition; name the remedy in the alert
            delivered = True
            if health_was == "ok" and old is not None and not dry:
                delivered = send_alert(cfg, "[pr-watch] could not snapshot %s#%s (%s). "
                                       "Check network and `gh auth status`, then rerun. %s"
                                       % (repo, number, str(exc)[:160], url))
            if old is not None and delivered:
                # if the alert did NOT go out, keep health=ok so the ok->error
                # transition (and its alert) fires again on the next tick
                old["_health"] = "error"
                if not dry:
                    save_state(spath, old)
            continue

        snap["_health"] = "ok"
        snap["_checked_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        if old is None:
            log("first snapshot %s#%s saved (comments=%d reviews=%d checks=%d) — no alert"
                % (repo, number,
                   len(snap["issue_comments"]) + len(snap["review_comments"]),
                   len(snap["reviews"]), len(snap["ci_checks"])))
            if not dry:
                save_state(spath, snap)
            continue

        events = diff(old, snap)
        total_events += len(events)
        if events:
            head = "[pr-watch] %s#%s — %d change(s):" % (repo, number, len(events))
            body = "\n".join("- %s" % e for e in events)
            msg = "%s\n%s\n%s" % (head, body, url)
            log("EVENTS %s#%s: %s" % (repo, number, "; ".join(events)))
            if dry:
                log("dry-run: alert NOT sent:\n%s" % msg)
            elif not send_alert(cfg, msg):
                # alert undelivered — do NOT save state, so the same events
                # re-alert tomorrow instead of being silently lost
                log("[!] alert undelivered — snapshot not saved, will retry")
                continue
        else:
            log("quiet: %s#%s — no changes" % (repo, number))
        if not dry:
            save_state(spath, snap)

    status = "ok" if failed == 0 else ("error" if fetched == 0 else "degraded")
    print("heartbeat %s prs=%d/%d events=%d" % (status, fetched, len(prs), total_events))
    return 4 if fetched == 0 and prs else 0


if __name__ == "__main__":
    sys.exit(main())
