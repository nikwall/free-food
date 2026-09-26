"""'I'm going' / 'Skip it' votes, shared by everyone who uses the site.

Each phone or browser gets a random device id (kept in its localStorage) and may
set a first name that other fellows see next to "going". One vote per device and
event; voting the same way again removes the vote. Stored in data/votes.json.

The same talk can be listed on several calendars. The pipeline gives the merged
event a stable id plus `aliases`, so votes are counted over the id and all aliases.
"""
import json
import re
import threading
import time
from datetime import datetime, timedelta

from .config import DATA_DIR, EVENTS_FILE, TZ

VOTES_FILE = DATA_DIR / "votes.json"
DEVICE_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
KEEP_DAYS = 30


class VoteStore:
    def __init__(self, path=VOTES_FILE):
        self.path = path
        self.lock = threading.Lock()
        self._events_mtime, self._groups = None, {}
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            self.data = {}
        self.data.setdefault("votes", {})    # event_id -> device -> {"v": "going"|"skip", "t": iso}
        self.data.setdefault("names", {})    # device -> first name

    # -- event id groups from the latest scan --------------------------------------------
    def _event_groups(self):
        """canonical id -> [canonical id, *aliases]; alias -> canonical id."""
        try:
            mtime = EVENTS_FILE.stat().st_mtime
        except FileNotFoundError:
            return {}, {}
        if mtime != self._events_mtime:
            events = json.loads(EVENTS_FILE.read_text(encoding="utf-8"))["events"]
            groups = {e["id"]: [e["id"], *e.get("aliases", [])] for e in events}
            canon = {i: cid for cid, ids in groups.items() for i in ids}
            self._events_mtime, self._groups = mtime, (groups, canon)
        return self._groups

    # -- reading ------------------------------------------------------------------------------
    def tally(self, device=""):
        groups, _canon = self._event_groups()
        out = {}
        with self.lock:
            votes, names = self.data["votes"], self.data["names"]
            for cid, ids in groups.items():
                by_device = {}
                for i in ids:                       # later entries win, so a device counts once
                    by_device.update(votes.get(i, {}))
                if not by_device:
                    continue
                going = [d for d, x in by_device.items() if x["v"] == "going"]
                skip = [d for d, x in by_device.items() if x["v"] == "skip"]
                out[cid] = {
                    "going": len(going), "skip": len(skip),
                    "names": sorted(names[d] for d in going if names.get(d)),
                    "mine": by_device.get(device, {}).get("v"),
                }
        return {"votes": out, "name": self.data["names"].get(device, "")}

    # -- writing ------------------------------------------------------------------------------
    def vote(self, event_id, device, vote, name=None):
        if not DEVICE_RE.match(device or ""):
            raise ValueError("bad device id")
        if vote not in ("going", "skip", None):
            raise ValueError("vote must be 'going', 'skip' or null")
        groups, canon = self._event_groups()
        cid = canon.get(event_id)
        if cid is None:
            raise KeyError("unknown event")
        with self.lock:
            for i in groups[cid]:                   # clear this device's vote under every alias
                self.data["votes"].get(i, {}).pop(device, None)
            if vote:
                self.data["votes"].setdefault(cid, {})[device] = {"v": vote, "t": datetime.now(TZ).isoformat(timespec="seconds")}
            if name is not None:
                self._set_name(device, name)
            self._prune()
            self._save()
        return self.tally(device)["votes"].get(cid, {"going": 0, "skip": 0, "names": [], "mine": None})

    def set_name(self, device, name):
        if not DEVICE_RE.match(device or ""):
            raise ValueError("bad device id")
        with self.lock:
            self._set_name(device, name)
            self._save()

    def _set_name(self, device, name):
        name = re.sub(r"[\x00-\x1f<>]", "", str(name or "")).strip()[:24]
        if name:
            self.data["names"][device] = name
        else:
            self.data["names"].pop(device, None)

    def _prune(self):
        cutoff = (datetime.now(TZ) - timedelta(days=KEEP_DAYS)).isoformat()
        for eid in list(self.data["votes"]):
            devs = {d: x for d, x in self.data["votes"][eid].items() if x.get("t", "") >= cutoff}
            if devs:
                self.data["votes"][eid] = devs
            else:
                del self.data["votes"][eid]

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False), encoding="utf-8")
        for attempt in range(5):                    # Windows: a reader may briefly hold the file
            try:
                tmp.replace(self.path)
                return
            except PermissionError:
                time.sleep(0.05 * (attempt + 1))
        raise
