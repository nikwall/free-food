"""The one record type every source produces."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Event:
    source_id: str
    source_name: str
    title: str
    url: str
    start: datetime                      # timezone-aware
    end: Optional[datetime] = None
    all_day: bool = False
    location: str = ""                   # free text as published
    description: str = ""                # plain text (HTML already stripped)
    host: str = ""                       # sponsoring center / organization
    online: bool = False                 # online-only event
    canceled: bool = False
    registration_link: str = ""          # structured link from the source, if any
    registration_hint: str = ""          # "required" / "rsvp" / "none" when the source says so
    lat: Optional[float] = None          # structured coordinates from the source, if any
    lon: Optional[float] = None
    extra: dict = field(default_factory=dict)

    def to_dict(self):
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat() if self.end else None
        return d
