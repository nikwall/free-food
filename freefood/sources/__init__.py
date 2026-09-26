"""Registry of event sources. Add a line here to scan another calendar.

Every source has .id, .name, .homepage and .fetch(start_date, end_date, http) -> [Event].
Reusable adapters:
  TrumbaSource(web_name=...)      any Trumba calendar (Gazette and several schools)
  LiveWhaleSource(base=...)       any LiveWhale calendar
  TribeSource(base=...)           any WordPress site with The Events Calendar plugin
  WpAcfSource(base=...)           WordPress `event` post type with ACF details
"""
from .hks import HksSource
from .hls import HlsSource
from .livewhale import LiveWhaleSource
from .newsletters import NewsletterSource
from .trumba import TrumbaSource
from .wordpress import TribeSource, WpAcfSource

SOURCES = [
    TrumbaSource(),                                   # university-wide Gazette calendar
    HksSource(),                                      # HKS + IOP, Belfer, CPL, M-RCBG, ...
    HlsSource(),                                      # Harvard Law School
    LiveWhaleSource(),                                # Harvard College
    WpAcfSource("ash", "Ash Center (HKS)", "https://ash.harvard.edu", "Ash Center for Democratic Governance"),
    WpAcfSource("shorenstein", "Shorenstein Center (HKS)", "https://shorensteincenter.org",
                "Shorenstein Center on Media, Politics and Public Policy"),
    TribeSource("fairbank", "Fairbank Center", "https://fairbank.fas.harvard.edu",
                "Fairbank Center for Chinese Studies"),
    NewsletterSource(),
]
