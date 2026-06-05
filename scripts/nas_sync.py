#!/usr/bin/env python3
"""
nas_sync.py — NAS 归档器，三层降级，随时随地不丢。

① 局域网可达      → 直接归档到项目结构(00-05)。
② 在外地+配了远程 → 走 WebDAV HTTPS 直接上传回 NAS（外地实时归档，无需 VPN）。
③ 都不行(纯断网)  → 暂存本地队列+清单，回家/连上时 `flush` 自动补传。零丢失。

远程实时归档一次性配置见下方 REMOTE 段注释（NAS 装 WebDAV Server + 填 ~/.nas-autoclip-remote.json）。

子命令:
  archive  按角色归档(可达直传/不可达入队)
  flush    扫描队列，把所有能传的补传到各自 NAS 目标
  status   看队列里还有多少待同步 + 当前 NAS 是否可达

角色→NAS子目录映射:
  final   -> 04_导出成片/<原名>
  raw-dir -> 01_拍摄原始_只读勿改/<每个视频>
  srt     -> 00_策划脚本/<原名>
  preview -> 00_策划脚本/成片预览_9帧.jpg
  draft   -> 03_剪辑工程/剪映草稿_<原名>/   (整个目录)

用法见 `--help`。队列默认在 ~/.nas-autoclip-queue/
"""
import argparse, json, os, shutil, subprocess, sys, time

QUEUE_DEFAULT = os.path.expanduser("~/.nas-autoclip-queue")
RAW_EXTS = (".mp4", ".mov", ".m4v", ".MP4", ".MOV", ".M4V")
REMOTE_CFG = os.path.expanduser("~/.nas-autoclip-remote.json")

# ───────────────────────── 远程 WebDAV 后端（外地实时归档） ─────────────────────────
# 让「在外地」也能直接把成片传回 NAS，无需 VPN/客户端。
# 一次性配置：在 NAS 装「WebDAV Server」套件(开 HTTPS 5006)，再填 ~/.nas-autoclip-remote.json:
#   { "webdav_base": "https://<你的DDNS或公网地址>:5006/团队共享盘",
#     "user": "MING", "pass": "********", "insecure": true }
# 或用环境变量 NAS_REMOTE_WEBDAV / NAS_REMOTE_USER / NAS_REMOTE_PASS。
# 凭据由你本地提供，脚本只读取不外传；建议 chmod 600 该文件。
def load_remote():
    cfg = {}
    if os.path.isfile(REMOTE_CFG):
        try: cfg = json.load(open(REMOTE_CFG, encoding="utf-8"))
        except Exception: cfg = {}
    base = os.environ.get("NAS_REMOTE_WEBDAV", cfg.get("webdav_base"))
    user = os.environ.get("NAS_REMOTE_USER", cfg.get("user"))
    pw   = os.environ.get("NAS_REMOTE_PASS", cfg.get("pass"))
    if not base or not user or pw is None:
        return None
    return {"base": base.rstrip("/"), "user": user, "pass": pw,
            "insecure": bool(cfg.get("insecure", False))}

def _curl(remote, method, url, extra=None):
    cmd = ["curl", "-fsS", "--connect-timeout", "8", "-u", f"{remote['user']}:{remote['pass']}",
           "-X", method, url]
    if remote["insecure"]: cmd.insert(1, "-k")
    if extra: cmd[1:1] = extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stderr

def remote_online(remote):
    if remote is None: return False
    rc, _ = _curl(remote, "PROPFIND", remote["base"] + "/", ["-H", "Depth: 0"])
    return rc == 0

def remote_mkcol_p(remote, rel):
    # 逐级建目录(WebDAV MKCOL 不递归)
    acc = remote["base"]
    for seg in [s for s in rel.split("/") if s]:
        acc += "/" + seg
        _curl(remote, "MKCOL", acc)  # 已存在返回非0也无妨

def remote_put_file(remote, local, rel):
    remote_mkcol_p(remote, os.path.dirname(rel))
    url = remote["base"] + "/" + rel
    rc, err = _curl(remote, "PUT", url, ["-T", local])
    if rc != 0: raise RuntimeError(f"WebDAV PUT 失败 {rel}: {err[-200:]}")

def remote_put_tree(remote, local_dir, rel_dir):
    for root, _, files in os.walk(local_dir):
        for fn in files:
            lp = os.path.join(root, fn)
            rp = rel_dir + "/" + os.path.relpath(lp, local_dir).replace(os.sep, "/")
            remote_put_file(remote, lp, rp)

def proj_relpath(proj):
    """把 /Volumes/<share>/a/b 转成 share 内相对路径 a/b（webdav_base 已指向 share 根）"""
    vol = vol_of(proj)
    if vol and proj.startswith(vol + "/"):
        return proj[len(vol) + 1:]
    return proj.lstrip("/")

def remote_archive(remote, proj, jobs):
    rel_root = proj_relpath(proj)
    done = []
    for role, src, dest_rel, is_dir in jobs:
        rel = f"{rel_root}/{dest_rel}"
        if is_dir: remote_put_tree(remote, src, rel)
        else:      remote_put_file(remote, src, rel)
        done.append((role, dest_rel, "ok"))
    return done
# ──────────────────────────────────────────────────────────────────────────────

def vol_of(proj):
    """从 /Volumes/<share>/... 推出卷挂载点 /Volumes/<share>"""
    parts = proj.split("/")
    if len(parts) >= 3 and parts[1] == "Volumes":
        return "/" + "/".join(parts[1:3])
    return None

def nas_reachable(proj):
    if os.environ.get("NAS_AUTOCLIP_FORCE_OFFLINE") == "1":
        return False
    vol = vol_of(proj)
    if vol is None:
        # 非 /Volumes 路径(比如本地同步盘) → 看父目录是否可写
        return os.path.isdir(os.path.dirname(proj)) or os.path.isdir(proj)
    return os.path.ismount(vol)

def build_jobs(args):
    """返回 [(role, src_abspath, dest_relpath, is_dir)]"""
    jobs = []
    if args.final:
        jobs.append(("final", os.path.abspath(args.final),
                     f"04_导出成片/{os.path.basename(args.final)}", False))
    if args.raw_dir and os.path.isdir(args.raw_dir):
        for n in sorted(os.listdir(args.raw_dir)):
            if n.endswith(RAW_EXTS):
                jobs.append(("raw", os.path.join(os.path.abspath(args.raw_dir), n),
                             f"01_拍摄原始_只读勿改/{n}", False))
    if args.srt and os.path.isfile(args.srt):
        jobs.append(("srt", os.path.abspath(args.srt),
                     f"00_策划脚本/{os.path.basename(args.srt)}", False))
    if args.preview and os.path.isfile(args.preview):
        jobs.append(("preview", os.path.abspath(args.preview),
                     "00_策划脚本/成片预览_9帧.jpg", False))
    if args.draft and os.path.isdir(args.draft):
        jobs.append(("draft", os.path.abspath(args.draft),
                     f"03_剪辑工程/剪映草稿_{os.path.basename(args.draft)}", True))
    return jobs

def copy_to_nas(proj, jobs):
    for sub in ("00_策划脚本","01_拍摄原始_只读勿改","03_剪辑工程","04_导出成片","05_已交付发布"):
        os.makedirs(os.path.join(proj, sub), exist_ok=True)
    done = []
    for role, src, dest_rel, is_dir in jobs:
        dst = os.path.join(proj, dest_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if is_dir:
            if os.path.exists(dst): shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            if role == "raw" and os.path.exists(dst):
                done.append((role, dest_rel, "skip(已存在)")); continue
            shutil.copy2(src, dst)
        done.append((role, dest_rel, "ok"))
    return done

def enqueue(proj, jobs, queue):
    stamp = time.strftime("%Y%m%d-%H%M%S")
    job_dir = os.path.join(queue, f"{stamp}_{os.path.basename(proj.rstrip('/'))}")
    staged = os.path.join(job_dir, "staged")
    os.makedirs(staged, exist_ok=True)
    manifest = {"proj": proj, "queued_at": stamp, "jobs": []}
    for i, (role, src, dest_rel, is_dir) in enumerate(jobs):
        sp = os.path.join(staged, str(i))
        if is_dir:
            shutil.copytree(src, sp)
        else:
            os.makedirs(sp, exist_ok=True)
            shutil.copy2(src, os.path.join(sp, os.path.basename(src)))
        manifest["jobs"].append({"role": role, "staged": str(i),
                                 "name": os.path.basename(src.rstrip('/')),
                                 "dest_rel": dest_rel, "is_dir": is_dir})
    with open(os.path.join(job_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return job_dir

def cmd_archive(args):
    jobs = build_jobs(args)
    if not jobs:
        print("⚠️ 没有可归档的文件(检查 --final 等参数)"); return 1
    # 三层降级：局域网直传 → 远程WebDAV实时上传(外地) → 入队兜底(断网不丢)
    if nas_reachable(args.proj):
        done = copy_to_nas(args.proj, jobs)
        print(json.dumps({"mode":"local-direct","proj":args.proj,
                          "copied":[d[1] for d in done if d[2]=='ok']},
                         ensure_ascii=False, indent=2))
        flushed = flush(args.queue)
        if flushed: print(f"↪ 顺带补传了 {flushed} 个历史待同步项")
        return 0
    remote = load_remote()
    if remote_online(remote):
        try:
            done = remote_archive(remote, args.proj, jobs)
            print(json.dumps({"mode":"remote-webdav","target":args.proj,
                              "uploaded":[d[1] for d in done]}, ensure_ascii=False, indent=2))
            flush(args.queue)
            return 0
        except Exception as e:
            sys.stderr.write(f"远程上传失败，转入队列: {e}\n")
    jd = enqueue(args.proj, jobs, args.queue)
    reason = "NAS不可达且未配/连不上远程" if remote is None else "远程上传失败"
    print(json.dumps({"mode":"queued","reason":reason,
                      "queue_dir":jd,"target":args.proj,"files":len(jobs),
                      "hint":"NAS可达(回家/连VPN)或远程恢复时 flush 自动补传"},
                     ensure_ascii=False, indent=2))
    return 0

def flush(queue):
    """把队列里所有 NAS 现在可达的任务补传，返回成功条数。"""
    if not os.path.isdir(queue): return 0
    remote = load_remote()
    remote_up = remote_online(remote) if remote else False
    n = 0
    for d in sorted(os.listdir(queue)):
        jd = os.path.join(queue, d)
        mf = os.path.join(jd, "manifest.json")
        if not os.path.isfile(mf): continue
        m = json.load(open(mf, encoding="utf-8"))
        proj = m["proj"]
        local_ok = nas_reachable(proj)
        if not local_ok and not remote_up: continue
        # 远程优先用 WebDAV 整单上传
        if not local_ok and remote_up:
            try:
                for j in m["jobs"]:
                    src_root = os.path.join(jd, "staged", j["staged"])
                    rel = f"{proj_relpath(proj)}/{j['dest_rel']}"
                    if j["is_dir"]: remote_put_tree(remote, src_root, rel)
                    else:
                        inner = os.path.join(src_root, j["name"])
                        src = inner if os.path.isfile(inner) else os.path.join(src_root, os.listdir(src_root)[0])
                        remote_put_file(remote, src, rel)
                shutil.rmtree(jd, ignore_errors=True); n += 1
            except Exception as e:
                sys.stderr.write(f"flush(远程) 失败 {d}: {e}\n")
            continue
        for sub in ("00_策划脚本","01_拍摄原始_只读勿改","03_剪辑工程","04_导出成片","05_已交付发布"):
            os.makedirs(os.path.join(proj, sub), exist_ok=True)
        ok = True
        for j in m["jobs"]:
            src_root = os.path.join(jd, "staged", j["staged"])
            dst = os.path.join(proj, j["dest_rel"])
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                if j["is_dir"]:
                    # 入队时 copytree(draft, staged/i) → staged/i 即草稿目录本身
                    if os.path.exists(dst): shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(src_root, dst)
                else:
                    inner = os.path.join(src_root, j["name"])
                    src = inner if os.path.isfile(inner) else os.path.join(src_root, os.listdir(src_root)[0])
                    if j["role"]=="raw" and os.path.exists(dst): continue
                    shutil.copy2(src, dst)
            except Exception as e:
                ok = False; sys.stderr.write(f"flush 失败 {d}/{j['role']}: {e}\n")
        if ok:
            shutil.rmtree(jd, ignore_errors=True); n += 1
    return n

def cmd_flush(args):
    n = flush(args.queue)
    print(json.dumps({"flushed": n, "queue": args.queue}, ensure_ascii=False))
    return 0

def cmd_status(args):
    q = args.queue
    pend = []
    if os.path.isdir(q):
        for d in sorted(os.listdir(q)):
            mf = os.path.join(q, d, "manifest.json")
            if os.path.isfile(mf):
                m = json.load(open(mf, encoding="utf-8"))
                pend.append({"job": d, "target": m["proj"],
                             "reachable_now": nas_reachable(m["proj"]),
                             "files": len(m["jobs"])})
    remote = load_remote()
    print(json.dumps({"queue": q, "pending": len(pend), "items": pend,
                      "remote_configured": remote is not None,
                      "remote_online": (remote_online(remote) if remote else False)},
                     ensure_ascii=False, indent=2))
    return 0

def main():
    ap = argparse.ArgumentParser(description="断网不丢的 NAS 归档器")
    ap.add_argument("--queue", default=QUEUE_DEFAULT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("archive"); a.set_defaults(fn=cmd_archive)
    a.add_argument("--proj", required=True, help="NAS项目根, 如 /Volumes/<share>/01_项目进行中/2026/2026-06_客户_项目")
    a.add_argument("--final"); a.add_argument("--raw-dir")
    a.add_argument("--srt"); a.add_argument("--preview"); a.add_argument("--draft")
    f = sub.add_parser("flush"); f.set_defaults(fn=cmd_flush)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    args = ap.parse_args()
    sys.exit(args.fn(args))

if __name__ == "__main__":
    main()
