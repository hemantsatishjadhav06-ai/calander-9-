"""Map retired IANA zone names onto their current ones.

Browsers still report some zones by names the IANA database kept only as
backward-compatible links: Chrome sends "Asia/Calcutta" for India, so an org
created from an Indian browser showed "Calcutta" everywhere. Both names resolve
to the same rules, so rewriting is purely cosmetic and always safe.
"""

LEGACY_ZONE_NAMES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon",
    "Asia/Dacca": "Asia/Dhaka",
    "Asia/Thimbu": "Asia/Thimphu",
    "Asia/Ulan_Bator": "Asia/Ulaanbaatar",
    "Asia/Macao": "Asia/Macau",
    "Asia/Chungking": "Asia/Chongqing",
    "Europe/Kiev": "Europe/Kyiv",
    "Europe/Uzhgorod": "Europe/Kyiv",
    "Europe/Zaporozhye": "Europe/Kyiv",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires",
    "America/Godthab": "America/Nuuk",
    "Atlantic/Faeroe": "Atlantic/Faroe",
    "Pacific/Enderbury": "Pacific/Kanton",
}


def canonical_timezone(name: str) -> str:
    """The current IANA name for *name*, or *name* itself when it is not retired."""
    return LEGACY_ZONE_NAMES.get(name, name)
