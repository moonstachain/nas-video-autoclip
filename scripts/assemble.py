#!/usr/bin/env python3
"""
assemble.py — 把一份「剪辑计划」编译成一条高级感竖屏成片。

核心价值：把 N=1 验证过的「归一化 + 电影级调色 + 柔交叉转场 + 淡入淡出 + 暗角」
配方固化成一条命令，避免每次重写一长串 ffmpeg filtergraph。

用法:
  python3 assemble.py --plan plan.json --out final.mp4 \
      --width 1080 --height 1920 --fps 30 --grade cinematic-warm

plan.json 是一个数组，每段一个对象（按出场顺序排列）:
  [
    {"file": "/abs/path/a.mp4", "start": 0,  "dur": 14},
    {"file": "/abs/path/b.mp4", "start": 0,  "dur": 28},
    {"file": "/abs/path/a.mp4", "start": 40, "dur": 6}
  ]

默认行为（都可关）:
  - 统一填充裁切到 width×height（竖屏小红书默认 1080×1920），不留黑边
  - 调色: cinematic-warm（偏暖电影感）。其它见 --grade 选项
  - 段间 0.7s 交叉淡化转场
  - 片头淡入 0.6s / 片尾淡出 1.0s
  - 轻微暗角聚焦
  - 静音（--keep-audio 可保留原声；现场口语通常应静音后在剪映加 BGM）
"""
import argparse, json, os, subprocess, sys, tempfile, shutil

GRADES = {
    # name: ffmpeg 调色滤镜串（可自行扩展）
    "cinematic-warm": "eq=contrast=1.06:saturation=1.10:brightness=0.012,unsharp=5:5:0.3:5:5:0.0",
    "wabi-sabi":      "eq=contrast=1.04:saturation=0.86:brightness=0.01,curves=preset=lighter,unsharp=5:5:0.25:5:5:0.0",
    "clean-bright":   "eq=contrast=1.05:saturation=1.06:brightness=0.02,unsharp=5:5:0.3:5:5:0.0",
    "none":           "null",
}

def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.stderr.write("FFMPEG ERROR:\n" + p.stderr[-2000:] + "\n")
        raise SystemExit(p.returncode)
    return p

def probe_dur(path):
    out = subprocess.run(
        ["ffprobe","-v","error","-show_entries","format=duration","-of","csv=p=0", path],
        capture_output=True, text=True).stdout.strip()
    return float(out)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--width", type=int, default=1080)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--grade", default="cinematic-warm", choices=list(GRADES))
    ap.add_argument("--xfade", type=float, default=0.7, help="转场时长秒, 0=硬切")
    ap.add_argument("--fade-in", type=float, default=0.6)
    ap.add_argument("--fade-out", type=float, default=1.0)
    ap.add_argument("--no-vignette", action="store_true")
    ap.add_argument("--keep-audio", action="store_true", help="保留原声(默认静音待配乐)")
    ap.add_argument("--crf", type=int, default=19)
    args = ap.parse_args()

    W, H, F = args.width, args.height, args.fps
    plan = json.load(open(args.plan, encoding="utf-8"))
    if not plan:
        raise SystemExit("plan.json 为空")
    grade = GRADES[args.grade]
    vf_norm = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
               f"crop={W}:{H},fps={F}," + grade)

    tmp = tempfile.mkdtemp(prefix="assemble_")
    try:
        # 1) 归一化每一段
        segs, durs = [], []
        for i, s in enumerate(plan):
            seg = os.path.join(tmp, f"seg{i}.mp4")
            cmd = ["ffmpeg","-y","-ss",str(s["start"]),"-t",str(s["dur"]),
                   "-i", s["file"], "-vf", vf_norm]
            if not args.keep_audio:
                cmd += ["-an"]
            cmd += ["-c:v","libx264","-crf",str(args.crf),"-preset","medium", seg, "-loglevel","error"]
            run(cmd)
            segs.append(seg); durs.append(probe_dur(seg))
            print(f"  段{i}: {os.path.basename(s['file'])} [{s['start']}+{s['dur']}] -> {durs[-1]:.2f}s")

        # 2) 串接（xfade 链 或 硬切 concat）
        inputs = []
        for seg in segs:
            inputs += ["-i", seg]

        if args.xfade > 0 and len(segs) > 1:
            # 累积 offset 链式 xfade
            fc, prev, off = [], "[0:v]", 0.0
            for i in range(1, len(segs)):
                off += durs[i-1] - args.xfade
                lbl = f"[x{i}]"
                fc.append(f"{prev}[{i}:v]xfade=transition=fade:duration={args.xfade}:offset={off:.3f}{lbl}")
                prev = lbl
            total = sum(durs) - args.xfade * (len(segs)-1)
            post = []
            if args.fade_in > 0:  post.append(f"fade=t=in:st=0:d={args.fade_in}")
            if args.fade_out > 0: post.append(f"fade=t=out:st={total-args.fade_out:.3f}:d={args.fade_out}")
            if not args.no_vignette: post.append("vignette=PI/5")
            # prev 已是最后一个 [xN] 标签；追加后处理 -> [v]
            if post:
                fc.append(f"{prev}{','.join(post)}[v]")
            else:
                fc.append(f"{prev}null[v]")
            filt = ";".join(fc)
            run(["ffmpeg","-y",*inputs,"-filter_complex",filt,"-map","[v]",
                 "-c:v","libx264","-crf",str(args.crf),"-preset","medium",
                 "-pix_fmt","yuv420p", args.out, "-loglevel","error"])
        else:
            # 硬切：concat demuxer
            lst = os.path.join(tmp, "list.txt")
            with open(lst,"w") as f:
                for seg in segs: f.write(f"file '{seg}'\n")
            post = []
            total = sum(durs)
            if args.fade_in > 0:  post.append(f"fade=t=in:st=0:d={args.fade_in}")
            if args.fade_out > 0: post.append(f"fade=t=out:st={total-args.fade_out:.3f}:d={args.fade_out}")
            if not args.no_vignette: post.append("vignette=PI/5")
            vf = ",".join(post) if post else "null"
            run(["ffmpeg","-y","-f","concat","-safe","0","-i",lst,"-vf",vf,
                 "-c:v","libx264","-crf",str(args.crf),"-preset","medium",
                 "-pix_fmt","yuv420p", args.out, "-loglevel","error"])

        final_dur = probe_dur(args.out)
        print(json.dumps({"ok": True, "out": args.out, "duration": round(final_dur,2),
                          "width": W, "height": H, "segments": len(segs),
                          "grade": args.grade, "muted": not args.keep_audio},
                         ensure_ascii=False))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

if __name__ == "__main__":
    main()
