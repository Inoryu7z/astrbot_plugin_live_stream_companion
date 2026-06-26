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
        # 概率触发用：连续未触发的检查次数，达到上限后强制触发一次
        self._screenshot_narration_silent_checks = 0
        # 已生成但尚未确认消费/清理的截图文件路径，防止 asyncio.to_thread 被取消时泄漏
        self._screenshot_narration_pending_paths: list[str] = []
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
        # 兜底清理可能因取消而残留的截图文件
        self._screenshot_narration_cleanup_pending_paths()

    def _screenshot_narration_cleanup_pending_paths(self) -> None:
        """清理所有 pending 截图文件。"""
        paths = getattr(self, "_screenshot_narration_pending_paths", []) or []
        for path in list(paths):
            self._screenshot_narration_cleanup_path(path)

    # ------------------------------------------------------------------ #
    #  主循环
    # ------------------------------------------------------------------ #

    async def _screenshot_narration_loop(self) -> None:
        """周期截图并生成解说的主循环。

        采用「概率 + 最大静默上限」触发：每次检查周期里，以 trigger_probability 的概率
        触发截图解说；若连续 max_silent_checks 次未触发，则强制触发一次，避免长时间沉默。
        这样既不会像固定间隔那样僵硬，也不会完全随机导致可能很久不说话。
        """
        import random
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
                # 检查间隔（每次「摇骰子」的周期，不是实际触发间隔）
                interval = max(
                    10.0,
                    self._safe_parse_float(
                        self.config.get("screenshot_narration_interval_seconds"), 60.0
                    ),
                )
                probability = max(
                    0.0,
                    min(
                        1.0,
                        self._safe_parse_float(
                            self.config.get("screenshot_narration_trigger_probability"), 0.3
                        ),
                    ),
                )
                max_silent = max(
                    1,
                    self._safe_parse_int(
                        self.config.get("screenshot_narration_max_silent_checks"), 5
                    ),
                )
                # 只在直播监听运行时才自动截图，避免无人直播时白烧 token
                live_running = self._is_bili_live_running() if callable(
                    getattr(self, "_is_bili_live_running", None)
                ) else True
                if live_running:
                    # 判断是否触发：概率命中 或 已达到静默上限
                    should_trigger = (
                        self._screenshot_narration_silent_checks >= max_silent
                        or random.random() < probability
                    )
                    if should_trigger:
                        try:
                            await self._run_one_screenshot_narration_cycle(source="loop")
                            self._screenshot_narration_silent_checks = 0
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            logger.warning(f"[截图解说] 周期任务失败: {e}")
                            self._screenshot_narration_last_error = str(e)
                            # 失败也重置计数，避免失败后立即重试堆积
                            self._screenshot_narration_silent_checks = 0
                    else:
                        self._screenshot_narration_silent_checks += 1
                        logger.debug(
                            "[截图解说] 概率未命中，跳过本轮（silent=%d/%d, p=%.2f）",
                            self._screenshot_narration_silent_checks,
                            max_silent,
                            probability,
                        )
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
            self._screenshot_narration_last_error = "上一帧仍在处理中，跳过本次触发"
            logger.debug(self._screenshot_narration_last_error)
            return None
        self._screenshot_narration_in_flight = True
        self._screenshot_narration_last_attempt_at = time.time()
        captured_paths: list[str] = []
        try:
            # 连续截 N 张
            captured_paths = await self._capture_screenshot_burst()
            if not captured_paths:
                self._screenshot_narration_last_error = "截屏失败或未捕获到画面"
                return None
            # 在清理前先记录帧数，finally 块会清空 captured_paths
            frame_count = len(captured_paths)
            try:
                narration = await self._generate_screenshot_narration(captured_paths)
            finally:
                # 用完即删，避免临时目录膨胀
                for path in captured_paths:
                    self._screenshot_narration_cleanup_path(path)
                captured_paths = []
            if not narration:
                self._screenshot_narration_last_error = "LLM 未返回有效解说"
                return None
            # ts 用截图发起时刻，更接近画面真实时间
            narration["ts"] = self._screenshot_narration_last_attempt_at
            narration["source"] = source
            narration["frame_count"] = max(1, frame_count)
            self._screenshot_narration_history.append(narration)
            self._screenshot_narration_last_error = ""
            logger.info(
                "[截图解说] 已生成解说 source=%s scene=%s candidates=%d",
                source,
                (narration.get("scene_description") or "")[:60],
                len(narration.get("narration_candidates") or []),
            )
            # 主动说话：把解说候选作为 bot 消息发到绑定会话
            if source == "loop" and self.config.get(
                "screenshot_narration_auto_speak_enabled", True
            ):
                try:
                    await self._speak_screenshot_narration(narration)
                except Exception as e:
                    logger.warning(f"[截图解说] 主动说话失败: {e}")
            return narration
        except asyncio.CancelledError:
            # 被取消时兜底清理已生成的截图文件
            for path in captured_paths:
                self._screenshot_narration_cleanup_path(path)
            raise
        finally:
            self._screenshot_narration_in_flight = False

    async def _speak_screenshot_narration(self, narration: dict[str, Any]) -> None:
        """把截图解说候选作为 bot 消息发到绑定会话，触发 OBS 字幕+口型+TTS。

        只在周期触发（source=loop）时调用，手动触发不自动说话。
        """
        candidates = [
            str(item).strip()
            for item in (narration.get("narration_candidates") or [])
            if str(item or "").strip()
        ]
        if not candidates:
            return
        session_id = await self._get_bili_reply_session()
        if not session_id:
            logger.debug("[截图解说] 未绑定自动回应会话，主动说话跳过")
            return
        # 取第一条候选作为主动说话内容（LLM 已按 Inory 风格生成）
        speak_text = candidates[0]
        try:
            from astrbot.api.message_components import Plain
            from astrbot.api.event import MessageChain
        except ImportError:
            return
        force_voice = bool(self.config.get("bili_live_auto_reply_force_full_tts", True))
        chain = await self._decorate_bili_live_reply_chain(
            session_id,
            [Plain(speak_text)],
            force_voice=False,
            skip_subtitle=force_voice,
        )
        chain = self._strip_tts_blocks_from_plain_chain(chain)
        chain = self._ensure_visible_text_after_voice(chain, speak_text)
        await self.context.send_message(session_id, MessageChain(chain))
        if not force_voice:
            await self._push_subtitle(speak_text, source="bili_live")
        if force_voice:
            asyncio.create_task(self._send_bili_live_tts_followup(session_id, speak_text))
        logger.info(f"[截图解说] 主动说话 -> {session_id}: {speak_text}")

    def _screenshot_narration_cleanup_path(self, path: str) -> None:
        """删除指定截图文件并从 pending 列表移除。"""
        try:
            Path(path).unlink(missing_ok=True)
        except Exception:
            pass
        try:
            if path in self._screenshot_narration_pending_paths:
                self._screenshot_narration_pending_paths.remove(path)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    #  截屏
    # ------------------------------------------------------------------ #

    async def _capture_screenshot_burst(self) -> list[str]:
        """连续截取 N 张画面（默认 3 张，间隔默认 1 秒），返回文件路径列表。

        用于让视觉 LLM 看到一段连续画面，更精准判断直播当前在做什么。
        单张截图失败不会中断整组，只要至少有一张成功就返回非空列表。
        """
        count = max(
            1,
            min(
                10,
                self._safe_parse_int(
                    self.config.get("screenshot_narration_burst_count"), 3
                ),
            ),
        )
        interval = max(
            0.0,
            min(
                30.0,
                self._safe_parse_float(
                    self.config.get("screenshot_narration_burst_interval_seconds"), 1.0
                ),
            ),
        )
        paths: list[str] = []
        for i in range(count):
            try:
                path = await asyncio.to_thread(self._capture_screenshot_to_file)
            except asyncio.CancelledError:
                # 被取消时清理已捕获的图片
                for p in paths:
                    self._screenshot_narration_cleanup_path(p)
                raise
            except Exception as e:
                logger.debug(f"[截图解说] 第 {i + 1}/{count} 张截图失败: {e}")
                path = None
            if path:
                paths.append(path)
            # 最后一张不需要等待
            if i < count - 1 and interval > 0:
                await asyncio.sleep(interval)
        return paths

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

        # Pillow 10+ 用 Image.Resampling.LANCZOS，老版本用 Image.LANCZOS
        try:
            resample = Image.Resampling.LANCZOS  # type: ignore[attr-defined]
        except AttributeError:
            resample = Image.LANCZOS  # type: ignore[attr-defined]

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
                img = img.resize((max_width, new_height), resample)
        except Exception as e:
            logger.debug(f"[截图解说] 下采样失败，使用原图: {e}")

        # 保存为 JPEG（mkdir 也包进异常保护，避免目录创建失败让错误信息不友好）
        try:
            out_dir = Path(self._screenshot_narration_temp_dir())
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"shot_{uuid.uuid4().hex}.jpg"
            img.convert("RGB").save(out_path, format="JPEG", quality=jpeg_quality)
        except Exception as e:
            self._screenshot_narration_last_error = f"截图保存失败: {e}"
            logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
            return None
        # 登记到 pending 列表，防止 asyncio.to_thread 被取消时泄漏文件
        try:
            self._screenshot_narration_pending_paths.append(str(out_path))
        except AttributeError:
            self._screenshot_narration_pending_paths = [str(out_path)]
        return str(out_path)

    def _screenshot_narration_temp_dir(self) -> str:
        """返回截图临时目录。优先放在插件数据目录下，便于排查。"""
        data_dir = ""
        try:
            if isinstance(self.config, dict):
                data_dir = str(self.config.get("_data_dir") or "").strip()
        except Exception:
            data_dir = ""
        if data_dir:
            return str(Path(data_dir) / "screenshots")
        import tempfile

        return str(Path(tempfile.gettempdir()) / "live_stream_companion_screenshots")

    # ------------------------------------------------------------------ #
    #  视觉 LLM 调用
    # ------------------------------------------------------------------ #

    async def _generate_screenshot_narration(self, image_paths: list[str]) -> Optional[dict[str, Any]]:
        """调用视觉 LLM 生成场景描述 + 解说候选，返回解析后的 dict。

        image_paths 为按时间顺序的连续截图路径列表（1-10 张），LLM 可借此理解
        当前直播画面正在发生的连续动作，而不仅是一帧静态画面。
        """
        if not image_paths:
            return None
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
        frame_count = len(image_paths)
        if frame_count > 1:
            prompt = (
                f"请分析这组连续的直播画面截图（共 {frame_count} 张，按时间顺序排列），"
                "严格按以下 JSON 格式输出，不要输出 JSON 以外的内容、不要包裹在 ``` 代码块里：\n"
                "{\n"
                '  "scene_description": "对画面内容的简短客观描述（20-50字），包括游戏/应用类型、可见关键元素、大致状态；可结合多帧判断正在发生的动作",\n'
                '  "narration_candidates": ["2-3条适合直播陪聊语气的简短解说候选，每条15-40字"]\n'
                "}\n\n"
                "要求：\n"
                "- 这是一组连续截图，按顺序反映了几秒内的画面变化，请结合多帧判断现在到底在做什么\n"
                "- 客观描述画面里能看到的元素，不要编造画面外的细节\n"
                f"- 解说候选给 {candidate_count} 条，自然口语化，像主播现场接话\n"
                "- 每条解说独立可用，不依赖前文，不要重复同一意思\n"
                "- 不要逐字读出 JSON 字段名，按 JSON 结构输出即可\n"
            )
        else:
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
                image_urls=image_paths,
                persist=False,
            )
        except TypeError as e:
            # provider.text_chat 不接受 image_urls 关键字时降级为纯文本调用
            # 只在参数签名确实不支持时降级，避免掩盖 provider 内部真实 TypeError
            import inspect
            sig = inspect.signature(provider.text_chat)
            params = sig.parameters
            if "image_urls" in params or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
            ):
                # 签名支持却仍抛 TypeError，说明是 provider 内部 bug，不降级
                self._screenshot_narration_last_error = f"视觉 LLM 调用失败: {e}"
                logger.warning(f"[截图解说] {self._screenshot_narration_last_error}")
                return None
            logger.warning(
                "[截图解说] 当前 Provider 不支持 image_urls 参数，降级为纯文本调用（将丧失视觉能力）: %s",
                e,
            )
            try:
                response = await provider.text_chat(
                    prompt=prompt,
                    system_prompt=system_prompt,
                    persist=False,
                )
            except Exception as e2:
                self._screenshot_narration_last_error = f"LLM 调用失败: {e2}"
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
        """获取截图解说使用的 LLM Provider。

        直接复用 astrbot 框架配置的主模型/回退模型链，不单独绑定视觉会话。
        优先用自动回应会话的 provider（和弹幕回应同源），最后回退到全局默认。
        """
        candidate_sessions: list[str] = []
        # 优先用自动回应会话（和弹幕回应共用同一 provider）
        try:
            auto_session = await self._get_bili_reply_session()
            if auto_session:
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
            "你是 Inory，正在直播中的虚拟主播助手。根据提供的直播画面截图（可能是一组连续画面），"
            "给出场景描述和解说候选。\n\n"
            "性格：诚实、不分场合乱说话、偶尔自恋、被戳中会破防。\n\n"
            "要求：\n"
            "- 客观描述画面里能看到的元素，不要编造画面外的细节\n"
            "- 解说候选自然口语化，像主播现场接话\n"
            "- 可以用「你」称呼操作员（B站 ID「梦书桦」），但不要用「操作员」这个词\n"
            "- 每条解说独立可用，不依赖前文"
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

        # 候选 JSON 文本片段，按优先级尝试
        candidates_text: list[str] = []
        # 1. ```json ... ``` 代码块（贪心匹配，支持嵌套对象）
        for fence in re.finditer(
            r"```(?:json)?\s*(\{.*\})\s*```", raw, re.IGNORECASE | re.DOTALL
        ):
            candidates_text.append(fence.group(1))
        # 2. 首尾大括号之间的内容
        first = raw.find("{")
        last = raw.rfind("}")
        if 0 <= first < last:
            candidates_text.append(raw[first : last + 1])
        # 3. 原文
        candidates_text.append(raw)

        for json_text in candidates_text:
            try:
                data = json.loads(json_text)
            except Exception:
                continue
            if isinstance(data, dict):
                scene = str(data.get("scene_description") or "").strip()
                candidates_raw = data.get("narration_candidates") or []
                if isinstance(candidates_raw, str):
                    candidates_raw = [candidates_raw]
                if not isinstance(candidates_raw, list):
                    candidates_raw = []
                cand = [
                    str(item).strip()
                    for item in candidates_raw
                    if str(item or "").strip()
                ]
                cand = cand[:candidate_count]
                if scene or cand:
                    return {
                        "scene_description": scene,
                        "narration_candidates": cand,
                    }

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
    #  弹幕回应时附带截图
    # ------------------------------------------------------------------ #

    async def _capture_screenshot_for_reply(self) -> Optional[str]:
        """为弹幕自动回应截取一张当前画面，返回文件路径（失败/未启用返回 None）。

        与周期截图解说的 burst 不同，这里只截一张，优先保证回应速度。
        截图失败不会阻断弹幕回应，只是退化为纯文本。
        """
        if not self.config.get("screenshot_narration_attach_to_reply_enabled", True):
            return None
        if not self.config.get("screenshot_narration_enabled", False):
            # 截图解说总开关关闭时不截图，避免用户只想要弹幕附图却忘了开总开关时静默失败
            return None
        try:
            path = await asyncio.to_thread(self._capture_screenshot_to_file)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"[截图解说] 弹幕回应截图失败: {e}")
            return None
        return path

    def _screenshot_reply_prompt_hint(self, has_screenshot: bool) -> str:
        """返回给弹幕回应 prompt 的截图附注文本。"""
        if not has_screenshot:
            return ""
        return (
            "\n\n[附件包含一张当前直播画面截图，可参考画面内容更精准地回应弹幕。"
            "不要说自己看到了截图或描述截图过程，自然地把画面作为背景信息即可。]"
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
        probability = self._safe_parse_float(
            self.config.get("screenshot_narration_trigger_probability"), 0.3
        )
        max_silent = self._safe_parse_int(
            self.config.get("screenshot_narration_max_silent_checks"), 5
        )
        burst_count = self._safe_parse_int(
            self.config.get("screenshot_narration_burst_count"), 3
        )
        burst_interval = self._safe_parse_float(
            self.config.get("screenshot_narration_burst_interval_seconds"), 1.0
        )
        latest_frames = int(latest.get("frame_count", 1)) if latest else 0
        silent = getattr(self, "_screenshot_narration_silent_checks", 0)
        return (
            f"截图解说功能：{'已启用' if enabled else '未启用'}\n"
            f"后台循环：{'运行中' if running else '未运行'}\n"
            f"检查间隔：{interval:g} 秒，触发概率：{probability:g}，最大静默：{max_silent} 次\n"
            f"当前静默计数：{silent}/{max_silent}\n"
            f"连续截图：{burst_count} 张，间隔 {burst_interval:g} 秒\n"
            f"已缓存解说：{len(history)} 条\n"
            f"最近一次：{latest_age}秒前，帧数={latest_frames}，场景={latest_scene}，候选={latest_count} 条\n"
            f"最近错误：{last_error}"
        )
