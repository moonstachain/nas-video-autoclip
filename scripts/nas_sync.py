#!/usr/bin/env python3
"""
nas_sync.py — 「断网不丢」的 NAS 归档器。

NAS 可达 → 直接归档到项目结构(00-05)。
NAS 不可达(在外地/断网/没连VPN) → 把成片等暂存到本地队列 + 清单，
                                  下次 NAS 可达时 `flush` 自动补传。零丢失。

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
import argparse, json, os, shutil, sys, time

QUEUE_DEFAULT = os.path.expanduser("~/.nas-autoclip-queue")
RAW_EXTS = (".mp4", ".mov", ".m4v", ".MP4", ".MOV", ".M4V")

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
    if nas_reachable(args.proj):
        done = copy_to_nas(args.proj, jobs)
        print(json.dumps({"mode":"direct","proj":args.proj,
                          "copied":[d[1] for d in done if d[2]=='ok']},
                         ensure_ascii=False, indent=2))
        # 顺便清一次旧队列(可能之前断网攒下的)
        flushed = flush(args.queue)
        if flushed: print(f"↪ 顺带补传了 {flushed} 个历史待同步项")
    else:
        jd = enqueue(args.proj, jobs, args.queue)
        print(json.dumps({"mode":"queued","reason":"NAS不可达(断网/外地/没连VPN)",
                          "queue_dir":jd,"target":args.proj,"files":len(jobs),
                          "hint":"NAS 可达时运行 flush 自动补传(或已装自动补传则无需手动)"},
                         ensure_ascii=False, indent=2))
    return 0

def flush(queue):
    """把队列里所有 NAS 现在可达的任务补传，返回成功条数。"""
    if not os.path.isdir(queue): return 0
    n = 0
    for d in sorted(os.listdir(queue)):
        jd = os.path.join(queue, d)
        mf = os.path.join(jd, "manifest.json")
        if not os.path.isfile(mf): continue
        m = json.load(open(mf, encoding="utf-8"))
        proj = m["proj"]
        if not nas_reachable(proj): continue
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
    print(json.dumps({"queue": q, "pending": len(pend), "items": pend},
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
