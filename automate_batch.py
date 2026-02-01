#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd, cwd=None):
    p = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        shell=False
    )
    return p.returncode == 0, p.stdout, p.stderr, p.returncode


def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)


def parse_list_or_range(s: str):
    """
    Aceita:
      "all"
      "0,1,2"
      "0-7"
      "0-7,10,12-14"
    Retorna lista de ints ou None (para all).
    """
    if s is None:
        return None
    s = s.strip().lower()
    if s in ("all", ""):
        return None

    out = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a.strip()); b = int(b.strip())
            if b < a:
                a, b = b, a
            out.extend(range(a, b + 1))
        else:
            out.append(int(part))

    # dedupe preserving order
    seen = set()
    final = []
    for x in out:
        if x not in seen:
            seen.add(x)
            final.append(x)
    return final


def choose_visualization(data, size: int):
    for v in (data.get("visualizations") or []):
        if int(v.get("size", -1)) == int(size):
            return v
    raise RuntimeError(f"Visualização size={size} não encontrada no JSON.")


def detect_colors(viz):
    colors = viz.get("colors") or {}
    ids = []
    for k in colors.keys():
        try:
            ids.append(int(k))
        except Exception:
            pass
    # se não houver colors, assume [0] (não-tint)
    return sorted(ids) if ids else [0]


def detect_anims(viz):
    anims = viz.get("animations") or {}
    ids = []
    for k in anims.keys():
        try:
            ids.append(int(k))
        except Exception:
            pass
    return sorted(ids)


def detect_directions_from_assets(data, furni_name: str, size: int):
    """
    Detecta direções procurando keys existentes no assets.
    Prioriza sombra: <name>_<size>_sd_<dir>_0
    Fallback: qualquer layer: <name>_<size>_<letter>_<dir>_<frame>
    """
    assets = data.get("assets") or {}
    dirs = set()

    pat_sd = re.compile(rf"^{re.escape(furni_name)}_{size}_sd_(\d+)_0$")
    pat_any = re.compile(rf"^{re.escape(furni_name)}_{size}_[a-z]_(\d+)_\d+$")

    for k in assets.keys():
        m = pat_sd.match(k)
        if m:
            dirs.add(int(m.group(1)))

    if not dirs:
        for k in assets.keys():
            m = pat_any.match(k)
            if m:
                dirs.add(int(m.group(1)))

    return sorted(dirs)


def json_to_png_path(json_path: Path, data: dict):
    meta = ((data.get("spritesheet") or {}).get("meta") or {})
    img_name = meta.get("image")
    if img_name:
        candidate = json_path.parent / img_name
        if candidate.exists():
            return candidate

    candidate2 = json_path.with_suffix(".png")
    if candidate2.exists():
        return candidate2

    pngs = list(json_path.parent.glob("*.png"))
    if len(pngs) == 1:
        return pngs[0]

    return None


def copy_frames_to_dest(temp_frames_dir: Path, dest_dir: Path):
    frames_out = dest_dir / "frames"
    ensure_dir(frames_out)
    for f in sorted(temp_frames_dir.glob("frame_*.png")):
        shutil.copy2(f, frames_out / f.name)


def process_one_item(
    json_path: Path,
    png_path: Path,
    render_py: Path,
    stitcher: Path,
    size: int,
    fps: int,
    shadow_alpha: float,
    quality: int,
    out_root: Path,
    temp_root: Path,
    forced_dirs,
    forced_colors,
    forced_anims,
    include_static: bool,
    keep_frames: bool,
    stop_on_error: bool,
    retries: int
):
    data = json.loads(json_path.read_text(encoding="utf-8"))
    furni_name = data.get("name") or json_path.stem
    viz = choose_visualization(data, size)

    auto_dirs = detect_directions_from_assets(data, furni_name, size)
    auto_cols = detect_colors(viz)
    auto_anims = detect_anims(viz)

    directions = forced_dirs if forced_dirs is not None else auto_dirs
    colors = forced_colors if forced_colors is not None else auto_cols

    # anims: se o usuário forçou, usa os ids. senão usa detectado.
    anim_ids = forced_anims if forced_anims is not None else auto_anims

    # compor lista de "animações" a exportar:
    # - sempre 'static' (se include_static)
    # - + ids detectados
    anims = []
    if include_static:
        anims.append("static")
    for a in anim_ids:
        anims.append(str(a))

    if not directions:
        raise RuntimeError(f"[{furni_name}] Não detectei directions. Use --directions manual.")
    if not colors:
        raise RuntimeError(f"[{furni_name}] Não detectei colors. Use --colors manual.")
    if not anims:
        # caso extremo: sem static e sem anims
        raise RuntimeError(f"[{furni_name}] Sem anims e static desativado. Nada para exportar.")

    print(f"\n=== ITEM: {furni_name} ===")
    print(f"[INFO] json={json_path.name} png={png_path.name} size={size} fps={fps} shadowAlpha={shadow_alpha}")
    print(f"[INFO] directions={directions}")
    print(f"[INFO] anims={anims}")
    print(f"[INFO] colors={colors}")

    total = len(directions) * len(anims) * len(colors)
    done = 0
    failures = 0

    for d in directions:
        for anim in anims:
            for c in colors:
                done += 1

                # output/<item>/<dir>/<anim>/<color>/
                dest_dir = out_root / furni_name / str(d) / str(anim) / str(c)
                ensure_dir(dest_dir)
                out_webp = dest_dir / f"{furni_name}.webp"
                log_file = dest_dir / f"{furni_name}.log.txt"

                # temp/<item>__dir__anim__color/
                temp_dir = temp_root / f"{furni_name}__dir{d}__anim{anim}__col{c}"
                if temp_dir.exists():
                    shutil.rmtree(temp_dir, ignore_errors=True)
                ensure_dir(temp_dir)

                print(f">> [{done}/{total}] dir={d} anim={anim} color={c}")

                # anim param: para static usamos um id inexistente (ex: "static")
                cmd_render = [
                    sys.executable, str(render_py),
                    str(json_path), str(png_path), str(temp_dir),
                    f"--size={size}",
                    f"--anim={anim}",
                    f"--direction={d}",
                    f"--color={c}",
                    f"--shadowAlpha={shadow_alpha}",
                ]

                ok = False
                last_stdout = ""
                last_stderr = ""
                last_code = 0

                for attempt in range(retries + 1):
                    ok, stdout, stderr, code = run_cmd(cmd_render)
                    last_stdout, last_stderr, last_code = stdout, stderr, code
                    if ok:
                        break

                if not ok:
                    failures += 1
                    log_file.write_text(
                        f"[RENDER FAIL] code={last_code}\n\nCMD:\n{' '.join(cmd_render)}\n\nSTDOUT:\n{last_stdout}\n\nSTDERR:\n{last_stderr}\n",
                        encoding="utf-8"
                    )
                    print(f"[FALHA] Render. Log: {log_file}")
                    if stop_on_error:
                        return failures
                    continue

                cmd_stitch = [
                    sys.executable, str(stitcher),
                    "--input", str(temp_dir),
                    "--out", str(out_webp),
                    "--fps", str(fps),
                    "--quality", str(quality),
                ]
                ok2, stdout2, stderr2, code2 = run_cmd(cmd_stitch)
                if not ok2:
                    failures += 1
                    log_file.write_text(
                        f"[STITCH FAIL] code={code2}\n\nCMD:\n{' '.join(cmd_stitch)}\n\nSTDOUT:\n{stdout2}\n\nSTDERR:\n{stderr2}\n",
                        encoding="utf-8"
                    )
                    print(f"[FALHA] Stitch. Log: {log_file}")
                    if stop_on_error:
                        return failures
                    continue

                if keep_frames:
                    copy_frames_to_dest(temp_dir, dest_dir)

                if not keep_frames:
                    shutil.rmtree(temp_dir, ignore_errors=True)

                print(f"[OK] {out_webp}")

    print(f"=== FINAL {furni_name}: falhas={failures} combos={total} ===")
    return failures


def main():
    ap = argparse.ArgumentParser(description="Batch export: output/<item>/<dir>/<anim>/<color>/ (inclui static)")
    ap.add_argument("--json", required=True, help="Arquivo .json ou pasta com vários .json")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--shadowAlpha", type=float, default=0.60)
    ap.add_argument("--quality", type=int, default=100)

    ap.add_argument("--render_py", default="render_py.py")
    ap.add_argument("--stitcher", default="stitcher.py")

    ap.add_argument("--out_root", default="./output")
    ap.add_argument("--temp_root", default="./temp_build")

    ap.add_argument("--directions", default="all")
    ap.add_argument("--colors", default="all")
    ap.add_argument("--anims", default="all")

    ap.add_argument("--include_static", action="store_true", help="Exporta também pose estática (anim=static)")
    ap.add_argument("--keep_frames", action="store_true", help="Copia frames PNG para output/.../frames/")
    ap.add_argument("--stop_on_error", action="store_true")
    ap.add_argument("--retries", type=int, default=0)

    args = ap.parse_args()

    json_in = Path(args.json)
    render_py = Path(args.render_py)
    stitcher = Path(args.stitcher)
    out_root = Path(args.out_root)
    temp_root = Path(args.temp_root)

    if not render_py.exists():
        print(f"[ERRO] render_py não encontrado: {render_py}")
        sys.exit(2)
    if not stitcher.exists():
        print(f"[ERRO] stitcher.py não encontrado: {stitcher}")
        sys.exit(2)

    ensure_dir(out_root)
    ensure_dir(temp_root)

    forced_dirs = parse_list_or_range(args.directions)
    forced_cols = parse_list_or_range(args.colors)
    forced_anims = parse_list_or_range(args.anims)

    json_files = []
    if json_in.is_dir():
        json_files = sorted(json_in.glob("*.json"))
        if not json_files:
            print(f"[ERRO] Nenhum .json encontrado na pasta: {json_in}")
            sys.exit(2)
    else:
        if not json_in.exists():
            print(f"[ERRO] JSON não encontrado: {json_in}")
            sys.exit(2)
        json_files = [json_in]

    total_failures = 0

    for jp in json_files:
        try:
            data = json.loads(jp.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[ERRO] Falha lendo JSON {jp}: {e}")
            total_failures += 1
            if args.stop_on_error:
                break
            continue

        png_path = json_to_png_path(jp, data)
        if png_path is None or not png_path.exists():
            furni_name = data.get("name") or jp.stem
            print(f"[ERRO] PNG do item '{furni_name}' não encontrado. (meta.image ou <stem>.png). JSON: {jp}")
            total_failures += 1
            if args.stop_on_error:
                break
            continue

        try:
            failures = process_one_item(
                json_path=jp,
                png_path=png_path,
                render_py=render_py,
                stitcher=stitcher,
                size=args.size,
                fps=args.fps,
                shadow_alpha=args.shadowAlpha,
                quality=args.quality,
                out_root=out_root,
                temp_root=temp_root,
                forced_dirs=forced_dirs,
                forced_colors=forced_cols,
                forced_anims=forced_anims,
                include_static=args.include_static,
                keep_frames=args.keep_frames,
                stop_on_error=args.stop_on_error,
                retries=args.retries
            )
            total_failures += failures
            if failures and args.stop_on_error:
                break
        except Exception as e:
            print(f"[ERRO] {jp.name}: {e}")
            total_failures += 1
            if args.stop_on_error:
                break

    print(f"\n--- Batch terminado. falhas_totais={total_failures} ---")
    sys.exit(1 if total_failures else 0)


if __name__ == "__main__":
    main()
