#!/usr/bin/env python3
"""
r4d4r.py 

Usage:
    python3 r4d4r.py -t example.com -o results
"""
import asyncio
import math
import random
import shlex
import sys
import time
import os
from pathlib import Path
import argparse
import shutil

# ---------------------------
# ---------- CONFIG ----------
# ---------------------------
LOGO = [
    "__________    _____________      _______________  ",
    "\\______   \\  /  |  \\______ \\    /  |  \\______   \\ ",
    " |       _/ /   |  ||    |  \\  /   |  ||       _/ ",
    " |    |   \\/    ^   /    `   \\/    ^   /    |   \\ ",
    " |____|_  /\\____   /_______  /\\____   ||____|_  / ",
    "        \\/      |__|       \\/      |__|       \\/  "
]

RADAR_RADIUS = 12
UI_SLEEP = 0.08            # refresh rate for UI (seconds)
SWEEP_STEP = 0.12         # radians per frame
BLIP_SPAWN_CHANCE = 0.06
MAX_BLIPS = 18
CONSOLE_HEIGHT = 8
USE_COLOR = True          # set False to disable ANSI colors in UI

# ANSI
CSI = "\033["
RESET = CSI + "0m"
BOLD = CSI + "1m"
DIM = CSI + "2m"
GREEN = CSI + "32m"
YELLOW = CSI + "33m"
RED = CSI + "31m"
BLUE = CSI + "34m"

# ---------------------------
# ---------- ARGPARSING ------
# ---------------------------
def m4in():
    parser = argparse.ArgumentParser(
        description="R4D4R — pipeline web asset on target domain"
    )
    parser.add_argument("-t", "--target", required=True, help="Target (example.com)")
    parser.add_argument("-o", "--outdir", default="/data/r4d4r_result", help="Output directory")
    parser.add_argument("--timeout", type=int, default=120, help="Timeout per command (s)")
    return parser.parse_args()

# ---------------------------
# ---------- SUBPROCESS helper
# ---------------------------
async def run_process(cmd_args, *, cwd=None, timeout=None, use_shell=False):
    """
    cmd_args: list (recommended) or string (if use_shell=True)
    returns (returncode, stdout_str, stderr_str)
    """
    if use_shell:
        if isinstance(cmd_args, (list, tuple)):
            cmd = " ".join(shlex.quote(str(x)) for x in cmd_args)
        else:
            cmd = str(cmd_args)
        create = asyncio.create_subprocess_shell
        proc_args = (cmd,)
    else:
        create = asyncio.create_subprocess_exec
        if isinstance(cmd_args, (list, tuple)):
            proc_args = tuple(cmd_args)
        else:
            proc_args = tuple(shlex.split(str(cmd_args)))

    proc = await create(
        *proc_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd
    )

    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        await proc.wait()
        return -1, "", f"TIMEOUT after {timeout}s"

    stdout = out.decode(errors="ignore") if out else ""
    stderr = err.decode(errors="ignore") if err else ""
    return proc.returncode, stdout, stderr

# ---------------------------
# ---------- RADAR & UI -----
# ---------------------------

class Blip:
    def __init__(self, radius):
        self.r = random.uniform(1.0, radius - 1.0)
        self.theta = random.random() * 2 * math.pi
        self.age = 0
        self.hit_timer = 0
        self.move = random.uniform(-0.02, 0.02)

    def step(self):
        self.theta += self.move
        self.age += 1
        if self.hit_timer > 0:
            self.hit_timer -= 1

    def mark_hit(self):
        self.hit_timer = 8

    def alive(self):
        return self.age < 1000

def color(s, col):
    if not USE_COLOR:
        return s
    return f"{col}{s}{RESET}"

def generate_circle(radius):
    grid = []
    for y in range(-radius, radius + 1):
        line = ""
        for x in range(-radius, radius + 1):
            # adjust vertical scale (chars are taller); tweak factor for roundness
            if x * x + (2 * y) * (2 * y) <= (radius * radius):
                line += " "
            else:
                line += " "
        grid.append(list(line))
    return grid  # as list of char lists for mutability

def draw_radar_frame(radius, sweep_angle, blips):
    size = radius * 2 + 1
    cx = radius
    cy = radius
    # start with empty grid
    grid = [[" " for _ in range(size)] for __ in range(size)]

    # draw border (approx)
    for deg in range(0, 360, 1):
        theta = math.radians(deg)
        x = int(round(cx + math.cos(theta) * radius))
        y = int(round(cy + math.sin(theta) * radius / 1.8))
        if 0 <= x < size and 0 <= y < size:
            grid[y][x] = color("·", CSI + "32;2m") if USE_COLOR else "·"

    # fill interior with faint dots
    for y in range(size):
        for x in range(size):
            dx = x - cx
            dy = (y - cy) * 1.8
            if dx * dx + dy * dy <= radius * radius:
                if grid[y][x] == " ":
                    grid[y][x] = color("·", DIM + CSI + "32m") if USE_COLOR else "."

    # draw sweep (multiple steps for trail)
    trail_len = 6
    for t in range(trail_len):
        a = sweep_angle - t * (SWEEP_STEP * 0.9)
        for r in range(radius):
            xr = int(round(cx + math.cos(a) * r))
            yr = int(round(cy + math.sin(a) * r / 1.8))
            if 0 <= xr < size and 0 <= yr < size:
                ch = "*" if t == 0 else "."
                grid[yr][xr] = color(ch, GREEN) if USE_COLOR else "*"

    # draw blips
    for b in blips:
        bx = int(round(cx + math.cos(b.theta) * b.r))
        by = int(round(cy + math.sin(b.theta) * b.r / 1.8))
        if 0 <= bx < size and 0 <= by < size:
            if b.hit_timer > 0:
                grid[by][bx] = color("●", YELLOW + BOLD) if USE_COLOR else "O"
            else:
                grid[by][bx] = color("•", RED) if USE_COLOR else "o"

    # convert rows to strings
    lines = ["".join(row) for row in grid]
    return lines

def draw_dashboard(logo_lines, radar_lines, messages, console_height=CONSOLE_HEIGHT):
    logo_width = max(len(l) for l in logo_lines)
    radar_width = max(len(l) for l in radar_lines)
    output_lines = []
    max_lines = max(len(logo_lines), len(radar_lines))
    for i in range(max_lines):
        logo_part = logo_lines[i] if i < len(logo_lines) else " " * logo_width
        radar_part = radar_lines[i] if i < len(radar_lines) else " " * radar_width
        output_lines.append(f"{logo_part}   {radar_part}")
    sep = "-" * (logo_width + 3 + radar_width)
    output_lines.append(sep)
    for msg in messages[-console_height:]:
        output_lines.append(msg)
    return "\n".join(output_lines)

# UI coroutine
async def ui_loop(messages, stop_event, radius=RADAR_RADIUS):
    sweep = 0.0
    blips = []

    sys.stdout.write("\033[?25l")  # hide cursor

    try:
        # --------------------------
        # Phase 1 : logo pendant 3s
        # --------------------------
        start_time = time.time()
        while time.time() - start_time < 3:
            sys.stdout.write("\033[H\033[2J")
            print("\n")  # clear screen
            print("\n".join(LOGO))
            print("\n")
            print(color("R4D4R by @Romso\n\n", BOLD))
            # afficher messages récents sous le logo
            recent_msgs = messages[-CONSOLE_HEIGHT:]
            for m in recent_msgs:
                print(m.ljust(max(len(l) for l in LOGO)))
            sys.stdout.flush()
            await asyncio.sleep(0.1)  # refresh messages régulièrement

        # --------------------------
        # Phase 2 : radar + messages
        # --------------------------
        while not stop_event.is_set():
            # spawn & step blips
            if len(blips) < MAX_BLIPS and random.random() < BLIP_SPAWN_CHANCE:
                blips.append(Blip(radius))
            for b in blips:
                b.step()
            blips = [b for b in blips if b.alive()]

            # hit detection
            for b in blips:
                diff = (sweep - b.theta + math.pi) % (2 * math.pi) - math.pi
                tol = 0.25 * (1.0 / max(0.4, b.r / radius))
                if abs(diff) < tol:
                    b.mark_hit()

            # dessiner radar
            radar_lines = draw_radar_frame(radius, sweep, blips)

            label = color("R4D4R by @Romso\n\n", BOLD)
            radar_lines.append(label.center(len(radar_lines[0])))

            # clear screen + afficher radar
            sys.stdout.write("\033[H\033[2J")
            sys.stdout.write("\n".join(radar_lines) )

            # afficher messages récents sous le radar
            recent_msgs = messages[-CONSOLE_HEIGHT:]
            for m in recent_msgs:
                sys.stdout.write(m.ljust(len(radar_lines[0])) + "\n")

            sys.stdout.flush()

            sweep += SWEEP_STEP
            if sweep >= 2 * math.pi:
                sweep -= 2 * math.pi

            await asyncio.sleep(UI_SLEEP)

    except asyncio.CancelledError:
        pass
    finally:
        sys.stdout.write("\033[?25h")  # show cursor
        sys.stdout.flush()

# ---------------------------
# ---------- Pipeline -------
# ---------------------------

def append_msg(messages, s):
    timestamp = time.strftime("%H:%M:%S")
    messages.append(f"[{color(timestamp, YELLOW + BOLD)}] {s}")

async def r4d4r_pipeline(target: str, outdir: Path, timeout: int, messages):

    append_msg(messages, color(f"R4d4r started for {target}, {outdir}", BOLD))

    outdir = Path(f"/data/{outdir}") 

    outdir.mkdir(parents=True, exist_ok=True)

    # 1) subfinder + assetfinder in parallel
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Starting Subfinder + Assetfinder")
    subfinder_cmd = ["subfinder", "-d", target, "-all"]
    assetfinder_cmd = ["assetfinder", target, "--subs-only"]

    t_sub = asyncio.create_task(run_process(subfinder_cmd, timeout=timeout))
    t_asset = asyncio.create_task(run_process(assetfinder_cmd, timeout=timeout))
    (code1, out1, err1), (code2, out2, err2) = await asyncio.gather(t_sub, t_asset)

    domain1 = outdir / "domain1.txt"
    domain2 = outdir / "domain2.txt"
    domain1.write_text(out1)
    domain2.write_text(out2)
    append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} Subfinder done ({len(out1.splitlines())} lines), Assetfinder done ({len(out2.splitlines())} lines)")
    if code1 != 0:
        append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)} Subfinder exit {code1}")
        if err1:
            append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)}  Subfinder stderr: {err1.splitlines()[0] if err1 else ''}")
    if code2 != 0:
        append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)} Assetfinder exit {code2}")
        if err2:
            append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)}  Assetfinder stderr: {err2.splitlines()[0] if err2 else ''}")

    # 2) combine domains (sort -u)
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Combining domains (sort -u)")
    sort_cmd = ["sort", "-u", str(domain1), str(domain2)]
    code, out, err = await run_process(sort_cmd, timeout=30, use_shell=False)
    if code == 0:
        domain_all = outdir / "domains.txt"
        domain_all.write_text(out if out.endswith("\n") else out + "\n")
        append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} Domains combined -> {domain_all} ({len(out.splitlines())} entries)")

        rm_domain12 = ["rm",domain1,domain2]
        await run_process(rm_domain12,timeout=30, use_shell=False)
    else:
        append_msg(messages, f"{color('[', BOLD)}{color('ERROR', RED + BOLD)}{color(']', BOLD)} sort failed (code {code})")
        domain_all = outdir / "domains.txt"
        domain_all.write_text("")  # keep empty

    # 3) httpx status + live in parallel (using shell pipelines for simplicity)
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Running httpx (status + live)")
    status_file = outdir / "status.txt"
    live_file = outdir / "live.txt"
    cmd_status = f"cat {shlex.quote(str(domain_all))} | httpx -sc > {shlex.quote(str(status_file))}"
    cmd_live = f"cat {shlex.quote(str(domain_all))} | httpx > {shlex.quote(str(live_file))}"

    t1 = asyncio.create_task(run_process(cmd_status, use_shell=True, timeout=timeout))
    t2 = asyncio.create_task(run_process(cmd_live, use_shell=True, timeout=timeout))
    r1, r2 = await asyncio.gather(t1, t2)
    append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} httpx tasks finished (status: Ok, live: Ok")

    # 4) subzy
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Starting Subzy (enumeration & takeover checks)")
    subzy_dir = outdir / "Subzy"
    subzy_dir.mkdir(parents=True, exist_ok=True)  # crée le dossier si nécessaire
    subzy_log = subzy_dir / "subzy.txt"
    subzy_cmd = ["subzy", "run", "--targets", str(domain_all)]
    code, out, err = await run_process(subzy_cmd, timeout=300, use_shell=False)
    subzy_log.write_text(out if out else "")
    if err:
        (subzy_dir / "subzy.err").write_text(err)
    append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} Subzy finished (code={code})")

    # 4b) display vulnerable context to messages
    # if subzy_log.exists():
    #     try:
    #         lines = subzy_log.read_text(errors="ignore").splitlines()
    #         for i, line in enumerate(lines):
    #             if "[32mVULNERABLE[0m" in line:
    #                 append_msg(messages, line)
    #                 # add next two non-empty lines
    #                 added = 0
    #                 j = i + 1
    #                 while added < 2 and j < len(lines):
    #                     c = lines[j].strip()
    #                     if c and not c.startswith('---'):
    #                         append_msg(messages, c)
    #                         added += 1
    #                     j += 1
    #     except Exception:
    #         pass

    # 5) blh (Broken-Link-Hijacker)
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Running BLH (Broken-Link-Hijacker)...")

    blh_output = outdir / "BLH"
    blh_output.mkdir(parents=True, exist_ok=True)  # crée le dossier si nécessaire
    blh_log = blh_output / "blh.txt"
    blh_exe = shutil.which("blh")
    blh_cmd = [blh_exe or "blh", "-d 1", f"https://{target}"]
    code, out, err = await run_process(blh_cmd, timeout=300, use_shell=False)
    if out and out.strip():
        blh_log.write_text(out)
        append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} BLH output written -> {blh_output}")
    if err:
        (blh_output / "blh.err").write_text(err)
        append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)} BLH stderr (preview): {err.splitlines()[0] if err else ''}")

    # 6) corsy (CORS)
    append_msg(messages, f"{color('[', BOLD)}{color('+', BLUE + BOLD)}{color(']', BOLD)} Running Corsy (CORS checks)...")
    corsy_output = outdir / "Corsy"
    corsy_output.mkdir(parents=True, exist_ok=True)  # crée le dossier si nécessaire
    corsy_log = corsy_output / "corsy.txt"
    corsy_cmd = ["corsy", "-i", str(live_file)]
    code, out, err = await run_process(corsy_cmd, timeout=300, use_shell=False)
    if out and out.strip():
        corsy_log.write_text(out)
        append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} Corsy output -> {corsy_output}")
    if err:
        (corsy_output / "corsy.err").write_text(err)
        append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)}  Corsy stderr (preview): {err.splitlines()[0] if err else ''}")

    append_msg(messages, f"{color('[', BOLD)}{color('DONE', GREEN + BOLD)}{color(']', BOLD)} {color('R4D4R ... N0 M0R3 S1GN4L ...',BLUE + BOLD)}")
    return

# ---------------------------
# ---------- MAIN -----------
# ---------------------------
async def main():
    args = m4in()
    if args.outdir == "/data/r4d4r_result":
        outdir = Path("r4d4r_result")
    else:
        outdir = Path(args.outdir)
    messages = []
    stop_event = asyncio.Event()

    # start UI
    ui_task = asyncio.create_task(ui_loop(messages, stop_event, radius=RADAR_RADIUS))

    # run pipeline
    try:
        await r4d4r_pipeline(args.target, outdir, args.timeout, messages)
    except KeyboardInterrupt:
        append_msg(messages, "Interrupted by user.")
    except Exception as e:
        append_msg(messages,  f"{color('[', BOLD)}{color('WARN', RED + BOLD)}{color(']', BOLD)}  R4D4R exception: {e}")
    finally:
        # stop UI and wait for it to finish cleanly
        stop_event.set()
        await asyncio.sleep(0)  # yield
        ui_task.cancel()
        try:
            await ui_task
        except asyncio.CancelledError:
            pass
        # final message display
        sys.stdout.write("\033[H\033[2J")
        for m in messages[-CONSOLE_HEIGHT:]:
            print(m)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
