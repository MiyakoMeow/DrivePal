"""隐私保护工具：位置脱敏。"""

import logging
from copy import deepcopy

logger = logging.getLogger(__name__)


def sanitize_location(
    latitude: float, longitude: float, address: str
) -> tuple[float, float, str]:
    """经纬度截断至 2 位小数（~1km），地址取街道级（逗号前第一段）。"""
    lat = round(latitude, 2)
    lon = round(longitude, 2)
    for sep in (",", "，", "、"):
        if sep in address:
            address = address.split(sep, maxsplit=1)[0].strip()
            break
    return lat, lon, address


def sanitize_context(context: dict) -> dict:
    """脱敏 context 中的位置信息（仅处理 current_location + destination 两个固定字段）。深度拷贝避免副作用。"""
    result = deepcopy(context)
    spatial = result.get("spatial", {})
    if isinstance(spatial, dict):
        loc = spatial.get("current_location")
        if isinstance(loc, dict):
            lat, lon, addr = sanitize_location(
                float(loc.get("latitude", 0) or 0),
                float(loc.get("longitude", 0) or 0),
                str(loc.get("address", "")),
            )
            loc["latitude"] = lat
            loc["longitude"] = lon
            loc["address"] = addr
        dest = spatial.get("destination")
        if isinstance(dest, dict):
            dlat, dlon, daddr = sanitize_location(
                float(dest.get("latitude", 0) or 0),
                float(dest.get("longitude", 0) or 0),
                str(dest.get("address", "")),
            )
            dest["latitude"] = dlat
            dest["longitude"] = dlon
            dest["address"] = daddr
    else:
        logger.debug("spatial field is not a dict, skipping location sanitization")
    return result
