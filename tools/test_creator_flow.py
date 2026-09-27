#!/usr/bin/env python3
"""Drive the real creator using fresh semantic UI rectangles; dry-run by default.

The game must already show its custom Armor section. This first version only
selects an already-visible owned look. It never sends an equip/debug mutation.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path
import re
import time

import game_automation as game


class CreatorError(game.AutomationError):
    pass


@dataclass(frozen=True)
class Region:
    action: str
    value: str
    x: float
    y: float
    width: float
    height: float
    page_target: str = ""
    delta: int | None = None

    def point(self, viewport):
        """Convert engine bottom-left viewport coordinates to client top-left."""
        width, height = viewport
        return (self.x+self.width/2)/width, 1-(self.y+self.height/2)/height


@dataclass(frozen=True)
class UiStatus:
    viewport: tuple[int, int]
    step: int
    open: bool
    can_create: bool
    label: str
    stats_tuple_id: str
    selection: dict[str, str]
    regions: tuple[Region, ...]


def identity(value, field):
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512 \
            or any(ord(c) < 32 for c in value):
        raise CreatorError(f"Invalid {field}")
    return value


def parse_ui_status(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 65536 or "\x00" in raw:
        raise CreatorError("UI status is absent or exceeds its bounds")
    lines = raw.splitlines()
    if not lines or lines[0] != "HD2TM_UI_STATUS 1":
        raise CreatorError("Unsupported UI status format")
    fields, rows = {}, []
    for line in lines[1:]:
        if line.startswith("region\t"):
            values = line.split("\t")
            if len(values) != 9 or len(rows) >= 256:
                raise CreatorError("Invalid or excessive UI regions")
            rows.append(values)
        else:
            key, sep, value = line.partition("=")
            if not sep or not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_.]*", key) or key in fields:
                raise CreatorError("Invalid or duplicate UI status field")
            fields[key] = value
    try:
        dimensions = tuple(float(v) for v in fields["viewport"].split(","))
        if len(dimensions) != 2 or any(not math.isfinite(v) or not v.is_integer() for v in dimensions):
            raise ValueError()
        viewport = tuple(int(v) for v in dimensions)
        if not 640 <= viewport[0] <= 16384 or not 480 <= viewport[1] <= 16384:
            raise ValueError()
        step = int(fields["step"])
        if step not in (0, 1, 2, 3) or fields["open"] not in ("true", "false") \
                or fields["can_create"] not in ("true", "false"):
            raise ValueError()
        opened, can_create = fields["open"] == "true", fields["can_create"] == "true"
        if opened != (step != 0) or (can_create and step != 3):
            raise ValueError()
        label, stats_tuple_id = fields["label"], fields["stats_tuple_id"]
    except (KeyError, ValueError, OverflowError) as exc:
        raise CreatorError("Incomplete or inconsistent wizard state") from exc
    if len(label.encode("utf-8")) > 512 or "\t" in label or len(stats_tuple_id) > 512 \
            or (stats_tuple_id and not stats_tuple_id.startswith("base:")):
        raise CreatorError("Invalid wizard label")
    regions = []
    for _, action, value, x, y, width, height, target, delta in rows:
        if not re.fullmatch(r"[a-z_]{1,40}", action) or len(value.encode("utf-8")) > 512:
            raise CreatorError("Invalid region action identity")
        try:
            numbers = tuple(float(v) for v in (x, y, width, height))
            if any(not math.isfinite(v) for v in numbers):
                raise ValueError()
            x, y, width, height = numbers
            if x < 0 or y < 0 or width < 4 or height < 4 \
                    or x+width > viewport[0]+.001 or y+height > viewport[1]+.001:
                raise ValueError()
            if action == "panel_page":
                page_delta = int(delta)
                if target not in ("options", "section", "review") or page_delta not in (-1, 1):
                    raise ValueError()
            else:
                if target or delta:
                    raise ValueError()
                page_delta = None
        except (ValueError, OverflowError) as exc:
            raise CreatorError("Region is not a fully visible bounded control") from exc
        regions.append(Region(action, value, x, y, width, height, target, page_delta))
    selection = {key[10:]: value for key, value in fields.items() if key.startswith("selection.")}
    return UiStatus(viewport, step, opened, can_create, label, stats_tuple_id, selection, tuple(regions))


def choose_region(status, action, value=None, *, page_target=None, delta=None, optional=False):
    found = [r for r in status.regions if r.action == action and (value is None or r.value == value)
             and (page_target is None or r.page_target == page_target) and (delta is None or r.delta == delta)]
    if len(found) > 1:
        raise CreatorError(f"Ambiguous enabled control: {action} {value or ''}")
    if not found and not optional:
        raise CreatorError(f"Requested visible control is unavailable: {action} {value or ''}")
    return found[0] if found else None


def page_signature(status, action):
    return tuple((r.action, r.value, r.page_target, r.delta) for r in status.regions
                 if r.action == action or (r.action == "panel_page" and r.page_target == "options"))


def parse_saved_labels(raw):
    if not raw or not raw.startswith("HD2TM_VARIANT_STATUS 1\n"):
        raise CreatorError("Fresh saved-variant status unavailable")
    labels = [line[6:] for line in raw.splitlines()[1:] if line.startswith("saved ")]
    if len(labels) > 256 or len(set(labels)) != len(labels):
        raise CreatorError("Saved-label status is ambiguous")
    return {identity(value, "saved label") for value in labels}


class CreatorDriver:
    def __init__(self, session, state_dir=None, timeout=30, max_pages=16):
        if not math.isfinite(timeout) or not 1 <= timeout <= 60:
            raise CreatorError("Per-stage timeout must be 1–60 seconds")
        if not isinstance(max_pages, int) or not 0 <= max_pages <= 32:
            raise CreatorError("Page-click budget must be 0–32")
        self.session = session
        self.state_dir_arg = state_dir
        self.timeout, self.max_pages = timeout, max_pages
        self.state_dir = None
        self.token = None
        self.created_click = False
        self.persistence_confirmed = False

    def guard(self):
        self.session.assert_focus()
        if self.token is not None and game.debug_session(self.state_dir) != self.token:
            raise CreatorError("Game session changed; no wizard action will be replayed")

    def refresh(self, command, filename):
        self.guard()
        path = self.state_dir / filename
        before = game.file_identity(path)
        ack = game.debug_command(command, state_dir=self.state_dir, execute=True,
                                 timeout=min(10, self.timeout), journal=self.session.journal, guard=self.guard)
        if self.token is None:
            self.token = ack["session_token"]
        self.guard()
        if ack["session_token"] != self.token:
            raise CreatorError("Status acknowledgement belongs to another session")
        current = game.file_identity(path)
        if current is None or current == before:
            raise CreatorError(f"{filename} was not freshly written for this request")
        raw = game.bounded_read(path, 65536)
        request = game.parse_debug_request(game.bounded_read(self.state_dir / "debug.request", 2048))
        if not request or request["token"] != self.token or request["request_id"] != ack["request_id"] \
                or request["command"] != command or game.file_identity(path) != current:
            raise CreatorError("Status or debug request changed concurrently")
        self.guard()
        artifact = self.session.journal.path / f"{Path(filename).stem}-{ack['request_id']}.txt"
        artifact.write_text(raw, encoding="utf-8")
        self.session.journal.write("creator_status", command=command, request_id=ack["request_id"], artifact=str(artifact))
        return raw

    def status(self):
        return parse_ui_status(self.refresh("ui_status", "debug-ui-status.txt"))

    def saved_labels(self):
        return parse_saved_labels(self.refresh("variant_status", "debug-variant-status.txt"))

    def wait(self, predicate, description):
        deadline = time.monotonic()+self.timeout
        while True:
            state = self.status()
            if predicate(state):
                return state
            if time.monotonic() >= deadline:
                raise CreatorError(f"Timed out waiting for {description}; no click was repeated")
            time.sleep(.15)

    def click(self, action, *, step, value=None, page_target=None, delta=None, create_state=None):
        # Observe first, then refresh semantic rectangles so expensive OCR does
        # not age the coordinate evidence before the input.
        observation = self.session.observe()
        if observation["state"] not in ("equipment", "unknown"):
            raise CreatorError(f"Wizard is not the active game view: {observation['state']}")
        state = self.status()
        if state.step != step or state.open != (step != 0):
            raise CreatorError("Wizard step changed before click")
        if tuple(state.viewport) != (observation["width"], observation["height"]):
            raise CreatorError("Viewport differs from captured game; coordinates were not used")
        region = choose_region(state, action, value, page_target=page_target, delta=delta)
        if action == "create":
            if self.created_click or not state.can_create:
                raise CreatorError("Create is disabled or has already been attempted")
            if create_state is None or state.label != create_state.label or state.selection != create_state.selection \
                    or state.stats_tuple_id != create_state.stats_tuple_id:
                raise CreatorError("Creator label or selections changed before Create; no click sent")
            self.created_click = True
        self.guard()
        x, y = region.point(state.viewport)
        self.session.journal.write("creator_click", action=action, value=region.value, step=step,
                                   viewport=state.viewport, rect=[region.x, region.y, region.width, region.height],
                                   basis="fresh addon UI region", screenshot=observation["path"])
        result = self.session.action({"kind":"click", "x":x, "y":y, "label":f"creator:{action}:{region.value}"},
                                     ["equipment", "unknown"], observation)
        return state, result["after"]

    def choose_paged(self, action, value, step):
        deadline = time.monotonic()+self.timeout
        clicks = 0
        direction = -1  # Start from any retained option page, then walk forward.
        seen = {-1:set(), 1:set()}
        while True:
            if time.monotonic() >= deadline:
                raise CreatorError("Bounded option-page search exhausted")
            state = self.status()
            if state.step != step or not state.open:
                raise CreatorError("Wizard changed while searching options")
            if choose_region(state, action, value, optional=True):
                return self.click(action, step=step, value=value)
            signature = page_signature(state, action)
            if signature in seen[direction]:
                raise CreatorError("Option page repeated without finding the requested identity")
            seen[direction].add(signature)
            page = choose_region(state, "panel_page", page_target="options", delta=direction, optional=True)
            if page is None and direction == -1:
                direction = 1
                continue
            if page is None:
                raise CreatorError(f"Requested option is unavailable: {action} {value}")
            if clicks >= self.max_pages or time.monotonic() >= deadline:
                raise CreatorError("Bounded option-page search exhausted")
            self.click("panel_page", step=step, page_target="options", delta=direction)
            clicks += 1
            self.wait(lambda s: s.step == step and page_signature(s, action) != signature, "a changed option page")

    def run(self, look, stats, passive):
        look, stats, passive = (identity(v, key) for v, key in
                                ((look, "look identity"), (stats, "base tuple identity"), (passive, "passive identity")))
        if not stats.startswith("base:"):
            raise CreatorError("Choose a base: tuple from the wizard, not a stat-donor identity")
        if not self.session.args.execute:
            return {"dry_run":True, "look":look, "stats":stats, "passive":passive, "saved":False,
                    "steps":["Click +", "Click specified visible owned look", "Page to and click base tuple",
                             "Page to and click passive", "Click Create once when enabled", "Verify closed wizard and new saved card"]}
        self.state_dir = Path(self.state_dir_arg).expanduser().resolve() if self.state_dir_arg else game.discover_debug_dir()
        self.session.focus()
        self.token = game.debug_session(self.state_dir)
        initial = self.status()
        if initial.open or initial.step != 0:
            raise CreatorError("Close the current draft before starting a new creator test")
        choose_region(initial, "open")
        before_labels = self.saved_labels()
        self.click("open", step=0)
        state = self.wait(lambda s: s.open and s.step == 1, "look picker")
        # No scrolling/teleporting to obtain an absent look in this version.
        choose_region(state, "select_look", look)
        self.click("select_look", step=1, value=look)
        self.wait(lambda s: s.step == 2 and s.selection.get("appearance_id") == look, "selected look and base stats")
        self.choose_paged("select_stats", stats, 2)
        self.wait(lambda s: s.step == 3 and s.stats_tuple_id == stats and bool(s.selection.get("stats_id")), "selected base tuple and passive picker")
        self.choose_paged("select_passive", passive, 3)
        ready = self.wait(lambda s: s.step == 3 and s.can_create and s.stats_tuple_id == stats and s.selection.get("appearance_id") == look
                          and s.selection.get("passive_variant_id") == passive, "enabled Create")
        label = identity(ready.label, "new variant label")
        if label in before_labels:
            raise CreatorError("The proposed variant label already existed; Create was not clicked")
        self.click("create", step=3, create_state=ready)
        self.wait(lambda s: not s.open and s.step == 0, "closed saved wizard")
        if label not in self.saved_labels():
            raise CreatorError("Wizard closed but the fresh saved-label report lacks the new variant")
        self.persistence_confirmed = True
        visible = self.wait(lambda s: s.step == 0 and not s.open and
                            choose_region(s, "select_variant", label, optional=True) is not None, "new saved card")
        self.guard()
        final = self.session.observe()
        self.guard()
        current = self.status()
        if current.open or current.step != 0 or choose_region(current, "select_variant", label, optional=True) is None \
                or tuple(current.viewport) != (final["width"], final["height"]) \
                or final["state"] not in ("equipment", "unknown"):
            raise CreatorError("Saved card or native viewport changed during final capture; Create was not repeated")
        result = {"saved":True, "label":label, "look":look, "stats":stats, "passive":passive,
                  "wizard_step":visible.step, "saved_card_visible":True, "create_clicks":1,
                  "equip_action_sent":False, "observation":final}
        artifact = self.session.journal.path / "creator-result.json"
        artifact.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
        self.session.journal.write("creator_verified", label=label, artifact=str(artifact), screenshot=final["path"])
        return result


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--look", required=True, help="Visible owned look identity from ui_status")
    p.add_argument("--stats", required=True, help="Exact base: tuple identity")
    p.add_argument("--passive", required=True, help="Exact passive identity")
    p.add_argument("--state-dir")
    p.add_argument("--artifacts", default=str(game.ROOT / ".cache/game-automation/creator-run"))
    p.add_argument("--window-id", type=int)
    p.add_argument("--tessdata", default=str(game.ROOT / ".cache/tessdata") if (game.ROOT / ".cache/tessdata/eng.traineddata").exists() else None)
    p.add_argument("--languages", default="rus+eng")
    p.add_argument("--timeout", type=float, default=30, help="Per-step wait budget, 1–60 seconds")
    p.add_argument("--max-pages", type=int, default=16, help="Maximum option-page clicks per choice, 0–32")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    session = game.Session(args)
    driver = None
    try:
        driver = CreatorDriver(session,args.state_dir,args.timeout,args.max_pages)
        result = driver.run(args.look,args.stats,args.passive)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (game.AutomationError, ValueError, KeyError, OSError) as exc:
        attempted = bool(driver and driver.created_click)
        saved = True if driver and driver.persistence_confirmed else (None if attempted else False)
        session.journal.write("creator_error", error=str(exc), create_was_not_replayed=True,
                              create_attempted=attempted, saved=saved)
        print(json.dumps({"error":str(exc),"saved":saved,"create_attempted":attempted,"inspect_before_retry":True}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
