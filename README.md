# Habbo Mobi Renderer (Hack That Works™)

> **Honest warning:** this repo is a **hacky pipeline**, built **with AI assistance**, and optimized for one thing:  
> **rendering Habbo “mobi” furniture visuals** (JSON + PNG spritesheet) with *correct-looking* transparency and effects.
>
> If you’re tired of **halo/fringing**, weird **glow/brightness**, “foggy trails”, or **WebP animations freezing mid-loop**, this is for you.
> Warning: I created this script for the purpose of building a furniture catalog for a fan site. You are responsible for everything you do with it; I am not responsible for anything done by third parties.
---

## What this project does

- Renders **frame PNGs** from a Habbo/Nitro-style **furniture JSON + spritesheet PNG**
- Builds **animated WebP** from the frames
- Handles the annoying parts that commonly break in other constructors:
  - correct alpha workflow (pre-multiply → composite → un-pre-multiply)
  - better behavior for special ink/blend cases (e.g. “ADD”-style effects)
  - optional **STRICT WebP encoding** (full-frames) to prevent mid-animation freezes

---

## Recommended upstream tools (SWF → Nitro → JSON/PNG)

This renderer expects **JSON + spritesheet PNG** as input.  
If your starting point is **classic SWF assets**, the workflow below is a practical way to get there.

### 1) SWF → Nitro (and a bunch of extra utilities)
**Recommended:** `duckietm/all-in-1-converter`

- Provides a **SWF → Nitro generator** for:
  - clothes, furniture, pets, effects.
- Also includes an **asset downloader** and other tooling (merge, SQL generation, compile/decompile Nitro, etc.).

Sources: the repository README describes these capabilities. (See citations in this chat.)

Repo:
- https://github.com/duckietm/all-in-1-converter

> Notes: The repo README mentions dependencies like **.NET SDK** and **NodeJS**, plus a “download tool” flow.

### 2) Nitro → JSON + PNG spritesheet
**Recommended:** `Hab-Track/nitro2png`

- Converts a `.nitro` file into:
  - a `.png` (including “all states of the furni” + the icon)
  - a `.json` containing the extracted data
- Usage is straightforward:
  - `python main.py <file>` (and it supports drag-and-drop onto the script)

Repo:
- https://github.com/Hab-Track/nitro2png


### 3) Optional: bulk-download official Habbo furni SWFs (requires a HabboFurni API token)
If you have a **HabboFurni API token**, you can use the Python script **`swf_massive_downloader`** to **download the full set of official furniture SWFs** from the original Habbo.

- This is useful when your starting point is “I want *all* the official SWFs”, instead of downloading them one-by-one.
- You’ll still need to run **SWF → Nitro** (e.g. `all-in-1-converter`) and then **Nitro → JSON/PNG** (e.g. `nitro2png`) before feeding assets into this renderer.

> Note: `swf_massive_downloader` is **not** part of this repository by default. You must obtain it separately and provide your own API token.

Typical usage (example):
```bash
# Example only — adjust to the script’s actual CLI/options
python swf_massive_downloader.py --token YOUR_HABBOFURNI_TOKEN --out ./swf
```


---

## Quickstart (this repo)

### Requirements
- Python 3.10+ recommended
- Dependencies:
  - `Pillow`
  - `numpy`

Install:
```bash
pip install pillow numpy
```

### Inputs
You need:
- `your_item.json`
- the matching spritesheet `.png`
  - usually the PNG is alongside the JSON or referenced via `spritesheet.meta.image`

### Run (batch runner)
Render everything found in a folder of JSON files:

```bash
python automate_batch.py --json ./items --include_static
```

Outputs:
```
output/
  <item_name>/
    <direction>/
      <anim_id or "static">/
        <color_id>/
          <item_name>.webp
```

---

## The WebP “freeze in the middle” issue

Some WebP decoders/players can glitch when the encoder uses **delta-frame optimization** (only storing differences).  
That can show up as: **animation plays, freezes mid-way, then restarts only when the loop restarts**.

This repo includes a STRICT mode that forces **full-frames** (no delta frames) for better compatibility.

### `--webp_strict` options
- `auto` (default): enables STRICT only when the JSON suggests it’s risky (e.g., special ink/blend or sensitive alpha)
- `on`: always use STRICT
- `off`: never use STRICT

Examples:
```bash
python automate_batch.py --json ./items --include_static --webp_strict auto
python automate_batch.py --json ./items --include_static --webp_strict on
python automate_batch.py --json ./items --include_static --webp_strict off
```

Recommendation:
- keep `auto` for most packs
- switch to `on` if you see mid-loop freezes (often on shiny/gold/effect-heavy furniture)

---

## Useful flags

### Filter directions / colors / animations
```bash
python automate_batch.py --json ./items --directions 0-7
python automate_batch.py --json ./items --colors 0,1,2
python automate_batch.py --json ./items --anims 1-5
```

### Control output characteristics
```bash
python automate_batch.py --json ./items --fps 30 --quality 100 --shadowAlpha 0.6
```

### Keep PNG frames (debugging)
```bash
python automate_batch.py --json ./items --include_static --keep_frames
```

---

## Project files

- `automate_batch.py` — batch pipeline that iterates items/directions/anims/colors and writes output
- `render_py.py` — renders `frame_0000.png`, `frame_0001.png`, ...
- `stitcher.py` — stitches frames into an animated WebP (supports STRICT mode)

---

## Why “hacky”, but worth it

This project is not trying to be elegant. It’s trying to be **visually faithful**.

If you care about:
- clean edges without halos,
- correct-looking glow/effects,
- fewer alpha artifacts,
- and WebP that doesn’t freeze…

…this hack is a solid baseline.

---

## License

Pick what matches your repo’s intent:
- MIT (simple / permissive)
- GPLv3 (forces forks to stay open)

---

## Credits
- Built with a lot of trial-and-error, and AI assistance.
- Thanks to the community and upstream tool authors.
