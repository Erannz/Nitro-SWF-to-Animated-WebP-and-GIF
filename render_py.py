#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("json_path")
    ap.add_argument("png_path")
    ap.add_argument("out_dir")
    ap.add_argument("--size", type=int, default=64)
    ap.add_argument("--anim", default="1")
    ap.add_argument("--direction", type=int, default=0)
    ap.add_argument("--color", default=None)
    ap.add_argument("--shadowAlpha", type=float, default=0.35)
    ap.add_argument("--canvasW", type=int, default=1024)
    ap.add_argument("--canvasH", type=int, default=1024)
    ap.add_argument("--cx", type=int, default=512)
    ap.add_argument("--cy", type=int, default=512)
    return ap.parse_args()


def int_to_rgb(n):
    n = int(n) & 0xFFFFFFFF
    return np.array([(n >> 16) & 255, (n >> 8) & 255, n & 255], dtype=np.uint16)


def get_visualization(data, size):
    for v in data.get("visualizations", []) or []:
        if int(v.get("size", -1)) == int(size):
            return v
    raise RuntimeError(f"Visualização {size} não encontrada.")


def frame_lookup(frames_data, furni_name, raw_key):
    candidates = [raw_key, f"{furni_name}_{raw_key}", f"{furni_name}_{furni_name}_{raw_key}"]
    for c in candidates:
        if c in frames_data:
            return frames_data[c]
    for k, v in frames_data.items():
        if raw_key in k:
            return v
    return None


def build_timelines(anim, layer_count):
    if not anim:
        return {}, 1

    timelines = {}
    layers_anim = anim.get("layers", {}) or {}

    for i in range(layer_count):
        layer_data = layers_anim.get(str(i), {}) or {}
        fseqs = layer_data.get("frameSequences", {}) or {}
        seq = fseqs.get("0") or (list(fseqs.values())[0] if fseqs else None)
        frames = (seq.get("frames", {}) if seq else {}) or {}
        frame_repeat = max(1, int(layer_data.get("frameRepeat", 1) or 1))

        ticks = []
        for t, finfo in frames.items():
            try:
                tt = int(t)
                fid = int((finfo or {}).get("id", 0) or 0)
                ticks.append((tt, fid))
            except Exception:
                pass
        ticks.sort(key=lambda x: x[0])

        if not ticks:
            timelines[i] = [0]
            continue

        last_tick = ticks[-1][0]
        length = (last_tick + 1) * frame_repeat
        tl = [0] * length

        for t, fid in ticks:
            base = t * frame_repeat
            for r in range(frame_repeat):
                if base + r < length:
                    tl[base + r] = fid

        last = 0
        for k in range(len(tl)):
            if tl[k] == 0 and k > 0:
                tl[k] = last
            else:
                last = tl[k]
        timelines[i] = tl

    global_len = max(len(timelines[i]) for i in timelines) if timelines else 1
    return timelines, global_len


def premultiply_rgba(img_u8):
    """straight u8 -> premult u16 (0..255)"""
    rgba = img_u8.astype(np.uint16)
    a = rgba[..., 3:4]
    rgba[..., 0:3] = (rgba[..., 0:3] * a + 127) // 255
    return rgba


def unpremultiply_rgba(prem_u16):
    """premult u16 (0..255) -> straight u8 (sem halo)"""
    out = prem_u16.copy()
    a = out[..., 3:4]
    rgb = out[..., 0:3]

    rgb2 = np.zeros_like(rgb)
    mask = (a > 0)
    rgb2[mask[..., 0]] = (rgb[mask[..., 0]] * 255 + (a[mask[..., 0]] // 2)) // a[mask[..., 0]]
    rgb2 = np.clip(rgb2, 0, 255)

    out[..., 0:3] = rgb2
    return out.astype(np.uint8)


def blend_src_over(dst_prem, src_prem, global_alpha=1.0):
    """Source-over em premultiplied alpha."""
    if global_alpha <= 0:
        return dst_prem

    ga = int(round(global_alpha * 255))
    if ga != 255:
        src = src_prem.copy()
        src[..., 0:3] = (src[..., 0:3] * ga + 127) // 255
        src[..., 3:4] = (src[..., 3:4] * ga + 127) // 255
    else:
        src = src_prem

    sa = src[..., 3:4].astype(np.uint16)
    inv_sa = 255 - sa

    out = dst_prem.copy()
    out[..., 0:3] = src[..., 0:3] + (dst_prem[..., 0:3] * inv_sa + 127) // 255
    out[..., 3:4] = src[..., 3:4] + (dst_prem[..., 3:4] * inv_sa + 127) // 255
    return out


def blend_multiply(dst_prem, src_prem, global_alpha=1.0):
    """
    Multiply correto (modelo W3C/Canvas) em premultiplied alpha.

    Ao = As + Ab - As*Ab
    Co = Cs*(1-Ab) + Cb*(1-As) + (As*Ab)*B(Cb/Ab, Cs/As)
    B(x,y) = x*y
    """
    if global_alpha <= 0:
        return dst_prem

    ga = int(round(global_alpha * 255))
    if ga != 255:
        src = src_prem.copy()
        src[..., 0:3] = (src[..., 0:3] * ga + 127) // 255
        src[..., 3:4] = (src[..., 3:4] * ga + 127) // 255
    else:
        src = src_prem

    cb = dst_prem[..., 0:3].astype(np.uint32)
    ab = dst_prem[..., 3:4].astype(np.uint32)
    cs = src[..., 0:3].astype(np.uint32)
    aS = src[..., 3:4].astype(np.uint32)

    ab3 = np.repeat(ab, 3, axis=2)
    as3 = np.repeat(aS, 3, axis=2)

    cb_straight = np.where(ab3 > 0, (cb * 255 + (ab3 // 2)) // ab3, 0)
    cs_straight = np.where(as3 > 0, (cs * 255 + (as3 // 2)) // as3, 0)
    cb_straight = np.clip(cb_straight, 0, 255)
    cs_straight = np.clip(cs_straight, 0, 255)

    B = (cb_straight * cs_straight + 127) // 255

    prem = (B * as3 * ab3 + 32512) // 65025

    inv_ab = 255 - ab
    inv_as = 255 - aS
    inv_ab3 = np.repeat(inv_ab, 3, axis=2)
    inv_as3 = np.repeat(inv_as, 3, axis=2)

    term1 = (cs * inv_ab3 + 127) // 255
    term2 = (cb * inv_as3 + 127) // 255
    out_rgb = term1 + term2 + prem
    out_rgb = np.clip(out_rgb, 0, 255).astype(np.uint16)

    out_a = aS + ab - (aS * ab + 127) // 255
    out_a = np.clip(out_a, 0, 255).astype(np.uint16)

    out = dst_prem.copy()
    out[..., 0:3] = out_rgb
    out[..., 3:4] = out_a
    return out


def tint_sprite(sprite_u8, tint_rgb_u16):
    """Tint multiplicativo em rgb, preserva alpha."""
    s = sprite_u8.copy().astype(np.uint16)
    s[..., 0] = (s[..., 0] * tint_rgb_u16[0] + 127) // 255
    s[..., 1] = (s[..., 1] * tint_rgb_u16[1] + 127) // 255
    s[..., 2] = (s[..., 2] * tint_rgb_u16[2] + 127) // 255
    return s.astype(np.uint8)


def apply_add_ink(sprite_u8):
    """
    ✅ FIX CRÍTICO
    Replica o comportamento do Node/skia-canvas:
    - primeiro efetivamente "premultiplica" RGB pelo alpha (como se tivesse sido desenhado sobre preto)
    - lum = max(premult_rgb)
    - alpha = lum
    - rgb = premult_rgb * 255 / lum
    """
    s = sprite_u8.astype(np.uint16)

    rgb = s[..., 0:3]
    a = s[..., 3:4]  # HxWx1

    # premult no preto: rgb_p = rgb * a / 255
    rgb_p = (rgb * a + 127) // 255  # HxWx3

    lum = np.max(rgb_p, axis=2).astype(np.uint16)  # HxW
    out = np.zeros_like(s)

    mask = lum > 0

    # rgb_out = rgb_p * 255 / lum
    for ch in range(3):
        chv = rgb_p[..., ch]
        o = np.zeros_like(chv)
        o[mask] = np.minimum(255, (chv[mask] * 255 + (lum[mask] // 2)) // lum[mask])
        out[..., ch] = o

    out[..., 3] = lum  # alpha = lum (0..255)
    return out.astype(np.uint8)


def main():
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(Path(args.json_path).read_text(encoding="utf-8"))
    furni_name = data.get("name") or Path(args.json_path).stem
    viz = get_visualization(data, args.size)

    layer_count = int(viz.get("layerCount", 1) or 1)
    physical_layers = [chr(ord("a") + i) for i in range(layer_count)]

    layers_cfg = (viz.get("layers", {}) or {})
    layers_meta = []
    for i in range(layer_count):
        cfg = layers_cfg.get(str(i), {}) or {}
        layers_meta.append({
            "id": i,
            "letter": physical_layers[i],
            "ink": str(cfg.get("ink", "NORMAL")).upper(),
            "z": float(cfg.get("z", 0) or 0),
            "alpha": float((cfg.get("alpha", 255) if cfg.get("alpha") is not None else 255)) / 255.0
        })
    layers_meta.sort(key=lambda x: (x["z"], x["id"]))

    tint_by_layer = None
    if args.color is not None:
        colors = viz.get("colors", {}) or {}
        chosen = colors.get(str(args.color))
        if chosen and chosen.get("layers"):
            tint_by_layer = {}
            for lid, layer_info in (chosen.get("layers") or {}).items():
                if layer_info and layer_info.get("color") is not None:
                    tint_by_layer[int(lid)] = int_to_rgb(layer_info["color"])

    animations = viz.get("animations", {}) or {}
    timelines, global_len = build_timelines(animations.get(str(args.anim)), layer_count)

    sheet = Image.open(args.png_path).convert("RGBA")
    sheet_np = np.array(sheet, dtype=np.uint8)

    assets = data.get("assets", {}) or {}
    frames_data = (data.get("spritesheet", {}) or {}).get("frames", {}) or {}

    W, H = args.canvasW, args.canvasH
    cx, cy = args.cx, args.cy

    frames_prem = []
    g_minx, g_miny, g_maxx, g_maxy = W, H, -1, -1

    def draw_sprite(dst_prem, asset_name, dx_base, dy_base, ink, alpha, layer_id, composite="normal"):
        asset = assets.get(asset_name)
        if not asset:
            return dst_prem

        source_key = asset.get("source") or asset_name
        fe = frame_lookup(frames_data, furni_name, source_key)
        if not fe or not fe.get("frame"):
            return dst_prem

        fr = fe["frame"]
        fw, fh = int(fr["w"]), int(fr["h"])
        sx, sy = int(fr["x"]), int(fr["y"])

        dx = int(dx_base - int(asset.get("x", 0) or 0))
        dy = int(dy_base - int(asset.get("y", 0) or 0))

        sprite = sheet_np[sy:sy+fh, sx:sx+fw, :].copy()

        if ink == "ADD":
            sprite = apply_add_ink(sprite)

        if layer_id != "sd" and tint_by_layer is not None:
            t = tint_by_layer.get(int(layer_id))
            if t is not None and not (int(t[0]) == 255 and int(t[1]) == 255 and int(t[2]) == 255):
                sprite = tint_sprite(sprite, t)

        src_prem = premultiply_rgba(sprite)

        x0 = max(0, dx)
        y0 = max(0, dy)
        x1 = min(W, dx + fw)
        y1 = min(H, dy + fh)
        if x1 <= x0 or y1 <= y0:
            return dst_prem

        sx0 = x0 - dx
        sy0 = y0 - dy
        sx1 = sx0 + (x1 - x0)
        sy1 = sy0 + (y1 - y0)

        dst_region = dst_prem[y0:y1, x0:x1, :]
        src_region = src_prem[sy0:sy1, sx0:sx1, :]

        if composite == "multiply":
            dst_region = blend_multiply(dst_region, src_region, global_alpha=float(alpha))
        else:
            dst_region = blend_src_over(dst_region, src_region, global_alpha=float(alpha))

        dst_prem[y0:y1, x0:x1, :] = dst_region
        return dst_prem

    shadow_key = f"{furni_name}_{args.size}_sd_{args.direction}_0"

    for t in range(global_len):
        canvas = np.zeros((H, W, 4), dtype=np.uint16)

        # sombra (multiply)
        canvas = draw_sprite(
            canvas, shadow_key, cx, cy,
            ink="NORMAL", alpha=float(args.shadowAlpha),
            layer_id="sd", composite="multiply"
        )

        for layer in layers_meta:
            tl = timelines.get(layer["id"])
            fid = tl[t % len(tl)] if tl else 0
            asset_key = f"{furni_name}_{args.size}_{layer['letter']}_{args.direction}_{fid}"
            canvas = draw_sprite(
                canvas, asset_key, cx, cy,
                ink=layer["ink"], alpha=float(layer["alpha"]),
                layer_id=layer["id"], composite="normal"
            )

        frames_prem.append(canvas)

        a = canvas[..., 3]
        ys, xs = np.where(a > 0)
        if xs.size:
            g_minx = min(g_minx, int(xs.min()))
            g_miny = min(g_miny, int(ys.min()))
            g_maxx = max(g_maxx, int(xs.max()))
            g_maxy = max(g_maxy, int(ys.max()))

    if g_maxx < 0:
        raise RuntimeError("Nada renderizado (bbox vazia). Verifique assets/frames.")

    crop_w = g_maxx - g_minx + 1
    crop_h = g_maxy - g_miny + 1

    for i, frm in enumerate(frames_prem):
        cropped = frm[g_miny:g_miny+crop_h, g_minx:g_minx+crop_w, :]
        out_u8 = unpremultiply_rgba(cropped)
        Image.fromarray(out_u8, mode="RGBA").save(out_dir / f"frame_{i:04d}.png")

    print(f"[SUCESSO] {global_len} frames exportados em: {out_dir}")


if __name__ == "__main__":
    main()
