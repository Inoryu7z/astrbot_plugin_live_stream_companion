# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Any

from astrbot.api import logger
from quart import request

from .page_config import PageConfigManager

PLUGIN_NAME = "astrbot_plugin_live_stream_companion"
PAGE_API_PREFIX = f"/{PLUGIN_NAME}/page"


class LiveStreamCompanionPageApi:
    """AstrBot 插件拓展页面 API。"""

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.config_manager = PageConfigManager(plugin, PLUGIN_NAME, logger)

    def register_routes(self) -> None:
        register = getattr(self.plugin.context, "register_web_api", None)
        if not callable(register):
            logger.debug("[B站直播] 当前 AstrBot 版本不支持拓展页 API 注册。")
            return
        routes = [
            ("/overview", self.get_overview, ["GET"], "Live Stream Companion overview"),
            ("/memory", self.get_memory, ["GET"], "Live Stream Companion live memory"),
            ("/config/schema", self.get_config_schema, ["GET"], "Live Stream Companion config schema"),
            ("/config/save", self.save_config, ["POST"], "Live Stream Companion save config"),
            ("/subtitle/preview", self.preview_subtitle, ["POST"], "Live Stream Companion subtitle preview"),
            ("/control/start", self.start_live, ["POST"], "Live Stream Companion start live"),
            ("/control/stop", self.stop_live, ["POST"], "Live Stream Companion stop live"),
        ]
        for path, handler, methods, desc in routes:
            register(f"{PAGE_API_PREFIX}{path}", handler, methods, desc)

    async def get_overview(self) -> dict[str, Any]:
        try:
            plugin = self.plugin
            companion = plugin._get_private_companion_plugin()
            store = plugin._private_companion_live_state_store(companion) if companion else {}
            events = list(getattr(plugin, "_bili_events", []))
            session_events = list(getattr(plugin, "_bili_session_events", []))
            return self._ok(
                {
                    "plugin": {
                        "name": PLUGIN_NAME,
                        "display_name": "我会直播圈米养你",
                        "version": "1.4.3",
                    },
                    "live": self._live_summary(events, session_events),
                    "vts": self._vts_summary(),
                    "subtitle": self._subtitle_summary(),
                    "mouth_sync": self._mouth_sync_summary(),
                    "auto_reply": self._auto_reply_summary(),
                    "companion": self._companion_summary(companion, store),
                    "memory": self._memory_summary(store),
                    "viewers": self._viewer_summary(store),
                    "recent_events": [self._event_payload(item) for item in events[-20:]][::-1],
                    "config": self._config_summary(),
                }
            )
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页概览读取失败: {exc}")
            return self._error(str(exc))

    async def get_memory(self) -> dict[str, Any]:
        try:
            companion = self.plugin._get_private_companion_plugin()
            if companion is None:
                return self._ok({"available": False, "message": "未找到“我会永远陪着你”插件实例。"})
            store = self.plugin._private_companion_live_state_store(companion)
            return self._ok(
                {
                    "available": True,
                    "overview": self.plugin._format_live_memory_overview(companion, limit=12),
                    "memory": self._memory_summary(store, detailed=True),
                    "viewers": self._viewer_summary(store, limit=50),
                }
            )
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页记忆读取失败: {exc}")
            return self._error(str(exc))

    async def get_config_schema(self) -> dict[str, Any]:
        try:
            return self._ok(self.config_manager.schema_payload())
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页配置结构读取失败: {exc}")
            return self._error(str(exc))

    async def save_config(self) -> dict[str, Any]:
        try:
            payload = await request.get_json(silent=True) or {}
            values = payload.get("values") if isinstance(payload.get("values"), dict) else {}
            updates = self.config_manager.build_updates(values)
            if not updates:
                return self._ok({"message": "没有可保存的配置变更。", "values": self._config_summary()})

            persisted = await self.config_manager.apply_updates(updates)
            return self._ok(
                {
                    "message": "配置已保存。" if persisted else "配置已应用到当前运行实例，但未确认持久化。",
                    "persisted": persisted,
                    "values": self._config_summary(),
                }
            )
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页配置保存失败: {exc}")
            return self._error(str(exc))

    async def preview_subtitle(self) -> dict[str, Any]:
        try:
            payload = await request.get_json(silent=True) or {}
            text = str(payload.get("text") or "谢谢喜欢，今天也一起把直播间热起来吧。")
            server = getattr(self.plugin, "_subtitle_server", None)
            if server is None:
                return self._ok(
                    {
                        "sent": False,
                        "message": "字幕服务未运行，已在页面内播放本地预览。",
                        "style": self.plugin._get_subtitle_style(),
                    }
                )
            await self.plugin._push_subtitle(text)
            return self._ok(
                {
                    "sent": True,
                    "message": "已发送到字幕 overlay，同时页面内播放预览。",
                    "style": self.plugin._get_subtitle_style(),
                }
            )
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页字幕预览失败: {exc}")
            return self._error(str(exc))

    async def start_live(self) -> dict[str, Any]:
        try:
            payload = await request.get_json(silent=True) or {}
            room_id = self._int(payload.get("room_id")) or self.plugin._get_config_room_id()
            message = await self.plugin._start_bili_live(room_id)
            return self._ok({"message": message})
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页启动监听失败: {exc}")
            return self._error(str(exc))

    async def stop_live(self) -> dict[str, Any]:
        try:
            message = await self.plugin._stop_bili_live()
            return self._ok({"message": message})
        except Exception as exc:
            logger.warning(f"[B站直播] 拓展页停止监听失败: {exc}")
            return self._error(str(exc))

    def _live_summary(self, events: list[Any], session_events: list[Any]) -> dict[str, Any]:
        plugin = self.plugin
        running = bool(plugin._is_bili_live_running())
        latest = events[-1] if events else None
        counts: dict[str, int] = {}
        viewers: dict[str, int] = {}
        for item in session_events:
            event_type = str(getattr(item, "event_type", "") or "")
            counts[event_type] = counts.get(event_type, 0) + 1
            username = plugin._single_line_text(getattr(item, "username", ""), 40)
            if username and username != "系统":
                viewers[username] = viewers.get(username, 0) + 1
        top_viewers = sorted(viewers.items(), key=lambda item: item[1], reverse=True)[:8]
        started = float(getattr(plugin, "_bili_session_started_at", 0.0) or 0.0)
        return {
            "enabled": bool(plugin._is_bili_live_enabled()),
            "running": running,
            "type": plugin._get_bili_live_type(),
            "backend": plugin._get_bili_web_backend(),
            "room_id": getattr(getattr(plugin, "_bili_live_client", None), "real_room_id", None) or plugin._get_config_room_id(),
            "cache_count": len(events),
            "session_count": len(session_events),
            "session_started_at": started,
            "duration_seconds": int(time.time() - started) if started else 0,
            "latest": self._event_payload(latest) if latest else None,
            "counts": counts,
            "top_viewers": [{"name": name, "count": count} for name, count in top_viewers],
            "last_error": getattr(getattr(plugin, "_bili_live_client", None), "last_error", "") or plugin._get_bili_live_task_error(),
        }

    def _vts_summary(self) -> dict[str, Any]:
        plugin = self.plugin
        return {
            "connected": bool(getattr(plugin, "_connected", False)),
            "url": getattr(getattr(plugin, "vts", None), "url", ""),
            "auto_connect": bool(plugin.config.get("auto_connect", True)),
            "auto_discover": bool(plugin.config.get("auto_discover", True)),
        }

    def _subtitle_summary(self) -> dict[str, Any]:
        server = getattr(self.plugin, "_subtitle_server", None)
        return {
            "enabled": bool(self.plugin.config.get("subtitle_enabled", False)),
            "running": server is not None,
            "url": getattr(server, "url", "") if server else "",
        }

    def _mouth_sync_summary(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.plugin.config.get("mouth_sync_enabled", False)),
            "fps": self._int(self.plugin.config.get("mouth_sync_fps"), 30),
            "parameter": str(self.plugin.config.get("mouth_sync_open_parameter") or "ParamMouthOpenY"),
        }

    def _auto_reply_summary(self) -> dict[str, Any]:
        marks = list(getattr(self.plugin, "_bili_auto_reply_minute_marks", []))
        now = time.time()
        recent_marks = [item for item in marks if now - float(item) < 60]
        return {
            "enabled": bool(self.plugin.config.get("bili_live_auto_reply_enabled", False)),
            "mode": str(self.plugin.config.get("bili_live_auto_reply_mode") or "native"),
            "pending": len(getattr(self.plugin, "_bili_pending_reply_events", [])),
            "cooldown_seconds": self._float(self.plugin.config.get("bili_live_auto_reply_cooldown_seconds"), 12.0),
            "max_per_minute": self._int(self.plugin.config.get("bili_live_auto_reply_max_per_minute"), 6),
            "used_this_minute": len(recent_marks),
            "last_reply_at": float(getattr(self.plugin, "_bili_last_auto_reply_at", 0.0) or 0.0),
            "exempt_event_types": list(self.plugin._bili_auto_reply_priority_types()),
        }

    def _companion_summary(self, companion: Any | None, store: dict[str, Any]) -> dict[str, Any]:
        return {
            "available": companion is not None,
            "context_enabled": bool(self.plugin.config.get("private_companion_live_context_enabled", True)),
            "writeback_enabled": bool(self.plugin.config.get("private_companion_writeback_enabled", True)),
            "viewer_activity_enabled": bool(self.plugin.config.get("private_companion_viewer_activity_enabled", True)),
            "summary_count": len(store.get("summaries") if isinstance(store.get("summaries"), list) else []),
        }

    def _memory_summary(self, store: dict[str, Any], detailed: bool = False) -> dict[str, Any]:
        memory_items = store.get("memory_items") if isinstance(store.get("memory_items"), list) else []
        highlights = store.get("highlight_events") if isinstance(store.get("highlight_events"), list) else []
        open_threads = store.get("open_threads") if isinstance(store.get("open_threads"), list) else []
        summaries = store.get("summaries") if isinstance(store.get("summaries"), list) else []
        topics = store.get("topic_memory") if isinstance(store.get("topic_memory"), dict) else {}
        topic_rows = []
        for topic, item in topics.items():
            if not isinstance(item, dict):
                continue
            topic_rows.append(
                {
                    "topic": str(topic),
                    "count": self._int(item.get("count")),
                    "last_seen": self._float(item.get("last_seen")),
                    "samples": item.get("samples") if isinstance(item.get("samples"), list) else [],
                }
            )
        topic_rows.sort(key=lambda item: (item["count"], item["last_seen"]), reverse=True)
        payload = {
            "enabled": bool(self.plugin.config.get("live_memory_enabled", True)),
            "context_enabled": bool(self.plugin.config.get("live_memory_context_enabled", True)),
            "memory_count": len(memory_items),
            "highlight_count": len(highlights),
            "topic_count": len(topic_rows),
            "open_thread_count": len(open_threads),
            "summary_count": len(summaries),
            "topics": topic_rows[:12],
            "recent_items": memory_items[:8],
            "highlights": highlights[:8],
            "open_threads": open_threads[:8],
            "summaries": list(reversed(summaries[-5:])),
        }
        if detailed:
            payload["all_recent_items"] = memory_items[:30]
        return payload

    def _viewer_summary(self, store: dict[str, Any], limit: int = 20) -> dict[str, Any]:
        activity = store.get("viewer_activity") if isinstance(store.get("viewer_activity"), dict) else {}
        rows = []
        for key, item in activity.items():
            if not isinstance(item, dict):
                continue
            rows.append(
                {
                    "key": str(key),
                    "display_name": self._single_line(item.get("display_name") or item.get("live_username"), 40),
                    "live_username": self._single_line(item.get("live_username"), 40),
                    "user_id": self._single_line(item.get("user_id"), 40),
                    "total_events": self._int(item.get("total_events")),
                    "event_counts": item.get("event_counts") if isinstance(item.get("event_counts"), dict) else {},
                    "recent_danmaku": item.get("recent_danmaku") if isinstance(item.get("recent_danmaku"), list) else [],
                    "last_seen": self._float(item.get("last_seen")),
                }
            )
        rows.sort(key=lambda item: (item["total_events"], item["last_seen"]), reverse=True)
        observations = store.get("viewer_observations") if isinstance(store.get("viewer_observations"), dict) else {}
        return {
            "count": len(rows),
            "candidate_count": len(observations),
            "items": rows[:limit],
        }

    def _config_summary(self) -> dict[str, Any]:
        return self.config_manager.summary()

    def _event_payload(self, event: Any) -> dict[str, Any]:
        if event is None:
            return {}
        return {
            "type": str(getattr(event, "event_type", "") or ""),
            "username": self._single_line(getattr(event, "username", ""), 60),
            "content": self._single_line(getattr(event, "content", ""), 180),
            "display": self._single_line(event.display_text() if hasattr(event, "display_text") else "", 220),
            "ts": self._float(getattr(event, "ts", 0.0)),
        }

    @staticmethod
    def _single_line(value: Any, limit: int = 120) -> str:
        text = " ".join(str(value or "").strip().split())
        if limit > 0 and len(text) > limit:
            return text[:limit].rstrip() + "..."
        return text

    @staticmethod
    def _int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _ok(data: Any = None) -> dict[str, Any]:
        return {"success": True, "data": data, "ts": int(time.time())}

    @staticmethod
    def _error(message: str) -> dict[str, Any]:
        return {"success": False, "error": str(message), "ts": int(time.time())}
