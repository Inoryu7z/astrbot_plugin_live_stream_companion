"""
直播画面截图解说子模块。

该 mixin 周期性截取当前显示器画面，发送给视觉 LLM 生成「场景描述 + 解说候选」，
缓存最近若干条结果，并通过辅助上下文注入回主链路，让 Inory 能在直播时自然评价画面。

依赖：
- mss：跨平台截屏（Windows/macOS/Linux X11）
- Pillow：图片下采样与 JPEG 编码

设计要点：
- 截图与 LLM 调用都在后台 asyncio 任务中执行，不阻塞主循环
- 截图先下采样到配置的最大宽度，再以 JPEG 保存到临时目录，避免 token 爆炸
- LLM 调用复用自动回应会话的 provider，调用失败时静默丢弃这一帧
- 解说结果只在内存 deque 中保留最近 N 条，不做持久化
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Optional

from astrbot.api import logger


class ScreenshotNarrationMixin:
    """周期截图 + 视觉 LLM 解说 + 主链路辅助上下文注入。"""

    # ------------------------------------------------------------------ #
    #  状态初始化（由 main.py 的 __init__ 调用）
    # ------------------------------------------------------------------ #

    def _screenshot_narration_state_init(self) -> None:
        """初始化截图解说相关的运行时状态。"""
        self._screenshot_narration_task: Optional[asyncio.Task] = None
        self._screenshot_narration_running = False
        self._screenshot_narration_in_flight = False
        self._screenshot_narration_last_attempt_at = 0.0
        history_size = max(
            2,
            self._safe_parse_int(
                self.config.get("screenshot_narration_max_history"), 6
            ),
        )
        self._screenshot_narration_history: deque[dict[str, Any]] = deque(
            maxlen=history_size
        )
        self._screenshot_narration_last_error: str = ""

    # ------------------------------------------------------------------ #
    #  生命周期
    # ------------------------------------------------------------------ #

    def _start_screenshot_narration_loop(self) -> None:
        """如果配置启用，启动后台周期截图解说任务。"""
        if not self.config.get("screenshot_narration_enabled", False):
            return
        if not self._is_bili_live_enabled():
            logger.info(
                "[截图解说] B站直播功能未启用，截图解说循环不启动（仍可手动触发）"
            )
            # 即使 B 站直播未启用，也允许手动触发，所以不直接 return 启动失败
        if self._screenshot_narration_task and not self._screenshot_narration_task.done():
            return
        self._screenshot_narration_running = True
        self._screenshot_narration_task = asyncio.create_task(
            self._screenshot_narration_loop()
        )
        logger.info("[截图解说] 后台周期截图解说任务已启动")

    async def _stop_screenshot_narration_loop(self) -> None:
        """停止后台截图解说任务。"""
        self._screenshot_narration_running = False
        task = self._screenshot_narration_task
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"[截图解说] 停止后台任务时出现异常: {e}")
        self._screenshot_narration_task = None

    # ------------------------------------------------------------------ #
    #  主循环
    # ------------------------------------------------------------------ #

    async def _screenshot_narration_loop(self) -> None:
        """周期截图并生成解说的主循环。"""
        try:
            # 启动时先等待一个间隔，避免和插件初始化挤在一起
            initial_delay = max(
                2.0,
                self._safe_parse_float(
                    self.config.get("screenshot_narration_initial_delay_seconds"), 8.0
                ),
            )
            await asyncio.sleep(initial_delay)

            while self._screenshot_narration_running:
                interval = max(
                    10.0,
                    self._safe_parse_float(
                        self.config.get("screenshot_narration_interval_seconds"), 60.0
                    ),
                )
                # 只在直播监听运行时才自动截图，避免无人直播时白烧 token
                live_running = self._is_bili_live_running() if callable(
                    getattr(self, "_is_bili_live_running", None)
                ) else True
                if live_running:
                    try:
                        await self._run_one_screenshot_narration_cycle(source="loop")
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(f"[截图解说] 周期任务失败: {e}")
                        self._screenshot_narration_last_error = str(e)
                else:
                    logger.debug("[截图解说] 直播监听未运行，跳过本轮自动截图")
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("[截图解说] 后台周期任务已取消")
            raise

    # ------------------------------------------------------------------ #
    #  单次截图解说流程
    # ------------------------------------------------------------------ #

    async def _run_one_screenshot_narration_cycle(self, *, source: str = "loop") -> Optional[dict[str, Any]]:
        """执行一次完整的截图->LLM解说->缓存流程，返回解说 dict。"""
        if self._screenshot_narration_in_flight:
            logger.debug("[截图解说] 上一帧仍在处理中，跳过本次触发")
            return None
        self._screenshot_narration_in_flight = True
        self._screenshot_narration_last_attempt_at = time.time()
        try:
            image_path = await asyncio.to_thread(self._capture_screenshot_to_file)
            if not image_path:
                self._screenshot_narration_last_error = "截屏失败或未捕获到画面"
                return None
            try:
                narration = await self._generate_screenshot_narration(image_path)
            finally:
                # 用完即删，避免临时目录膨胀
                try:
                    Path(image_path).unlink(missing_ok=True)
                except Exception:
                    pass
            if not narration:
                self._screenshot_narration_last_error = "LLM 未返回有效解说"
                return None
            narration["ts"] = time.time()
            narration["source"] = source
            self._screenshot_narration_history.append(narration)
            self._screenshot_narration_last_error = ""
            logger.info(
                "[截图解说] 已生成解说 source=%s scene=%s candidates=%d",
                source,
                (narration.get("scene_description") or "")[:60],
                len(narration.get("narration_candidates") or []),
            )
            return narration
        finally:
            self._screenshot_narration_in_flight = False

    # ------------------------------------------------------------------ #
    #  截屏
    # ------------------------------------------------------------------ #

    def _capture_screenshot_to_file(self) -> Optional[str]:
        """截取当前显示器，下采样并保存为 JPEG，返回文件路径。"""
        try:
            import mss  # type: ignore
            from PIL import Image  # type: ignore
        except ImportError as e:
            self._screenshot_narration_last_error = (
                f"缺少依赖 mss/Pillow：{e}。请在 requirements.txt 中添加并重启插件"
            )
            logger.warning(self._screenshot_narration_last_error)
            return None

        monitor_index = max(
            0,
            self._safe_parse_int(
                self.config.get("screenshot_narration_monitor_index"), 0
            ),
        )
        max_width = max(
            320,
            self._safe_parse_int(
                self.config.get("screenshot_narration_max_image_width"), 1280
            ),
        )
        jpeg_quality = max(
            20,
            min(
                95,
                self._safe_parse_int(
                    self.config.get("screenshot_narration_jpeg_quality"), 70
                ),
            ),
        )

        try:
            with mss.mss() as sct:
                monitors = sct.monitors
                # monitors[0] 通常是「整个虚拟桌面」，monitors[1:] 是各个物理显示器
                if monitor_index + 1 >= len(monitors):
                    logger.warning(
                        "[截图解说] 配置的显示器索引 %s 超出范围（共 %s 个显示器），回退到主显示器",
                        monitor_index,
                        max(0, len(monitors) - 1),
                    )
                    monitor = monitors[1] if len(monitors) > 1 else monitors[0]
                else:
                    monitor = monitors[monitor_index + 1]
                raw = sct.grab(monitor)
                # mss 返回的像素是 BGRA，转成 PIL Image
                img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        except Exception as e:
            self._screenshot_narration_last_error = f"截屏失败: {e}"
            logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
            return None

        # 下采样
        try:
            if img.width > max_width:
                new_height = max(1, int(img.height * (max_width / img.width)))
                img = img.resize((max_width, new_height), Image.LANCZOS)
        except Exception as e:
            logger.debug(f"[截图解说] 下采样失败，使用原图: {e}")

        # 保存为 JPEG
        out_dir = Path(self._screenshot_narration_temp_dir())
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"shot_{uuid.uuid4().hex}.jpg"
        try:
            img.convert("RGB").save(out_path, format="JPEG", quality=jpeg_quality)
        except Exception as e:
            self._screenshot_narration_last_error = f"截图保存失败: {e}"
            logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
            return None
        return str(out_path)

    def _screenshot_narration_temp_dir(self) -> str:
        """返回截图临时目录。优先放在插件数据目录下，便于排查。"""
        try:
            base = Path(self.config.get("_data_dir") or "") if isinstance(
                self.config, dict
            ) else Path("")
        except Exception:
            base = Path("")
        if not base or not str(base).strip():
            import tempfile

            base = Path(tempfile.gettempdir()) / "live_stream_companion_screenshots"
        else:
            base = Path(base) / "screenshots"
        return str(base)

    # ------------------------------------------------------------------ #
    #  视觉 LLM 调用
    # ------------------------------------------------------------------ #

    async def _generate_screenshot_narration(self, image_path: str) -> Optional[dict[str, Any]]:
        """调用视觉 LLM 生成场景描述 + 解说候选，返回解析后的 dict。"""
        provider = await self._get_screenshot_narration_provider()
        if provider is None:
            self._screenshot_narration_last_error = "未找到可用 LLM Provider"
            logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
            return None

        system_prompt = str(
            self.config.get("screenshot_narration_system_prompt")
            or self._screenshot_narration_default_system_prompt()
        )
        candidate_count = max(
            1,
            min(
                5,
                self._safe_parse_int(
                    self.config.get("screenshot_narration_candidate_count"), 3
                ),
            ),
        )
        prompt = (
            "请分析这张直播画面截图，严格按以下 JSON 格式输出，不要输出 JSON 以外的内容、不要包裹在 ``` 代码块里：\n"
            "{\n"
            '  "scene_description": "对画面内容的简短客观描述（20-50字），包括游戏/应用类型、可见关键元素、大致状态",\n'
            '  "narration_candidates": ["2-3条适合直播陪聊语气的简短解说候选，每条15-40字"]\n'
            "}\n\n"
            "要求：\n"
            "- 客观描述画面里能看到的元素，不要编造画面外的细节\n"
            f"- 解说候选给 {candidate_count} 条，自然口语化，像主播现场接话\n"
            "- 每条解说独立可用，不依赖前文，不要重复同一意思\n"
            "- 不要逐字读出 JSON 字段名，按 JSON 结构输出即可\n"
        )

        try:
            response = await provider.text_chat(
                prompt=prompt,
                system_prompt=system_prompt,
                image_urls=[image_path],
                persist=False,
            )
        except TypeError:
            # 老版本 provider 可能不支持 image_urls 关键字
            try:
                response = await provider.text_chat(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    persist=False,
                )
            except Exception as e:
                self._screenshot_narration_last_error = f"LLM 调用失败: {e}"
                logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
                return None
        except Exception as e:
            self._screenshot_narration_last_error = f"视觉 LLM 调用失败: {e}"
            logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
            return None

        text = self._extract_provider_text(response)
        if not text:
            self._screenshot_narration_last_error = "LLM 返回为空"
            return None
        return self._parse_screenshot_narration_response(text, candidate_count)

    async def _get_screenshot_narration_provider(self):
        """获取截图解说使用的 LLM Provider。"""
        # 优先用专门配置的会话
        dedicated_session = str(
            self.config.get("screenshot_narration_session_id") or ""
        ).strip()
        candidate_sessions: list[str] = []
        if dedicated_session:
            candidate_sessions.append(dedicated_session)
        # 回退到自动回应会话
        try:
            auto_session = await self._get_bili_reply_session()
            if auto_session and auto_session not in candidate_sessions:
                candidate_sessions.append(auto_session)
        except Exception:
            pass
        for session_id in candidate_sessions:
            try:
                provider = self.context.get_using_provider(session_id)
                if provider is not None:
                    return provider
            except Exception:
                continue
        # 最后回退到全局默认
        try:
            return self.context.get_using_provider()
        except Exception:
            return None

    def _screenshot_narration_default_system_prompt(self) -> str:
        return (
            "你是一个直播画面解说助手。根据用户提供的直播画面截图，"
            "客观描述画面里能看到的内容，并给出几条自然口语化的解说候选，"
            "供直播陪聊角色参考。不要编造画面外的细节。"
        )

    # ------------------------------------------------------------------ #
    #  解析 LLM 输出
    # ------------------------------------------------------------------ #

    def _parse_screenshot_narration_response(
        self, text: str, candidate_count: int
    ) -> Optional[dict[str, Any]]:
        """解析 LLM 的 JSON 输出，失败时降级为纯文本抽取。"""
        raw = str(text or "").strip()
        if not raw:
            return None

        # 抽取 JSON 块（容忍 ```json 包裹）
        json_text = raw
        fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.IGNORECASE | re.DOTALL)
        if fence:
            json_text = fence.group(1)
        else:
            # 找第一个 { 到最后一个 }
            first = raw.find("{")
            last = raw.rfind("}")
            if 0 <= first < last:
                json_text = raw[first : last + 1]

        try:
            data = json.loads(json_text)
            if isinstance(data, dict):
                scene = str(data.get("scene_description") or "").strip()
                candidates_raw = data.get("narration_candidates") or []
                if isinstance(candidates_raw, str):
                    candidates_raw = [candidates_raw]
                if not isinstance(candidates_raw, list):
                    candidates_raw = []
                candidates = [
                    str(item).strip()
                    for item in candidates_raw
                    if str(item or "").strip()
                ]
                candidates = candidates[:candidate_count]
                if scene or candidates:
                    return {
                        "scene_description": scene,
                        "narration_candidates": candidates,
                    }
        except Exception as e:
            logger.debug(f"[截图解说] JSON 解析失败，降级纯文本: {e}")

        # 降级：把整段文本当作 scene_description，候选为空
        scene = raw.replace("```", "").strip()
        if not scene:
            return None
        return {
            "scene_description": scene[:200],
            "narration_candidates": [],
        }

    # ------------------------------------------------------------------ #
    #  上下文注入
    # ------------------------------------------------------------------ #

    def _build_screenshot_narration_context(
        self, events: Optional[list[Any]] = None
    ) -> str:
        """生成注入给主链路的「当前直播画面」辅助上下文。"""
        if not self.config.get("screenshot_narration_context_enabled", True):
            return ""
        history = list(self._screenshot_narration_history)
        if not history:
            return ""

        max_age = max(
            0.0,
            self._safe_parse_float(
                self.config.get("screenshot_narration_context_max_age_seconds"), 180.0
            ),
        )
        now = time.time()
        recent = [
            item for item in history
            if max_age <= 0 or (now - float(item.get("ts") or 0)) <= max_age
        ]
        if not recent:
            return ""
        # 取最近一条作为「当前画面」，更早的作为「前情画面」简短带过
        latest = recent[-1]
        earlier = recent[:-1][-2:]  # 最多带 2 条前情

        lines: list[str] = []
        latest_age = max(0, int(now - float(latest.get("ts") or 0)))
        scene = str(latest.get("scene_description") or "").strip()
        candidates = [
            str(item).strip()
            for item in (latest.get("narration_candidates") or [])
            if str(item or "").strip()
        ]
        if not scene and not candidates:
            return ""
        if scene:
            lines.append(f"- 当前画面（{latest_age}秒前）：{scene}")
        if candidates:
            lines.append("- 解说候选（可任选一条改写或直接使用，不要逐字复读）：" + " / ".join(candidates))

        if earlier:
            prior_parts: list[str] = []
            for item in earlier:
                age = max(0, int(now - float(item.get("ts") or 0)))
                brief = str(item.get("scene_description") or "").strip()
                if brief:
                    prior_parts.append(f"{age}秒前：{brief}")
            if prior_parts:
                lines.append("- 前情画面：" + "；".join(prior_parts))

        return (
            "## 当前直播画面\n"
            "以下是刚截取到的直播间画面描述和解说候选，用于让回应能自然承接画面。"
            "可以基于画面自然评价或吐槽，但不要说自己看到了截图、不要描述画面外细节、"
            "不要逐字复读解说候选；如果没有把握，就只当作轻量背景。\n"
            + "\n".join(lines)
        )

    # ------------------------------------------------------------------ #
    #  手动触发与状态查询
    # ------------------------------------------------------------------ #

    async def _trigger_screenshot_narration_now(self) -> Optional[dict[str, Any]]:
        """手动触发一次截图解说，返回结果 dict。"""
        return await self._run_one_screenshot_narration_cycle(source="manual")

    def _screenshot_narration_status_text(self) -> str:
        """生成截图解说当前状态的可读文本，供命令回显。"""
        enabled = bool(self.config.get("screenshot_narration_enabled", False))
        running = bool(
            self._screenshot_narration_task
            and not self._screenshot_narration_task.done()
        )
        history = list(self._screenshot_narration_history)
        last_error = self._screenshot_narration_last_error or "无"
        latest = history[-1] if history else None
        if latest:
            latest_age = max(0, int(time.time() - float(latest.get("ts") or 0)))
            latest_scene = str(latest.get("scene_description") or "")[:60]
            latest_count = len(latest.get("narration_candidates") or [])
        else:
            latest_age = -1
            latest_scene = "暂无"
            latest_count = 0
        interval = self._safe_parse_float(
            self.config.get("screenshot_narration_interval_seconds"), 60.0
        )
        return (
            f"截图解说功能：{'已启用' if enabled else '未启用'}\n"
            f"后台循环：{'运行中' if running else '未运行'}\n"
            f"截图间隔：{interval:g} 秒\n"
            f"已缓存解说：{len(history)} 条\n"
            f"最近一次：{latest_age}秒前，场景={latest_scene}，候选={latest_count} 条\n"
            f"最近错误：{last_error}"
        )
