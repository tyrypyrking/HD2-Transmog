#!/usr/bin/env python3
"""Bounded, observed desktop automation for the Helldivers 2 test session.

No game memory is read. Every input requires matching compositor + X11 focus.
Mutating commands are dry-run unless --execute is passed. Observations and
proposed/executed actions are appended to an artifact directory as JSONL.
"""
from __future__ import annotations

import argparse
import csv
import fcntl
import ctypes as C
import ctypes.util
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
STATES = ("startup", "menu", "ship", "armory", "equipment", "unknown")
SAFE_KEYS = {"Return", "space", "Escape", "Tab", "Up", "Down", "Left", "Right", "BackSpace", *list("wasdeqzcfr1234567890")}
MAX_HOLD = 3.0


class AutomationError(RuntimeError):
    pass


def run(args, timeout=15):
    try:
        p = subprocess.run([str(x) for x in args], capture_output=True, text=True,
                           timeout=timeout, check=True)
        return p.stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as exc:
        raise AutomationError(f"Command failed: {args[0]}: {getattr(exc, 'stderr', '') or exc}") from exc


def normalize(text):
    return re.sub(r"\s+", " ", text.upper()).strip()


def classify(text, words=None, width=None, height=None):
    """Conservative EN/RU label classifier; unknown is an ordinary stop state."""
    text = normalize(text)
    has = lambda *xs: any(x in text for x in xs)
    evidence = []
    grid_text = text
    if words is not None and width and height:
        grid_text = normalize(" ".join(w["text"] for w in words
            if .04 <= (w["left"]+w["width"]/2)/width <= .45
            and .15 <= (w["top"]+w["height"]/2)/height <= .27))
    grid_has = lambda *labels: any(label in grid_text for label in labels)
    if has("ARMORY", "АРСЕНАЛ") or re.search(r"(?<!\w)APCEHAN(?!\w)", text):
        evidence.append("armory_heading")
    stat_groups = (("ARMOR RATING", "РЕЙТИНГ БРОНИ"), ("SPEED", "СКОРОСТЬ"),
                   ("STAMINA", "ВЫНОСЛИВОСТ"), ("PASSIVE", "ПАССИВНЫ"))
    stats = sum(has(*x) for x in stat_groups)
    if evidence and stats >= 2 and has("APPLY", "ПРИМЕНИТЬ", "COMPARE", "СРАВНИТЬ"):
        if grid_has("HELMETS", "ШЛЕМЫ"):
            view = "helmet_grid"
        elif grid_has("CAPES", "ПЛАЩИ"):
            view = "cape_grid"
        elif grid_has("CUSTOM VARIANT", "LIGHT", "MEDIUM", "HEAVY", "ЛЕГКАЯ", "ЛЁГКАЯ", "СРЕДНЯЯ", "ТЯЖЕЛАЯ"):
            view = "armor_grid"
        else:
            view = "unclassified_grid"
        return {"state": "equipment", "view": view, "evidence": evidence + [f"stat_labels:{stats}", "equipment_controls"]}
    native_tabs = sum(has(*group) for group in (("CHARACTER", "ПЕРСОНАЖ"), ("BOOSTER", "УСИЛИТЕЛЬ"), ("CAREER", "КАРЬЕРА")))
    weapon_cards = sum(has(*group) for group in (("PRIMARY", "ОСНОВНОЕ ОРУЖИЕ"), ("SECONDARY", "ДОПОЛНИТЕЛЬНОЕ"), ("GRENADE", "THROWABLE", "МЕТАТЕЛЬНОЕ")))
    armor_cards = sum(has(*group) for group in (("ARMOR", "БРОНЯ"), ("HELMET", "ШЛЕМ"), ("CAPE", "ПЛАЩ")))
    if evidence and (native_tabs >= 2 or (native_tabs >= 1 and armor_cards == 3)) and has("SELECT", "ВЫБРАТЬ", "CLOSE", "ЗАКРЫТЬ"):
        if weapon_cards >= 2:
            return {"state": "armory", "view": "weapons_cards", "evidence": evidence + ["native_root_tabs", "weapon_cards"]}
        if armor_cards >= 2:
            return {"state": "armory", "view": "armor_cards", "evidence": evidence + ["native_root_tabs", "armor_cards"]}
    if evidence and has("EQUIPMENT", "СНАРЯЖЕНИЕ") and has("WEAPON", "ОРУЖИЕ", "CHARACTER", "ПЕРСОНАЖ"):
        return {"state": "armory", "evidence": evidence + ["equipment_and_other_category"]}
    if has("PRESS ANY", "PRESS SPACE", "НАЖМИТЕ ЛЮБУЮ", "НАЖМИТЕ ПРОБЕЛ") and has("HELLDIVERS", "ПРОДОЛЖ", "CONTINUE", "НАЧАТЬ"):
        return {"state": "startup", "evidence": ["explicit_start_prompt"]}
    if has("CONTINUE", "ПРОДОЛЖИТЬ", "RESUME", "ВЕРНУТЬСЯ В ИГРУ") and has("OPTIONS", "НАСТРОЙКИ", "QUIT", "ВЫЙТИ", "EXIT"):
        return {"state": "menu", "evidence": ["continue_and_menu_controls"]}
    # Ship HUD requires two independent anchors; an armory interaction alone is
    # not enough because it also appears in menus. Never treat loading as ship.
    acquisitions_hud = has("ACQUISITIONS", "ПРИОБРЕТ") and has("SOCIAL", "ОБЩЕНИЕ", "СОЦИАЛЬ", "СОЦСЕТИ", "SUPER DESTROYER", "СУПЕРЭССМИНЕЦ", "DISPATCHES", "СВОДКИ")
    commander_hud = has("COMMANDER", "КОМАНДИР") and has("LEVEL", "УРОВЕНЬ") \
        and has("ORDERS", "ПРИКАЗЫ") and has("SOCIAL", "СОЦСЕТИ")
    if acquisitions_hud or commander_hud:
        return {"state": "ship", "evidence": ["ship_hud_anchors" if acquisitions_hud else "commander_level_orders_social"]}
    return {"state": "unknown", "evidence": evidence + ([f"stat_labels:{stats}"] if stats else [])}


def game_identity(title, app_id=""):
    if app_id:
        return app_id.lower() == "steam_app_553850"
    return bool(re.fullmatch(r"HELLDIVERS[™®]?\s*2", title.strip(), re.I))


def game_window_candidate(window):
    """Exclude launcher/GameGuard splashes before focus or startup input."""
    title = window.get("title", "")
    if not isinstance(title, str):
        return False
    size = window.get("layout", {}).get("window_size", [])
    if not isinstance(size, (list, tuple)) or len(size) != 2:
        return False
    if any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in size):
        return False
    # The actual game consistently publishes this title. App ID alone is also
    # shared by GameGuard and Wine helpers, including the live 320×200 splash.
    return size[0] >= 640 and size[1] >= 480 and game_identity(title) \
        and game_identity(title, window.get("app_id", ""))


class Journal:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.mkdir(parents=True, exist_ok=True)

    def write(self, event, **data):
        row = {"time": time.time(), "event": event, **data}
        with (self.path / "journal.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


class X11:
    """Small ctypes Xlib/XTest adapter, also works when xdotool is absent."""
    def __init__(self):
        if not os.environ.get("DISPLAY"):
            raise AutomationError("DISPLAY is absent; no X11 input backend")
        try:
            self.x = C.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
            self.t = C.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
        except OSError as exc:
            raise AutomationError(f"X11/XTest unavailable: {exc}") from exc
        signatures = {
            "XOpenDisplay": ([C.c_char_p], C.c_void_p),
            "XDefaultRootWindow": ([C.c_void_p], C.c_ulong),
            "XGetInputFocus": ([C.c_void_p, C.POINTER(C.c_ulong), C.POINTER(C.c_int)], C.c_int),
            "XQueryTree": ([C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_ulong), C.POINTER(C.POINTER(C.c_ulong)), C.POINTER(C.c_uint)], C.c_int),
            "XFetchName": ([C.c_void_p, C.c_ulong, C.POINTER(C.c_void_p)], C.c_int),
            "XGetGeometry": ([C.c_void_p, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint), C.POINTER(C.c_uint)], C.c_int),
            "XTranslateCoordinates": ([C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int, C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_ulong)], C.c_int),
            "XStringToKeysym": ([C.c_char_p], C.c_ulong),
            "XKeysymToKeycode": ([C.c_void_p, C.c_ulong], C.c_uint),
            "XFlush": ([C.c_void_p], C.c_int),
            "XRaiseWindow": ([C.c_void_p, C.c_ulong], C.c_int),
            "XSync": ([C.c_void_p, C.c_int], C.c_int),
            "XWarpPointer": ([C.c_void_p, C.c_ulong, C.c_ulong, C.c_int, C.c_int, C.c_uint, C.c_uint, C.c_int, C.c_int], C.c_int),
            "XFree": ([C.c_void_p], C.c_int),
            "XInternAtom": ([C.c_void_p, C.c_char_p, C.c_int], C.c_ulong),
            "XGetWindowProperty": ([C.c_void_p, C.c_ulong, C.c_ulong, C.c_long, C.c_long, C.c_int, C.c_ulong, C.POINTER(C.c_ulong), C.POINTER(C.c_int), C.POINTER(C.c_ulong), C.POINTER(C.c_ulong), C.POINTER(C.c_void_p)], C.c_int),
        }
        for name, (args, ret) in signatures.items():
            fn = getattr(self.x, name)
            fn.argtypes, fn.restype = args, ret
        # Stale windows from startup/teardown are rejected instead of aborting Python.
        self.error_handler = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p)(lambda *_: 0)
        self.x.XSetErrorHandler.argtypes = [C.c_void_p]
        self.x.XSetErrorHandler(self.error_handler)
        self.display = self.x.XOpenDisplay(None)
        if not self.display:
            raise AutomationError("Cannot connect to DISPLAY")
        self.root = self.x.XDefaultRootWindow(self.display)
        for name, args in {
            "XTestFakeKeyEvent": [C.c_void_p, C.c_uint, C.c_int, C.c_ulong],
            "XTestFakeButtonEvent": [C.c_void_p, C.c_uint, C.c_int, C.c_ulong],
            "XTestFakeMotionEvent": [C.c_void_p, C.c_int, C.c_int, C.c_int, C.c_ulong],
            "XTestFakeRelativeMotionEvent": [C.c_void_p, C.c_int, C.c_int, C.c_ulong],
        }.items():
            fn = getattr(self.t, name)
            fn.argtypes, fn.restype = args, C.c_int
        self.t.XTestQueryExtension.argtypes = [C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int), C.POINTER(C.c_int)]
        a, b, c, d = C.c_int(), C.c_int(), C.c_int(), C.c_int()
        if not self.t.XTestQueryExtension(self.display, C.byref(a), C.byref(b), C.byref(c), C.byref(d)):
            raise AutomationError("XTest extension not available on DISPLAY")

    def tree(self, wid):
        root, parent, children, count = C.c_ulong(), C.c_ulong(), C.POINTER(C.c_ulong)(), C.c_uint()
        ok = self.x.XQueryTree(self.display, wid, C.byref(root), C.byref(parent), C.byref(children), C.byref(count))
        result = [children[i] for i in range(count.value)] if ok else []
        if children:
            self.x.XFree(children)
        return parent.value, result

    def property(self, wid, name):
        actual, fmt, count, left, data = C.c_ulong(), C.c_int(), C.c_ulong(), C.c_ulong(), C.c_void_p()
        atom = self.x.XInternAtom(self.display, name.encode(), 1)
        if not atom:
            return None
        status = self.x.XGetWindowProperty(self.display, wid, atom, 0, 1024, 0, 0,
                  C.byref(actual), C.byref(fmt), C.byref(count), C.byref(left), C.byref(data))
        try:
            if status or not data.value:
                return None
            if fmt.value == 8:
                return C.string_at(data, count.value).decode("utf-8", "replace").replace("\x00", " ").strip()
            if fmt.value == 32 and count.value:
                return C.cast(data, C.POINTER(C.c_ulong))[0]
            return None
        finally:
            if data.value:
                self.x.XFree(data)

    def title(self, wid):
        name = self.property(wid, "_NET_WM_NAME")
        if name:
            return name
        data = C.c_void_p()
        self.x.XFetchName(self.display, wid, C.byref(data))
        try:
            return C.string_at(data).decode("utf-8", "replace") if data.value else ""
        finally:
            if data.value:
                self.x.XFree(data)

    def windows(self):
        queue = list(self.tree(self.root)[1])
        result = []
        seen = set()
        while queue and len(seen) < 2048:
            wid = queue.pop(0)
            if wid in seen:
                continue
            seen.add(wid)
            title = self.title(wid)
            cls = self.property(wid, "WM_CLASS") or ""
            if game_identity(title) or "steam_app_553850" in cls.lower().split():
                result.append({"id": wid, "title": title, "class": cls, "pid": self.property(wid, "_NET_WM_PID")})
            queue.extend(self.tree(wid)[1])
        return result

    def focused(self, expected):
        wid, revert = C.c_ulong(), C.c_int()
        self.x.XGetInputFocus(self.display, C.byref(wid), C.byref(revert))
        for _ in range(16):
            if wid.value == expected:
                return True
            if wid.value in (0, 1, self.root):
                break
            wid.value = self.tree(wid.value)[0]
        return False

    def geometry(self, wid):
        root, child = C.c_ulong(), C.c_ulong()
        x, y, out_x, out_y = C.c_int(), C.c_int(), C.c_int(), C.c_int()
        w, h, border, depth = C.c_uint(), C.c_uint(), C.c_uint(), C.c_uint()
        if not self.x.XGetGeometry(self.display, wid, C.byref(root), C.byref(x), C.byref(y), C.byref(w), C.byref(h), C.byref(border), C.byref(depth)):
            raise AutomationError("Game X window vanished")
        if not self.x.XTranslateCoordinates(self.display, wid, self.root, 0, 0, C.byref(out_x), C.byref(out_y), C.byref(child)):
            raise AutomationError("Cannot map game window coordinates")
        return (out_x.value, out_y.value, w.value, h.value)

    def key_event(self, key, down):
        sym = self.x.XStringToKeysym(key.encode("ascii"))
        code = self.x.XKeysymToKeycode(self.display, sym)
        if not code:
            raise AutomationError(f"No X keycode for {key}")
        if not self.t.XTestFakeKeyEvent(self.display, code, int(down), 0):
            raise AutomationError("XTest key event failed")
        self.x.XFlush(self.display)

    def move(self, x, y):
        if not self.t.XTestFakeMotionEvent(self.display, -1, int(x), int(y), 0):
            raise AutomationError("XTest pointer movement failed")
        self.x.XFlush(self.display)

    def raise_window(self, window):
        if not self.focused(window):
            raise AutomationError("Game X11 focus changed before stacking alignment")
        self.x.XRaiseWindow(self.display, window)
        self.x.XSync(self.display, 0)

    def move_to_window(self, window, x, y):
        # Rootless XWayland windows may share virtual root coordinates while
        # niri places them on different surfaces. Warp to the target client;
        # root-absolute XTest motion can focus an unrelated desktop window.
        if not self.focused(window):
            raise AutomationError("Game X11 focus changed before pointer targeting")
        self.x.XWarpPointer(self.display, 0, window, 0, 0, 0, 0, int(x), int(y))
        self.x.XSync(self.display, 0)

    def relative(self, dx, dy):
        if not self.t.XTestFakeRelativeMotionEvent(self.display, int(dx), int(dy), 0):
            raise AutomationError("XTest relative movement failed")
        self.x.XFlush(self.display)

    def button(self, number, down):
        if not self.t.XTestFakeButtonEvent(self.display, number, int(down), 0):
            raise AutomationError("XTest button event failed")
        self.x.XFlush(self.display)


def ocr_words(path, tessdata=None, languages="rus+eng", psm=11):
    args = ["tesseract", str(path), "stdout", "-l", languages, "--psm", str(psm)]
    if tessdata:
        args.extend(["--tessdata-dir", str(tessdata)])
    args.extend(["-c", "tessedit_create_tsv=1"])
    raw = run(args, timeout=30)
    words = []
    # Tesseract emits unescaped quote characters in TSV cells. CSV quoting
    # would consume following rows as a multiline OCR word.
    for row in csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
        txt = (row.get("text") or "").strip()
        if not txt or row.get("level") != "5":
            continue
        try:
            word = {"text": txt, "confidence": float(row["conf"]),
                    "left": int(row["left"]), "top": int(row["top"]),
                    "width": int(row["width"]), "height": int(row["height"])}
        except (TypeError, ValueError, KeyError):
            continue
        if word["width"] > 0 and word["height"] > 0:
            words.append(word)
    return words


def read_ocr(path, tessdata=None, languages="rus+eng"):
    words = ocr_words(path, tessdata, languages)
    # Full-scene sparse OCR often interprets ship scenery as letters and misses
    # the small HUD. Read those two native HUD strips independently. Normalized
    # crop coordinates adapt to resolution; unsupported layouts remain unknown.
    if Path(path).is_file():
        from PIL import Image, ImageOps
        with Image.open(path) as im, tempfile.TemporaryDirectory(prefix="hd2-ocr-") as temp:
            regions = [((.42, .022, .57, .059), 6, languages),
                       ((.77, .014, .988, .06), 6, languages),
                       ((.06, .025, .18, .085), 7, "rus" if "rus" in languages.split("+") else languages),
                       ((.065, .083, .594, .116), 6, "rus" if "rus" in languages.split("+") else languages),
                       ((.18, .17, .82, .223), 6, "rus" if "rus" in languages.split("+") else languages),
                       ((.027, .95, .99, .99), 6, "rus" if "rus" in languages.split("+") else languages)]
            for index, (box, psm, crop_languages) in enumerate(regions):
                pixels = tuple(round(a*b) for a,b in zip(box, (im.width, im.height, im.width, im.height)))
                crop = im.crop(pixels)
                crop = ImageOps.autocontrast(ImageOps.grayscale(crop).resize((crop.width*2, crop.height*2)))
                crop_path = Path(temp) / f"hud-{index}.png"
                crop.save(crop_path)
                extra = ocr_words(crop_path, tessdata, crop_languages, psm=psm)
                for word in extra:
                    word["left"] = pixels[0] + round(word["left"]/2)
                    word["top"] = pixels[1] + round(word["top"]/2)
                    word["width"] = round(word["width"]/2)
                    word["height"] = round(word["height"]/2)
                    if not any(normalize(w["text"]) == normalize(word["text"]) and abs(w["left"]-word["left"]) < 15 and abs(w["top"]-word["top"]) < 15 for w in words):
                        words.append(word)
    return " ".join(w["text"] for w in words), words


def text_target(words, text, width, height):
    """Match a unique OCR word/phrase and return its normalized center."""
    wanted = normalize(text).split()
    candidates = []
    for i in range(len(words) - len(wanted) + 1):
        part = words[i:i + len(wanted)]
        clean = [normalize(w["text"]).strip("[]():,.|") for w in part]
        if clean != wanted or min(w["confidence"] for w in part) < 40:
            continue
        # Multi-word phrases must share a text line, avoiding unrelated matches.
        if max(w["top"] for w in part) - min(w["top"] for w in part) > max(w["height"] for w in part):
            continue
        x1, y1 = min(w["left"] for w in part), min(w["top"] for w in part)
        x2, y2 = max(w["left"] + w["width"] for w in part), max(w["top"] + w["height"] for w in part)
        candidates.append(((x1+x2)/2/width, (y1+y2)/2/height))
    if len(candidates) != 1:
        raise AutomationError(f"OCR target {text!r} has {len(candidates)} confident matches, expected one")
    return candidates[0]


def armor_card_target(words, width, height):
    """Select the native Armor card from its large visible title, not a fixed tile."""
    candidates = []
    for word in words:
        title = normalize(word["text"]).strip("[]():,.|")
        center_x = (word["left"]+word["width"]/2)/width
        center_y = (word["top"]+word["height"]/2)/height
        if title in ("ARMOR", "ARMOUR", "БРОНЯ") and word["confidence"] >= 60 \
                and .15 <= center_x <= .45 and .14 <= center_y <= .31 \
                and .012 <= word["height"]/height <= .065:
            # Native cards begin immediately below these large category titles.
            # Six title heights below the baseline lands inside the visible
            # left card, including when its width changes with selection.
            click_y = (word["top"]+7*word["height"])/height
            if .25 <= click_y <= .70:
                candidates.append((center_x, click_y))
    if len(candidates) != 1:
        raise AutomationError(f"Expected one visible native Armor card title, found {len(candidates)}")
    return candidates[0]


def armory_prompt(words, width, height):
    stations = [w for w in words if normalize(w["text"]).strip("[]():,.|") in ("ARMORY", "АРСЕНАЛ") and w["confidence"] >= 40]
    keys = [w for w in words if normalize(w["text"]).strip("[]():,.|") in ("E", "Е") and w["confidence"] >= 40]
    return any(abs(station["left"]-key["left"]) < width*.1 and abs(station["top"]-key["top"]) < height*.08 for station in stations for key in keys)


def window_fit(window, outputs, workspaces):
    """Assess single-output logical bounds without changing the desktop."""
    active = [(name, output["logical"]) for name, output in outputs.items()
              if output.get("logical") and output.get("current_mode") is not None]
    result = {"window_id": window["id"], "fits": None}
    if len(active) != 1:
        return {**result, "reason": "single_active_output_required"}
    name, output = active[0]
    # This desktop's scale-1, normal-transform geometry is verified. Avoid
    # guessing pixel/logical transforms on other setups during an automatic toggle.
    if output.get("scale", 1) != 1 or output.get("transform", "Normal") != "Normal":
        return {**result, "reason": "output_transform_not_verified"}
    workspace = [w for w in workspaces if w.get("id") == window.get("workspace_id")
                 and w.get("is_active") and w.get("output") == name]
    if len(workspace) != 1:
        return {**result, "reason": "game_output_not_unambiguous"}
    layout = window.get("layout", {})
    pos, offset, size = (layout.get(key) for key in
                         ("tile_pos_in_workspace_view", "window_offset_in_tile", "window_size"))
    if any(not isinstance(v, (list, tuple)) or len(v) != 2 for v in (pos, offset, size)):
        return {**result, "reason": "window_bounds_unavailable"}
    dimensions = [*pos, *offset, *size, output.get("width"), output.get("height")]
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in dimensions):
        return {**result, "reason": "window_bounds_invalid"}
    x, y = pos[0]+offset[0], pos[1]+offset[1]
    width, height = size
    if min(width, height, output["width"], output["height"]) <= 0:
        return {**result, "reason": "window_bounds_invalid"}
    fits = x >= 0 and y >= 0 and x+width <= output["width"] and y+height <= output["height"]
    return {**result, "fits": fits, "output": name, "bounds": [x, y, width, height],
            "output_size": [output["width"], output["height"]], "reason": "fits" if fits else "clipped"}


class Session:
    def __init__(self, args):
        self.args = args
        self.journal = Journal(args.artifacts)
        self.x11 = None
        self.bound_window = None

    def windows(self):
        if not shutil.which("niri") or not os.environ.get("NIRI_SOCKET"):
            raise AutomationError("This build requires niri compositor focus/geometry; unsupported desktops fail closed")
        return json.loads(run(["niri", "msg", "-j", "windows"]))

    def game(self):
        found = [w for w in self.windows() if game_window_candidate(w)]
        if self.args.window_id is not None:
            found = [w for w in found if w["id"] == self.args.window_id]
        if len(found) != 1:
            raise AutomationError(f"Expected one game window, found {len(found)}; inspect windows, or supply --window-id")
        window = found[0]
        if self.bound_window is None:
            self.bound_window = window["id"]
        if self.bound_window != window["id"]:
            raise AutomationError("Game window changed; begin a new session")
        return window

    def assert_focus(self):
        window = self.game()
        if not window.get("is_focused"):
            raise AutomationError("Game does not have compositor focus")
        if json.loads(run(["niri", "msg", "-j", "overview-state"])).get("is_open"):
            raise AutomationError("Compositor overview is open")
        return window

    def focus(self):
        window = self.game()
        self.journal.write("focus", execute=self.args.execute, window_id=window["id"])
        if self.args.execute:
            run(["niri", "msg", "action", "focus-window", "--id", window["id"]])
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                if self.game().get("is_focused"):
                    time.sleep(.3)
                    return self.assert_focus()
                time.sleep(.1)
            raise AutomationError("Compositor did not focus game within 3 seconds")
        return window

    def window_fit_snapshot(self):
        window = self.assert_focus()
        outputs = json.loads(run(["niri", "msg", "-j", "outputs"]))
        workspaces = json.loads(run(["niri", "msg", "-j", "workspaces"]))
        return window_fit(window, outputs, workspaces)

    def fit_game_window(self):
        """One guarded fullscreen toggle only for a proven clipped game window."""
        if not self.args.execute:
            return self.journal.write("window_fit_plan", dry_run=True, changed=False,
                policy="Fullscreen once only if focused game is clipped on one verified output")
        before = self.window_fit_snapshot()
        if before["fits"] is not False:
            return self.journal.write("window_fit", changed=False, **before)
        # Revalidate immediately before a toggle so an intervening manual window
        # adjustment cannot turn an already-fitting fullscreen game back off.
        confirm = self.window_fit_snapshot()
        if confirm["window_id"] != before["window_id"]:
            raise AutomationError("Game window changed before fitting; no fullscreen toggle sent")
        if confirm["fits"] is not False:
            return self.journal.write("window_fit", changed=False, **confirm)
        self.journal.write("window_fit_requested", changed=True, action="fullscreen_once", **confirm)
        run(["niri", "msg", "action", "fullscreen-window", "--id", confirm["window_id"]])
        deadline = time.monotonic()+3
        while True:
            after = self.window_fit_snapshot()
            if after["window_id"] != confirm["window_id"]:
                raise AutomationError("Game window changed during fullscreen fitting")
            if after["fits"] is True:
                return self.journal.write("window_fit", changed=True, before=confirm["bounds"], **after)
            if after["fits"] is None:
                raise AutomationError("Cannot verify output/window bounds after fullscreen; no second toggle sent")
            if time.monotonic() >= deadline:
                raise AutomationError("Game remained clipped after 3-second fullscreen wait; no second toggle sent")
            time.sleep(min(.1, max(0, deadline-time.monotonic())))

    def input_window(self):
        self.assert_focus()
        if self.x11 is None:
            self.x11 = X11()
        found = self.x11.windows()
        focused = [w for w in found if game_identity(w.get("title", "")) and self.x11.focused(w["id"])]
        if len(focused) != 1:
            raise AutomationError(f"Expected one focused game X11 window, found {len(focused)}")
        return focused[0]

    def screenshot(self):
        from PIL import Image
        w = self.assert_focus()
        # XWayland's game window can extend a few pixels off the output in
        # borderless mode. Targeted X capture gets the entire game, independent
        # of compositor decorations, output clipping, and monitor scaling.
        target = self.input_window()
        x, y, width, height = self.x11.geometry(target["id"])
        path = self.journal.path / f"screen-{time.time_ns()}.png"
        if not shutil.which("import"):
            raise AutomationError("ImageMagick import is required for full game-window capture")
        run(["import", "-window", hex(target["id"]), str(path)], timeout=20)
        self.assert_focus()
        with Image.open(path) as img:
            pixel_width, pixel_height = img.size
        return {"path": str(path), "width": pixel_width, "height": pixel_height,
                "window_id": w["id"], "geometry": [x, y, width, height],
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def observe(self):
        shot = self.screenshot()
        text, words = read_ocr(shot["path"], self.args.tessdata, self.args.languages)
        state = classify(text, words, shot["width"], shot["height"])
        observation = {**shot, **state, "text": text, "words": words}
        self.journal.write("observation", **observation)
        return observation

    def check_expected(self, observation, expected):
        if not expected or observation["state"] not in expected:
            raise AutomationError(f"Expected {expected}, observed {observation['state']}; no input sent")

    def observe_expected(self, expected, observation=None):
        observation = observation or self.observe()
        if expected and observation["state"] == "unknown" and "unknown" not in expected:
            self.journal.write("observation_retry", expected=expected, reason="unknown", maximum_observations=2)
            self.assert_focus()
            time.sleep(.15)
            observation = self.observe()
        self.check_expected(observation, expected)
        return observation

    def action(self, action, expected, observation=None):
        validate_action(action)
        observation = self.observe_expected(expected, observation)
        self.journal.write("action", execute=self.args.execute, action=action, expected=expected,
                           observed=observation["state"], screenshot=observation["path"])
        if not self.args.execute:
            return {"dry_run": True, "action": action, "observed": observation["state"]}
        target = self.input_window()
        xid = target["id"]
        # The focus is rechecked before down/move and throughout each hold. Always
        # release in finally, including Ctrl-C, timeout, and focus loss.
        if action["kind"] == "key":
            key, duration = action["key"], action.get("duration", .08)
            try:
                self.x11.key_event(key, True)
                self.wait_guarded(duration, xid)
            finally:
                self.x11.key_event(key, False)
        elif action["kind"] == "click":
            x, y, width, height = self.x11.geometry(xid)
            self.x11.raise_window(xid)
            self.wait_guarded(.1, xid)
            self.x11.move_to_window(xid, round(action["x"] * (width-1)), round(action["y"] * (height-1)))
            self.wait_guarded(.25, xid)
            try:
                self.x11.button(1, True)
                self.wait_guarded(.05, xid)
            finally:
                self.x11.button(1, False)
        elif action["kind"] == "look":
            # Small relative increments produce usable camera turns under capture.
            steps = max(1, int(max(abs(action["dx"]), abs(action["dy"])) / 20) + 1)
            previous_x = previous_y = 0
            for i in range(1, steps + 1):
                px, py = round(action["dx"]*i/steps), round(action["dy"]*i/steps)
                self.x11.relative(px-previous_x, py-previous_y)
                previous_x, previous_y = px, py
                self.wait_guarded(.015, xid)
        elif action["kind"] == "wait":
            self.wait_guarded(action["duration"], xid)
        time.sleep(action.get("settle", .5))
        after = self.observe()
        return {"action": action, "after": after}

    def wait_guarded(self, seconds, xid):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.assert_focus()
            if not self.x11.focused(xid):
                raise AutomationError("X11 game focus lost during action; input released")
            time.sleep(min(.05, max(0, deadline-time.monotonic())))

    def click_text(self, label, expected, observation=None):
        observation = self.observe_expected(expected, observation)
        x, y = text_target(observation["words"], label, observation["width"], observation["height"])
        return self.action({"kind": "click", "x": x, "y": y, "label": label}, expected, observation)

    def route(self, path):
        route = json.loads(Path(path).read_text())
        validate_route(route)
        if not self.args.execute:
            return self.journal.write("route_plan", execute=False, route=route)
        self.focus()
        observation = self.observe()
        self.check_expected(observation, route["start"])
        for step in route["steps"]:
            if "text" in step:
                result = self.click_text(step["text"], step["expect"], observation)
            else:
                result = self.action(step["action"], step["expect"], observation)
            observation = result["after"]
            self.check_expected(observation, step["after"])
        self.check_expected(observation, route["target"])
        return {"route_complete": True, "observation": observation}

    def wait_for(self, states, timeout=30, initial=None, guard=None):
        """Wait through unreadable/loading frames without sending any input."""
        if not 0 <= timeout <= 300:
            raise AutomationError("Observation wait must be 0–300 seconds")
        deadline = time.monotonic() + timeout
        observation = initial
        attempts = 0
        while True:
            if guard:
                guard()
            observation = observation or self.observe()
            attempts += 1
            if observation["state"] in states:
                return {"reached": observation["state"], "observation": observation}
            if time.monotonic() >= deadline:
                raise AutomationError(f"Timed out waiting for {states}; last view is {observation['state']}; no input sent while waiting")
            self.journal.write("waiting", target=states, observed=observation["state"], attempt=attempts)
            time.sleep(min(1, max(0, deadline-time.monotonic())))
            observation = None

    def wait_startup_view(self, timeout, observation, clicks_allowed=False):
        """Only the first startup phase may use user-authorized movie clicks."""
        recognized = [state for state in STATES if state != "unknown"]
        if not clicks_allowed:
            return self.wait_for(recognized, timeout, observation)["observation"]
        deadline = time.monotonic()+timeout
        bursts = clicks = 0
        next_burst = time.monotonic()
        interval = min(20, max(2, timeout/8))
        while observation["state"] == "unknown":
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise AutomationError("Timed out during authorized startup movie skipping; click budget was bounded")
            self.assert_focus()
            if bursts < 8 and time.monotonic() >= next_burst:
                bursts += 1
                self.journal.write("startup_click_burst", burst=bursts, maximum_bursts=8,
                                   maximum_clicks=24, startup_only=True)
                for _ in range(3):
                    if observation["state"] != "unknown" or time.monotonic() >= deadline:
                        break
                    result = self.action({"kind":"click", "x":.5, "y":.5, "settle":.1,
                                          "label":"authorized startup movie skip"}, ["unknown"], observation)
                    clicks += 1
                    observation = result["after"]
                next_burst = time.monotonic()+interval
            else:
                time.sleep(min(1, remaining))
                observation = self.observe()
        self.journal.write("startup_clicks_finished", bursts=bursts, clicks=clicks,
                           recognized=observation["state"])
        return observation

    def equipment_view(self, observation, timeout=30, guard=None):
        """Native root: 2, actual left Armor-card click, then picker tab 1."""
        deadline = time.monotonic()+timeout
        def remaining():
            value = deadline-time.monotonic()
            if value <= 0:
                raise AutomationError("Native Armor navigation timed out; no input repeated")
            return min(60, value)
        def wait_until(predicate, view):
            while not predicate(view):
                remaining()
                if view["state"] != "unknown":
                    self.check_expected(view, ["armory", "equipment"])
                if guard:
                    guard()
                time.sleep(min(.25, remaining()))
                view = self.observe()
            return view
        def guarded_action(action, expected, view):
            remaining()
            if guard:
                guard()
            return self.action(action, expected, view)["after"]

        observation = wait_until(lambda view: view["state"] in ("armory", "equipment"), observation)
        if observation["state"] == "equipment" and observation.get("view") == "armor_grid":
            return observation
        if observation["state"] == "armory":
            observation = guarded_action({"kind":"key", "key":"2", "settle":.5}, ["armory"], observation)
            observation = wait_until(lambda view: view["state"] == "armory" and view.get("view") == "armor_cards", observation)
            x, y = armor_card_target(observation["words"], observation["width"], observation["height"])
            observation = guarded_action({"kind":"click", "x":x, "y":y, "label":"first left native Armor card"}, ["armory"], observation)
            observation = wait_until(lambda view: view["state"] == "equipment", observation)
        # Numeric tab selection is valid only once a picker is visibly open.
        # Always send 1 after the card click, even when its first frame is Armor.
        observation = guarded_action({"kind":"key", "key":"1", "settle":.5}, ["equipment"], observation)
        return wait_until(lambda view: view["state"] == "equipment" and view.get("view") == "armor_grid", observation)

    def armory(self, launch=False, timeout=60, state_dir=None, launch_timeout=240, startup_timeout=180, startup_clicks=False):
        """Reach and visually verify native Equipment, without walking inputs."""
        if not 0 < timeout <= 60:
            raise AutomationError("Armory workflow timeout must be greater than 0 and at most 60 seconds")
        if not 10 <= launch_timeout <= 300:
            raise AutomationError("Game-window launch timeout must be 10–300 seconds")
        if not 10 <= startup_timeout <= 300:
            raise AutomationError("Initial recognized-view timeout must be 10–300 seconds")
        if not self.args.execute:
            return self.journal.write("armory_plan", dry_run=True, execute=False, launch=launch,
                timeout=timeout, launch_timeout=launch_timeout, startup_timeout=startup_timeout, startup_clicks=startup_clicks, menu_verified=False,
                steps=["Find existing game or optionally launch once", "Focus game and wait for a recognized initial view", "Fit a clipped initialized game window once",
                       "Use bounded movie-click bursts only for a fresh launch or explicitly confirmed startup; stop at recognized UI",
                       "If needed, request native open_armory once from verified ship",
                       "Press 2 at native root, click first left Armor card, then press 1 in the picker and verify Armor"])
        deadline = time.monotonic() + launch_timeout
        stage = "window"
        self.journal.write("armory_stage", stage=stage, timeout=launch_timeout)
        launched = False
        requested = False
        acknowledgement = None
        addon_status = None
        open_guard = None

        def begin_stage(name, budget=None):
            nonlocal deadline, stage
            stage = name
            budget = timeout if budget is None else budget
            deadline = time.monotonic()+budget
            self.journal.write("armory_stage", stage=stage, timeout=budget)

        def remaining():
            seconds = deadline-time.monotonic()
            if seconds <= 0:
                raise AutomationError(f"Armory workflow time budget exhausted during {stage}; no request was replayed")
            return seconds

        def existing():
            return [w for w in self.windows() if game_window_candidate(w)]

        if not existing():
            if not launch:
                raise AutomationError("Game is not running; use armory --launch to launch it once")
            remaining()
            self.journal.write("launch", execute=True, url="steam://rungameid/553850", workflow="armory")
            run(["xdg-open", "steam://rungameid/553850"])
            launched = True
            while not existing():
                time.sleep(min(.5, remaining()))
        remaining()
        self.focus()
        fit = None
        begin_stage("initial_view", startup_timeout)
        observation = self.observe()
        recognized = [s for s in STATES if s != "unknown"]
        transitions = 0
        movie_clicks_allowed = launched or startup_clicks
        while True:
            state = observation["state"]
            if state == "unknown":
                observation = self.wait_startup_view(remaining(), observation, movie_clicks_allowed)
                movie_clicks_allowed = False
                continue
            movie_clicks_allowed = False
            if fit is None:
                # Cold launch creates a temporary viewport before its renderer
                # settles. Fit only after an actual title/menu/ship view exists.
                fit = self.fit_game_window()
                if fit.get("changed"):
                    observation = self.observe()
                    continue
            if state in ("ship", "armory", "equipment"):
                break
            if transitions >= 4:
                raise AutomationError("Armory startup/menu transition budget exhausted")
            transitions += 1
            if state == "startup":
                begin_stage("startup_to_ship")
                result = self.action({"kind": "key", "key": "space", "settle": 1}, ["startup"], observation)
            elif state == "menu":
                begin_stage("continue_to_ship")
                result = self.click_any(["CONTINUE", "ПРОДОЛЖИТЬ", "RESUME", "ВЕРНУТЬСЯ В ИГРУ"], observation)
            else:
                raise AutomationError(f"Unsupported Armory workflow view: {state}")
            observation = result["after"]
            if observation["state"] in (state, "unknown"):
                destinations = [s for s in recognized if s != state]
                observation = self.wait_for(destinations, remaining(), observation)["observation"]
        begin_stage("native_equipment")
        if observation["state"] == "ship":
            remaining()
            self.assert_focus()
            state_path = Path(state_dir).expanduser().resolve() if state_dir else discover_debug_dir()
            status_path = state_path / "debug-armory-open.txt"
            previous_status = file_identity(status_path)
            acknowledgement = debug_command("open_armory", state_dir=state_path, execute=True,
                timeout=min(10, remaining()), journal=self.journal, guard=self.assert_focus)
            requested = True

            def open_guard():
                nonlocal addon_status
                self.assert_focus()
                token = acknowledgement["session_token"]
                if debug_session(state_path) != token:
                    raise AutomationError("Game session changed before Armory confirmation; not replaying request")
                pending = parse_debug_request(bounded_read(state_path / "debug.request", 2048))
                if not pending or pending["token"] != token or pending["request_id"] != acknowledgement["request_id"]:
                    raise AutomationError("Debug request changed before Armory confirmation; not attributing another request")
                if file_identity(status_path) != previous_status:
                    addon_status = parse_armory_status(bounded_read(status_path, 4096), token)
                    if addon_status and addon_status["status"] == "error":
                        raise AutomationError(f"Native Armory opener failed: {addon_status['message']}")

            observation = self.wait_for(["armory", "equipment"], remaining(), guard=open_guard)["observation"]
        if observation["state"] in ("armory", "equipment"):
            observation = self.equipment_view(observation, remaining(), open_guard)
        if open_guard:
            open_guard()
            while not addon_status or addon_status["status"] != "ok":
                time.sleep(min(.25, remaining()))
                open_guard()
            # Confirm that the native view remained visible through handler completion.
            observation = self.observe()
        remaining()
        self.check_expected(observation, ["equipment"])
        if observation.get("view") != "armor_grid":
            raise AutomationError("Final native view is not the Armor grid; menu was not verified")
        self.assert_focus()
        result = {"reached": "equipment", "view": "armor_grid", "menu_verified": True, "launched": launched,
                  "open_requested": requested, "window_fit": fit, "observation": observation}
        if acknowledgement:
            result["acknowledgement"] = acknowledgement
            result["addon_open_status"] = addon_status
        self.journal.write("armory_verified", menu_verified=True, open_requested=requested,
                           launched=launched, screenshot=observation["path"])
        return result

    def navigate(self, target, max_steps, wait_seconds=30):
        self.focus()
        if not self.args.execute:
            return {"dry_run": True, "target": target,
                    "policy": "observe; explicit startup prompt -> space; menu -> Continue/Resume; nearby ship Armory prompt -> E; armory -> Equipment; bounded observation-only wait through loading"}
        loading_deadline = time.monotonic() + wait_seconds
        recognized = [state for state in STATES if state != "unknown"]
        for _ in range(max_steps):
            observation = self.observe()
            if observation["state"] == "unknown":
                remaining = max(0, loading_deadline-time.monotonic())
                observation = self.wait_for(recognized, remaining, observation)["observation"]
            state = observation["state"]
            if state == target:
                return {"reached": target, "observation": observation}
            if state == "startup":
                self.action({"kind": "key", "key": "space", "settle": 2}, [state], observation)
            elif state == "menu":
                self.click_any(["CONTINUE", "ПРОДОЛЖИТЬ", "RESUME", "ВЕРНУТЬСЯ В ИГРУ"], observation)
            elif state == "armory":
                self.equipment_view(observation, max(.01, loading_deadline-time.monotonic()))
            elif state == "ship":
                if not armory_prompt(observation["words"], observation["width"], observation["height"]):
                    raise AutomationError("No verified nearby Armory interaction prompt; use the debug Armory opener")
                self.action({"kind": "key", "key": "e", "settle": 1}, [state], observation)
            else:
                raise AutomationError(f"Cannot navigate from {state}; inspect the captured view")
        raise AutomationError("Navigation action budget exhausted")

    def click_any(self, labels, observation):
        for label in labels:
            try:
                x, y = text_target(observation["words"], label, observation["width"], observation["height"])
            except AutomationError:
                continue
            return self.action({"kind": "click", "x": x, "y": y, "label": label}, [observation["state"]], observation)
        raise AutomationError("No unique OCR navigation target found")


def validate_action(action):
    kind = action.get("kind")
    if kind == "key":
        if action.get("key") not in SAFE_KEYS:
            raise AutomationError("Key is not in the bounded game-navigation allowlist")
        if not 0.02 <= action.get("duration", .08) <= MAX_HOLD:
            raise AutomationError(f"Key duration must be .02–{MAX_HOLD} seconds")
    elif kind == "click":
        if not all(isinstance(action.get(k), (int, float)) and 0 <= action[k] <= 1 for k in ("x", "y")):
            raise AutomationError("Click coordinates must be normalized to [0, 1]")
    elif kind == "look":
        if not all(isinstance(action.get(k), int) and abs(action[k]) <= 600 for k in ("dx", "dy")):
            raise AutomationError("Look deltas must be integer pixels in [-600, 600]")
    elif kind == "wait":
        if not 0 <= action.get("duration", -1) <= 10:
            raise AutomationError("Wait must be 0–10 seconds")
    else:
        raise AutomationError(f"Unknown action kind: {kind}")
    if not 0 <= action.get("settle", .5) <= 10:
        raise AutomationError("Settle time must be 0–10 seconds")


def validate_route(route):
    if route.get("version") != 1:
        raise AutomationError("Unsupported route version")
    for key in ("start", "target"):
        if not route.get(key) or any(s not in STATES or s == "unknown" for s in route[key]):
            raise AutomationError(f"Route {key} requires recognized state(s)")
    steps = route.get("steps", [])
    if not 1 <= len(steps) <= 40:
        raise AutomationError("Route requires 1–40 bounded steps")
    duration = 0
    for step in steps:
        for field in ("expect", "after"):
            if not step.get(field) or any(s not in STATES or s == "unknown" for s in step[field]):
                raise AutomationError(f"Each route step requires recognized {field} state(s)")
        if "text" in step:
            if not isinstance(step["text"], str) or not step["text"].strip():
                raise AutomationError("Empty text target")
        else:
            validate_action(step.get("action", {}))
            duration += step["action"].get("duration", .1) + step["action"].get("settle", .5)
    if duration > 120:
        raise AutomationError("Route duration exceeds 120-second action budget")


DEBUG_COMMANDS = ("inspect_api", "probe_armory", "inspect_controller", "inspect_world",
                  "inspect_native_code", "inspect_native_callee", "inspect_native_switch", "inspect_armory_grid", "inspect_armory_model", "inspect_armory_producers", "inspect_render_types", "inspect_player_armor", "layout_trial", "probe_armor", "open_creator", "presentation_trial", "ui_status", "icon_probe",
                  "open_armory", "read_catalog", "variant_status", "draft_variant",
                  "save_variant", "select_variant", "apply_variant", "reset_variant")
DEBUG_SUBPATH = Path("steamapps/compatdata/553850/pfx/drive_c/users/steamuser/AppData/Local/CowboyBingus/Helldivers2/Transmog")


def file_identity(path):
    try:
        info = Path(path).stat()
        return info.st_ino, info.st_mtime_ns, info.st_size
    except FileNotFoundError:
        return None


def parse_armory_status(raw, token):
    if raw is None:
        return None
    match = re.fullmatch(r"HD2TM_ARMORY_OPEN 1\n([A-Za-z0-9-]+)\n(pending|ok|error)\n([^\r\n]*)\n", raw)
    if not match:
        raise AutomationError("Unrecognized native Armory status format")
    if match.group(1) != token:
        raise AutomationError("Native Armory status belongs to another game session")
    return {"session_token": token, "status": match.group(2), "message": match.group(3)}


def discover_debug_dir():
    """Resolve known Steam libraries, never guess among multiple installations."""
    home = Path.home()
    roots = [home / "Steam Library/SteamLibrary", home / ".local/share/Steam", home / ".steam/steam"]
    for root in tuple(roots):
        config = root / "steamapps/libraryfolders.vdf"
        if config.is_file():
            for value in re.findall(r'"path"\s+"([^"]+)"', config.read_text(encoding="utf-8", errors="replace")):
                roots.append(Path(value.replace("\\\\", "\\")))
    directories = sorted({(root / DEBUG_SUBPATH).resolve() for root in roots if (root / DEBUG_SUBPATH).is_dir()})
    enabled = [path for path in directories if (path / "debug.session").is_file() and (path / "debug.enabled").is_file()]
    choices = enabled or directories
    if len(choices) != 1:
        raise AutomationError(f"Found {len(choices)} possible debug directories; provide --state-dir")
    return choices[0]


def bounded_read(path, maximum):
    try:
        with Path(path).open("rb") as f:
            raw = f.read(maximum+1)
    except FileNotFoundError:
        return None
    if len(raw) > maximum:
        raise AutomationError(f"{Path(path).name} exceeds its protocol size limit")
    return raw.decode("utf-8", errors="replace")


def debug_session(state_dir):
    if bounded_read(state_dir / "debug.enabled", 64) != "HD2TM_DEBUG 1\n":
        raise AutomationError("Debug bridge is disabled; debug.enabled marker is absent or invalid")
    raw = bounded_read(state_dir / "debug.session", 512)
    match = re.fullmatch(r"HD2TM_DEBUG_SESSION 1\n([A-Za-z0-9-]{1,128})\n", raw or "")
    if not match:
        raise AutomationError("No valid live debug.session token; launch the debug-enabled addon first")
    return match.group(1)


def parse_debug_response(raw, token, request_id):
    if not raw:
        return None
    fields = raw.split("\n", 5)
    if len(fields) != 6 or fields[0] != "HD2TM_DEBUG_RESPONSE 1":
        return None
    if fields[1] != token or fields[2] != request_id:
        return None
    if fields[3] not in ("ok", "error") or fields[5] != "":
        raise AutomationError("Matching debug response has an invalid status or record shape")
    return {"request_id": request_id, "status": fields[3], "message": fields[4]}


def parse_debug_request(raw):
    match = re.fullmatch(r"HD2TM_DEBUG_REQUEST 1\n([A-Za-z0-9-]+)\n([A-Za-z0-9-]{1,80})\n([a-z_]+)\n([\s\S]*)", raw or "")
    if not match:
        return None
    return {"token": match.group(1), "request_id": match.group(2), "command": match.group(3), "payload": match.group(4)}


def write_debug_request(state_dir, text, previous):
    """Flush a same-directory temporary, then publish one complete request."""
    target = state_dir / "debug.request"
    if bounded_read(target, 2048) != previous:
        raise AutomationError("Debug inbox changed concurrently; no request was replaced")
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=".debug.request-", dir=state_dir, delete=False) as f:
            temp_path = Path(f.name)
            f.write(text.encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        # Recheck immediately before the atomic replacement. Other instances of
        # this CLI also hold debug.transport.lock across send/ack completion.
        if bounded_read(target, 2048) != previous:
            raise AutomationError("Debug inbox changed concurrently; no request was replaced")
        os.replace(temp_path, target)
        temp_path = None
        directory_fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def debug_command(command, payload="", state_dir=None, execute=False, timeout=10, journal=None, guard=None):
    if command not in DEBUG_COMMANDS:
        raise AutomationError("Debug command is not allowlisted")
    if not isinstance(payload, str) or "\x00" in payload or len(payload.encode("utf-8")) > 1024:
        raise AutomationError("Debug payload must be NUL-free text of at most 1024 UTF-8 bytes")
    if not 0 < timeout <= 60:
        raise AutomationError("Debug acknowledgement timeout must be greater than 0 and at most 60 seconds")
    state_dir = Path(state_dir).expanduser().resolve() if state_dir else discover_debug_dir()
    if not state_dir.is_dir():
        raise AutomationError("Debug state directory does not exist; it will not be created implicitly")
    token = debug_session(state_dir)
    request_id = str(uuid.uuid4())
    request = f"HD2TM_DEBUG_REQUEST 1\n{token}\n{request_id}\n{command}\n{payload}"
    if len(request.encode("utf-8")) > 2048:
        raise AutomationError("Debug request exceeds the addon's 2048-byte limit")
    info = {"command": command, "request_id": request_id, "state_dir": str(state_dir),
            "execute": execute, "menu_verified": False, "session_token": token}
    if not execute:
        if journal:
            journal.write("debug_plan", **info, payload=payload)
        return {**info, "dry_run": True, "message": "No bridge files written"}
    # flock only coordinates CLI clients. A separately edited inbox is detected
    # before replacement and while waiting, rather than attributed to our ID.
    with (state_dir / "debug.transport.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise AutomationError("Another debug transport is waiting on this addon") from exc
        if debug_session(state_dir) != token:
            raise AutomationError("Debug session changed before send; request not published")
        previous = bounded_read(state_dir / "debug.request", 2048)
        old = parse_debug_request(previous)
        if previous and not old:
            raise AutomationError("Existing debug.request is malformed; preserved without replacement")
        if old and old["token"] == token:
            ack = parse_debug_response(bounded_read(state_dir / "debug.response", 2048), token, old["request_id"])
            if ack is None:
                raise AutomationError(f"Unacknowledged debug request {old['request_id']} preserved; do not replay it")
        if previous and journal:
            backup = journal.path / f"debug-prior-{time.time_ns()}.request.txt"
            backup.write_text(previous, encoding="utf-8")
            journal.write("debug_previous_preserved", artifact=str(backup), stale_session=bool(old and old["token"] != token))
        if guard:
            guard()
        write_debug_request(state_dir, request, previous)
        if journal:
            journal.write("debug_sent", **info, payload=payload)
        deadline = time.monotonic() + timeout
        while True:
            if guard:
                guard()
            if debug_session(state_dir) != token:
                raise AutomationError("Game debug session changed while awaiting acknowledgement; request will not be replayed")
            response = parse_debug_response(bounded_read(state_dir / "debug.response", 2048), token, request_id)
            if response:
                result = {**info, **response, "transport_acknowledged": True}
                if journal:
                    journal.write("debug_acknowledged", **result)
                if response["status"] == "error":
                    raise AutomationError(f"Debug command failed: {response['message']}")
                return result
            if bounded_read(state_dir / "debug.request", 2048) != request:
                raise AutomationError("Debug inbox was replaced before our acknowledgement; not retrying")
            if time.monotonic() >= deadline:
                raise AutomationError(f"No acknowledgement for request {request_id} within {timeout:g}s; request remains pending and was not replayed")
            time.sleep(min(.1, max(0, deadline-time.monotonic())))


def probe():
    commands = {p: shutil.which(p) for p in ("niri", "grim", "tesseract", "xdotool", "ydotool", "wtype", "import", "xdg-open")}
    return {"commands": commands, "environment": {k: os.environ.get(k) for k in ("DISPLAY", "WAYLAND_DISPLAY", "NIRI_SOCKET", "XDG_SESSION_TYPE")},
            "libraries": {p: ctypes.util.find_library(p) for p in ("X11", "Xtst")},
            "local_tessdata": str(ROOT / ".cache/tessdata"),
            "models": [p.stem for p in (ROOT / ".cache/tessdata").glob("*.traineddata")]}


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true", help="Send bounded input; default is dry-run")
    p.add_argument("--artifacts", default=str(ROOT / ".cache/game-automation"))
    p.add_argument("--window-id", type=int)
    p.add_argument("--tessdata", default=str(ROOT / ".cache/tessdata") if (ROOT / ".cache/tessdata/eng.traineddata").exists() else None)
    p.add_argument("--languages", default="rus+eng")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("probe", "windows", "focus", "observe", "capture", "launch"):
        sub.add_parser(name)
    c = sub.add_parser("classify")
    c.add_argument("image")
    k = sub.add_parser("key")
    k.add_argument("key", choices=sorted(SAFE_KEYS))
    k.add_argument("--duration", type=float, default=.08)
    k.add_argument("--settle", type=float, default=.5)
    k.add_argument("--expect", nargs="+", choices=STATES, required=True)
    c = sub.add_parser("click")
    c.add_argument("x", type=float)
    c.add_argument("y", type=float)
    c.add_argument("--expect", nargs="+", choices=STATES, required=True)
    c = sub.add_parser("click-text")
    c.add_argument("text")
    c.add_argument("--expect", nargs="+", choices=STATES, required=True)
    c = sub.add_parser("look")
    c.add_argument("dx", type=int)
    c.add_argument("dy", type=int)
    c.add_argument("--expect", nargs="+", choices=STATES, required=True)
    c = sub.add_parser("route")
    c.add_argument("file")
    c = sub.add_parser("wait-for")
    c.add_argument("states", nargs="+", choices=STATES[:-1])
    c.add_argument("--timeout", type=float, default=30)
    c = sub.add_parser("debug")
    c.add_argument("debug_command", choices=DEBUG_COMMANDS)
    c.add_argument("--state-dir")
    c.add_argument("--payload", default="", help="Data only. draft_variant: appearance stats passive then newline and label; select_variant: exact saved name")
    c.add_argument("--timeout", type=float, default=10)
    c = sub.add_parser("armory")
    c.add_argument("--launch", action="store_true")
    c.add_argument("--launch-timeout", type=float, default=240,
                   help="Wait 10–300 seconds for the actual game window (default: 240)")
    c.add_argument("--startup-timeout", type=float, default=180,
                   help="Initial startup-view budget, 10–300 seconds (default: 180)")
    c.add_argument("--startup-clicks", action="store_true",
                   help="Confirm an existing game is in its opening movie; allow up to 24 guarded clicks before the first recognized screen")
    c.add_argument("--timeout", type=float, default=60,
                   help="Separate observed-screen stage budget, at most 60 seconds")
    c.add_argument("--state-dir")
    c = sub.add_parser("navigate")
    c.add_argument("--target", choices=("ship", "armory", "equipment"), default="equipment")
    c.add_argument("--max-steps", type=int, choices=range(1, 21), default=8)
    c.add_argument("--wait-seconds", type=float, default=30)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    session = Session(args)
    try:
        if args.command == "probe":
            result = probe()
        elif args.command == "windows":
            result = {"niri": session.windows(), "x11_game": X11().windows()}
        elif args.command == "launch":
            result = session.journal.write("launch", execute=args.execute, url="steam://rungameid/553850")
            if args.execute:
                if any(game_window_candidate(w) for w in session.windows()):
                    raise AutomationError("Game is already running")
                run(["xdg-open", "steam://rungameid/553850"])
        elif args.command == "classify":
            text, words = read_ocr(args.image, args.tessdata, args.languages)
            from PIL import Image
            with Image.open(args.image) as frame:
                width, height = frame.size
            result = {**classify(text, words, width, height), "text": text, "words": words}
        elif args.command == "focus":
            result = session.focus()
        elif args.command == "observe":
            result = session.observe()
        elif args.command == "capture":
            result = session.journal.write("capture", **session.screenshot())
        elif args.command == "key":
            result = session.action({"kind": "key", "key": args.key, "duration": args.duration, "settle": args.settle}, args.expect)
        elif args.command == "click":
            result = session.action({"kind": "click", "x": args.x, "y": args.y}, args.expect)
        elif args.command == "look":
            result = session.action({"kind": "look", "dx": args.dx, "dy": args.dy}, args.expect)
        elif args.command == "click-text":
            result = session.click_text(args.text, args.expect)
        elif args.command == "route":
            result = session.route(args.file)
        elif args.command == "wait-for":
            result = session.wait_for(args.states, args.timeout)
        elif args.command == "debug":
            result = debug_command(args.debug_command, args.payload, args.state_dir, args.execute, args.timeout, session.journal)
        elif args.command == "armory":
            result = session.armory(args.launch, args.timeout, args.state_dir, args.launch_timeout, args.startup_timeout, args.startup_clicks)
        else:
            if not 0 <= args.wait_seconds <= 60:
                raise AutomationError("Navigation loading wait must be 0–60 seconds")
            result = session.navigate(args.target, args.max_steps, args.wait_seconds)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (AutomationError, ValueError, KeyError, OSError) as exc:
        result = session.journal.write("error", error=str(exc), command=args.command)
        print(json.dumps(result, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
