#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
stitcher.py
Montagem de WebP animado a partir de frames PNG.

Mudança importante:
- Adiciona modo STRICT para evitar "nevoa/trail" em efeitos (ex.: ink=ADD),
  forçando full-frames (sem otimização delta) e preservando cores transparentes.

Requisitos: pip install Pillow
Uso:
  python stitcher.py --input ./temp_frames --out mobiliario.webp --fps 15
  python stitcher.py --input ./temp_frames --out mobiliario.webp --fps 30 --strict
"""

import argparse
import os
import glob
import re
from PIL import Image


def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower()
            for text in re.split('([0-9]+)', s)]


def main():
    parser = argparse.ArgumentParser(description="Montador de WebP Animado (com modo STRICT).")
    parser.add_argument("--input", required=True, help="Diretório com os frames PNG.")
    parser.add_argument("--out", required=True, help="Nome do arquivo WebP de saída.")
    parser.add_argument("--fps", type=int, default=15, help="Frames por segundo.")
    parser.add_argument("--quality", type=int, default=100, help="Qualidade (0-100).")

    # NOVOS:
    parser.add_argument("--strict", action="store_true",
                        help="Evita delta/blend e preserva cores transparentes (recomendado p/ ink=ADD).")
    parser.add_argument("--no_minimize", action="store_true",
                        help="Desliga otimização delta (full-frames), sem forçar 'exact'.")

    args = parser.parse_args()

    frame_pattern = os.path.join(args.input, "*.png")
    frame_files = sorted(glob.glob(frame_pattern), key=natural_sort_key)

    if not frame_files:
        print(f"Erro: Nenhum frame encontrado em {args.input}")
        return

    print(f"A processar {len(frame_files)} frames de forma sequencial...")

    frames = []
    for f in frame_files:
        img = Image.open(f).convert("RGBA")
        frames.append(img)

    duration_ms = int(1000 / args.fps)

    # Parâmetros base
    save_kwargs = dict(
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        format="WEBP",
        lossless=True,
        quality=args.quality,
        method=6,
    )

    # IMPORTANTE: estes dois evitam "nevoa" e bleed em muitos casos
    # - minimize_size=False => não tenta delta frames
    # - exact=True => preserva valores RGB em pixels com alpha baixo
    if args.strict:
        save_kwargs["minimize_size"] = False
        save_kwargs["exact"] = True
    elif args.no_minimize:
        save_kwargs["minimize_size"] = False

    try:
        frames[0].save(args.out, **save_kwargs)

        file_size = os.path.getsize(args.out) / 1024
        print(f"[SUCESSO] Animação guardada em: {args.out} ({file_size:.2f} KB)")

    except Exception as e:
        print(f"[ERRO] Falha ao compor WebP: {e}")


if __name__ == "__main__":
    main()
