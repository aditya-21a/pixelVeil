"""
Stores and applies user-marked static redaction zones — fixed regions
redacted on every frame regardless of detection (e.g. "always cover this
CRM sidebar").
"""


class ZoneManager:
    def __init__(self):
        self.zones = []  # list of (x, y, w, h)

    def add_zone(self, bbox):
        raise NotImplementedError

    def remove_zone(self, index):
        raise NotImplementedError

    def get_zones(self):
        return self.zones
