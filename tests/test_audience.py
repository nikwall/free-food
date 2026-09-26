"""Audience checks on phrasings and listing fields seen in real Harvard listings.  Run: python tests/test_audience.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from freefood.audience import detect_audience  # noqa: E402

CASES = [
    # (title, text, source, host, extra, expected level)
    ("Talk", "This event is open to Harvard ID holders only. Lunch will be served.", "ash", "", {}, "harvard"),
    ("Talk", "Attendance is in-person and for HUID holders only.", "hks", "", {}, "harvard"),
    ("Talk", "The in-person event is open to Harvard University ID holders only. Virtual event is open to all.", "hks", "", {}, "harvard"),
    ("Talk", "These off-the-record conversations are open to members of the Harvard community.", "hks", "", {}, "harvard"),
    ("Talk", "Free and open to the public. A reception will follow.", "gazette", "", {}, "public"),
    ("Talk", "This class is open to a wide audience including Harvard students, faculty, fellows, staff members.", "hks", "", {}, "harvard"),
    ("Panel", "This event is open to HLS students only.", "hls", "", {}, "restricted"),
    ("Dinner", "Dinner is by invitation only.", "gazette", "", {}, "restricted"),
    ("Meeting", "Open to residents of Winthrop House.", "college", "", {}, "restricted"),
    ("Lunch", "Lunch provided.", "hls", "", {"hls_audiences": ["All HLS students only"]}, "restricted"),
    ("Lunch", "Lunch provided.", "hls", "", {"hls_audiences": ["All Harvard"]}, "harvard"),
    ("Lunch", "Lunch provided.", "hls", "", {"hls_audiences": ["1Ls"]}, "restricted"),
    ("Advising", "Pizza.", "college", "", {"class_years": ["Sophomore"]}, "restricted"),
    ("Exhibit", "Opening.", "gazette", "", {"harvard_key": "Yes"}, "harvard"),
    ("Willkie 1L Coffee Chat", "", "hls", "", {}, "restricted"),
    ("Computer Science Sophomore Advising Event", "Empanadas will be available.", "college", "", {}, "restricted"),
    ("Junior brunch", "", "college", "Winthrop House", {"group": "Winthrop House"}, "restricted"),
    ("Faculty Deans’ Open House", "Enjoy snacks.", "college", "Dunster House", {}, "restricted"),
    ("SCR Afternoon Tea", "Meet the Senior Common Room.", "college", "Winthrop House", {}, "restricted"),
    ("HALS First GBM", "Lunch will be provided!", "hls", "", {}, "restricted"),
    # stricter defaults
    ("NALSA General Body Meeting", "NALSA is open to all students, allies, and anyone interested.", "hls", "", {}, "restricted"),
    ("Snackie Social", "Share food from different cultures.", "college", "Dean of Students Office", {}, "restricted"),
    ("MSI Chalk Talk", "No advanced registration required; all are welcome.", "college", "", {}, "public"),
    ("HLS Dems Reading Group", "Light food will be provided.", "hls", "", {"student_org": True}, "restricted"),
    ("Winter Term Opportunities", "Lunch will be served.", "hls", "", {"hls_office": "OCS"}, "restricted"),
    ("Law and Public Service", "Sandwiches will be served.", "hls", "", {}, "likely"),
    ("AIIB at 10", "A light lunch will be provided.", "hls", "", {"research_program": True}, "unknown"),
    ("Texas Club Big Kickoff BBQ", "", "hls", "", {"hls_audiences": ["All Harvard"], "student_org": True}, "harvard"),
    ("Talk with Junior Faculty", "", "gazette", "", {}, "unknown"),
    ("Book talk", "A reception will follow.", "gazette", "", {}, "unknown"),
]


def test_cases():
    for title, text, src, host, extra, level in CASES:
        got = detect_audience(title, text, src, host, extra)
        assert got["level"] == level, (title, text, got)


def test_groups():
    got = detect_audience("Panel", "This event is open to HLS students only.", "hls")
    assert "HLS students" in got["group"], got
    got = detect_audience("Lunch", "", "hls", "", {"hls_audiences": ["1L", "1Ls", "LLM", "LLMs"]})
    assert got["group"] == "HLS 1Ls, LLMs", got


if __name__ == "__main__":
    test_cases(); test_groups()
    print("audience checks passed")
