"""主动触发框架——PendingReminder 管理和轮询触发."""

import math
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.storage.toml_store import TOMLStore

if TYPE_CHECKING:
    from pathlib import Path

    from app.agents.outputs import MultiFormatContent

_PROXIMITY_RADIUS_M = 500
_DEFAULT_TTL_SECONDS = 3600
_TTL_EXTRA_FOR_TIME = 1800


@dataclass
class PendingReminder:
    """待触发提醒."""

    id: str
    event_id: str
    content: dict  # MultiFormatContent.model_dump()
    trigger_type: str  # "location" | "time" | "context"
    trigger_target: dict
    trigger_text: str  # 人类可读触发条件
    status: str  # "pending" | "triggered" | "cancelled"
    created_at: str
    ttl_seconds: int

    @classmethod
    def new(  # noqa: PLR0913
        cls,
        *,
        content: MultiFormatContent,
        trigger_type: str,
        trigger_target: dict,
        event_id: str,
        trigger_text: str = "",
        ttl_seconds: int = 3600,
    ) -> PendingReminder:
        """创建新的 PendingReminder 实例。"""
        return cls(
            id=f"pr_{uuid.uuid4().hex[:12]}",
            event_id=event_id,
            content=content.model_dump(),
            trigger_type=trigger_type,
            trigger_target=trigger_target,
            trigger_text=trigger_text,
            status="pending",
            created_at=datetime.now(UTC).isoformat(),
            ttl_seconds=ttl_seconds,
        )


class PendingReminderManager:
    """管理待触发提醒的增删查与轮询触发."""

    def __init__(self, user_dir: Path) -> None:
        """初始化待触发提醒管理器。

        Args:
            user_dir: 用户数据目录路径。

        """
        self._store = TOMLStore(
            user_dir=user_dir,
            filename="pending_reminders.toml",
            default_factory=list,
        )

    async def _read_all(self) -> list[dict]:
        return await self._store.read()

    async def _write_all(self, reminders: list[dict]) -> None:
        await self._store.write(reminders)

    async def add(  # noqa: PLR0913
        self,
        content: MultiFormatContent,
        trigger_type: str,
        trigger_target: dict,
        event_id: str,
        trigger_text: str = "",
        ttl_seconds: int | None = None,
    ) -> PendingReminder:
        """添加一条待触发提醒。"""
        if ttl_seconds is None:
            if trigger_type == "time":
                target_str = str(trigger_target.get("time", ""))
                try:
                    target_dt = datetime.fromisoformat(target_str)
                    if target_dt.tzinfo is None:
                        target_dt = target_dt.replace(tzinfo=UTC)
                    delta = (target_dt - datetime.now(UTC)).total_seconds()
                    ttl_seconds = int(max(delta, 0)) + _TTL_EXTRA_FOR_TIME
                except ValueError, TypeError:
                    ttl_seconds = _DEFAULT_TTL_SECONDS
            else:
                ttl_seconds = _DEFAULT_TTL_SECONDS

        pr = PendingReminder.new(
            content=content,
            trigger_type=trigger_type,
            trigger_target=trigger_target,
            event_id=event_id,
            trigger_text=trigger_text,
            ttl_seconds=ttl_seconds,
        )
        all_rem = await self._read_all()
        all_rem.append(asdict(pr))
        await self._write_all(all_rem)
        return pr

    async def list_pending(self) -> list[dict]:
        """返回所有 status=pending 的提醒列表。"""
        all_rem = await self._read_all()
        return [r for r in all_rem if r.get("status") == "pending"]

    async def cancel(self, reminder_id: str) -> None:
        """取消指定 ID 的待触发提醒。"""
        all_rem = await self._read_all()
        for r in all_rem:
            if r.get("id") == reminder_id:
                r["status"] = "cancelled"
        await self._write_all(all_rem)

    async def cancel_last(self) -> bool:
        """取消最近一条 pending reminder。返回是否成功取消。"""
        all_rem = await self._read_all()
        pending = [r for r in all_rem if r.get("status") == "pending"]
        if not pending:
            return False
        pending[-1]["status"] = "cancelled"
        await self._write_all(all_rem)
        return True

    async def poll(self, driving_context: dict) -> list[dict]:
        """返回满足触发条件的提醒列表，并将其标记为 triggered。"""
        all_rem = await self._read_all()
        triggered = []
        now = datetime.now(UTC)
        for r in all_rem:
            if r.get("status") != "pending":
                continue
            # TTL 超时
            created_str = r.get("created_at", "")
            try:
                created = datetime.fromisoformat(created_str)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=UTC)
                if (now - created).total_seconds() > (r.get("ttl_seconds") or 3600):
                    r["status"] = "cancelled"
                    continue
            except ValueError, TypeError:
                pass

            # 触发评估
            trigger_type = r.get("trigger_type", "")
            if (
                (
                    trigger_type == "location"
                    and self._check_location(r, driving_context)
                )
                or (trigger_type == "time" and self._check_time(r))
                or (
                    trigger_type == "context"
                    and self._check_context(r, driving_context)
                )
            ):
                r["status"] = "triggered"
                triggered.append(r)

        if triggered:
            await self._write_all(all_rem)
        return triggered

    @staticmethod
    def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """返回两点间距离（米）。"""
        earth_radius_m = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlam = math.radians(lon2 - lon1)
        a = (
            math.sin(dphi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
        )
        return earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _check_location(reminder: dict, ctx: dict) -> bool:
        target = reminder.get("trigger_target", {})
        spatial = ctx.get("spatial") or {}
        cur_loc = spatial.get("current_location") or {}
        if not cur_loc:
            return False
        if ctx.get("scenario") == "parked":
            return True
        target_lat = target.get("latitude")
        target_lon = target.get("longitude")
        if target_lat is None or target_lon is None:
            return False
        dist = PendingReminderManager._haversine(
            float(cur_loc.get("latitude") or 0),
            float(cur_loc.get("longitude") or 0),
            float(target_lat),
            float(target_lon),
        )
        return dist < _PROXIMITY_RADIUS_M

    @staticmethod
    def _check_time(reminder: dict) -> bool:
        target = reminder.get("trigger_target", {})
        target_time_str = target.get("time", "")
        if not target_time_str:
            return False
        try:
            target_time = datetime.fromisoformat(target_time_str)
        except ValueError, TypeError:
            return False
        if target_time.tzinfo is None:
            target_time = target_time.replace(tzinfo=UTC)
        return datetime.now(UTC) >= target_time

    @staticmethod
    def _check_context(reminder: dict, ctx: dict) -> bool:
        """Context 触发：当前 scenario != 入队时的 scenario（场景切换）。"""
        target = reminder.get("trigger_target", {})
        prev = target.get("previous_scenario", "")
        current = ctx.get("scenario", "")
        return bool(prev) and bool(current) and prev != current


def parse_duration(s: str) -> int | None:
    """解析中文时长字符串为秒数。支持 '10分钟' '半小时' '1小时' '5分'。"""
    s = s.strip()
    if s == "半小时":
        return 1800
    m = re.match(r"(\d+)\s*(小时|分钟|分)", s)
    if m:
        num = int(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            return num * 3600
        return num * 60
    return None


def parse_time(s: str) -> str | None:
    """解析中文时间字符串为 ISO 时间 HH:MM:SS。

    支持 '3点'→'15:00', '下午3点'→'15:00', '上午9点'→'09:00'。
    上/下午缺省时 < 8 算下午。
    """
    s = s.strip()
    m = re.match(r"(上午|下午)?(\d+)点", s)
    if not m:
        return None
    noon = 12
    afternoon_threshold = 8  # 缺省上/下午时，< 8 点视为下午
    am_pm = m.group(1)
    hour = int(m.group(2))
    if am_pm == "上午" and hour == noon:
        hour = 0
    elif (am_pm == "下午" and hour != noon) or (
        am_pm is None and hour < afternoon_threshold
    ):
        hour += noon
    return f"{hour:02d}:00:00"
