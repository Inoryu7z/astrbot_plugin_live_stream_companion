# 更改记录

## 1.6.6

- 新增「本地音频播放」配置项 `bili_live_local_audio_playback_enabled`（默认关闭）：
  - 开启后，直播自动回应和截图解说主动说话的 TTS 音频通过本机声卡直接播放（winsound），不再依赖聊天平台播放 Record 组件。
  - 适用于 webchat 等不自动播放音频的平台。
  - 播放成功后从结果链中移除 Record 组件，避免冗余；播放失败时回退保留 Record 组件。
  - 仅 Windows 平台生效，仅播放链中第一个 Record 组件，异步播放不阻塞主流程。
  - 临时音频文件由 tts_plus 原有清理机制处理。

## 1.6.5

- 截图解说触发机制从「固定间隔」改为「概率 + 最大静默上限」：
  - 新增配置 `screenshot_narration_trigger_probability`（默认 0.3，即 30%）和 `screenshot_narration_max_silent_checks`（默认 5）。
  - 每次检查周期里以该概率触发截图解说；连续 N 次概率未命中则强制触发一次，避免长时间沉默。
  - `screenshot_narration_interval_seconds` 语义改为「检查间隔」（默认从 60 调整为 30 秒），不再是实际触发间隔。
  - `/screenshot_narration_status` 状态输出新增触发概率、最大静默次数和当前静默计数。
- 新增「主动说话」链路：截图解说生成后直接发声：
  - 新增配置 `screenshot_narration_auto_speak_enabled`（默认开启）。
  - 开启后，周期截图解说生成后会把第一条解说候选作为 bot 消息发到绑定会话，触发 OBS 字幕+口型+TTS，实现「无弹幕时 bot 主动评论画面」。
  - 受概率触发和 max_silent_checks 控制频率，不需要额外冷却。手动 `/screenshot_narration_test` 不会触发主动说话。
- 删除 `screenshot_narration_session_id` 配置项：
  - 直接复用 astrbot 框架配置的主模型/回退模型链，不单独绑定视觉会话。Provider 获取逻辑简化为：自动回应会话 → 全局默认。
- 两个 system prompt 默认值调整为 Inory 人设 v3.2 风格：
  - `bili_live_auto_reply_system_prompt`：写入人设性格（诚实 + 不分场合乱说话 + 自恋 + 破防）、念弹幕格式（ID说："内容"——回应）、弹幕为主画面为辅、15-60 字约束。
  - `screenshot_narration_system_prompt`：写入 Inory 风格的解说要求，称呼操作员用「你」不用「操作员」。
  - 注意：默认值只对新安装生效。已有配置文件需手动改或删除旧值让框架回填默认。

## 1.6.4

- 截图解说子模块支持「连续多帧截图」：
  - 新增配置 `screenshot_narration_burst_count`（默认 3 张）和 `screenshot_narration_burst_interval_seconds`（默认 1 秒），每次周期截图会连续截取 N 张一并发给视觉 LLM，让模型看到连续动作而非单帧静态画面，判断更精准。
  - LLM 提示词会根据帧数自动切换：多帧时提示"按时间顺序分析连续画面变化"，单帧时保持原有行为。
  - `/screenshot_narration_status` 状态输出新增连续截图张数、间隔和最近一次帧数。
  - 修复 `frame_count` 在截图文件清理后才计算的 bug。
- 弹幕自动回应现在会附带当前画面截图：
  - 新增配置 `screenshot_narration_attach_to_reply_enabled`（默认开启），开启后三条自动回应路径（direct / native framework / native dispatch）都会在调用 LLM 前截取一张当前画面一并发送，避免模型只读弹幕文本而不了解直播画面。
  - 截图失败会静默退化为纯文本回应，不阻断弹幕回复。direct 和 native framework 路径在 LLM 调用结束后立即清理临时文件；native dispatch 路径因事件异步处理，临时文件登记到 pending 列表由后续周期或停止时清理。

## 1.6.3

- 新增「直播画面截图解说」子模块（`screenshot_mixin.py`）：
  - 周期性截取当前显示器画面，下采样后发送给视觉 LLM，生成「场景描述 + 解说候选」并缓存到内存 deque。
  - 通过 `_build_screenshot_narration_context` 注入到直播自动回应的辅助上下文，让 Inory 能自然评价画面，对接人设里预留的「画面评价」接入点。
  - 视觉 LLM 复用 `bili_live_auto_reply_session_id` 的 Provider，可通过新增 `screenshot_narration_session_id` 单独绑定支持图片的模型；调用失败时静默丢弃这一帧。
  - 直播监听未运行时自动跳过周期截图，避免无人直播时白烧 token。
  - 新增配置项：`screenshot_narration_enabled`、`screenshot_narration_interval_seconds`、`screenshot_narration_initial_delay_seconds`、`screenshot_narration_monitor_index`、`screenshot_narration_max_image_width`、`screenshot_narration_jpeg_quality`、`screenshot_narration_session_id`、`screenshot_narration_system_prompt`、`screenshot_narration_candidate_count`、`screenshot_narration_max_history`、`screenshot_narration_context_enabled`、`screenshot_narration_context_max_age_seconds`。
  - 新增命令：`/screenshot_narration_status` 查看状态，`/screenshot_narration_test` 手动触发一次截图解说。
  - `requirements.txt` 新增 `mss`、`Pillow` 依赖。

## 1.6.2

- 修复普通 QQ 消息仍可能进入 OBS 打字机字幕的问题。
- 将 `subtitle_scope` 的默认值调整为 `bili_live`，默认只允许 B 站直播自动回应、直播 TTS、手动测试和拓展页预览推送字幕。
- 将字幕来源校验下沉到 `_push_subtitle()` 本身，并要求直播/手动/预览路径显式传入来源，避免外部插件或直接调用绕过回复 hook。
- 更新 README 和配置页 fallback 默认值，明确 `all` 是兼容旧行为，只有显式选择时才会让所有 Bot 回复进入打字机。

## 1.6.1

- 新增 `subtitle_scope` 配置，可选择 OBS 打字机字幕触发范围：
  - `bili_live`：默认安全模式，只推送 B 站直播自动回应、直播 TTS 字幕、手动测试和拓展页预览，普通 QQ 聊天不会显示到 OBS 字幕层。
  - `all`：兼容旧行为，所有 Bot 最终回复都会推送到字幕层。
- 将字幕来源校验下沉到 `_push_subtitle`，避免外部插件或直接调用绕过回复 hook，把普通 QQ 消息推到直播字幕。
- 梳理直播间自动回应体验。当前直播回复会注入本场连续上下文、直播记忆、观众活跃画像和陪伴插件关系网线索；这些线索能增强承接感，但也可能让模型过度熟人寒暄。若出现每次都像“好久不见”的口吻，可优先关闭 `private_companion_viewer_activity_context_enabled`、`private_companion_live_context_enabled` 或 `live_memory_context_enabled`。

## 1.6.0

- 整合近期围绕 B 站直播监听、自动回应、TTS 和打字机字幕的补丁。
- B 站 Web 后端新增 `history` 模式，可只使用历史弹幕轮询，避开 `getDanmuInfo -352` 风控时的 websocket 弹幕服务器信息请求。
- `builtin` 后端保留 websocket + 历史轮询兜底。
- 直播自动回应链路改为先发送中文可见回复，再后台生成和补发语音，避免 TTS 生成阻塞直播互动。
- TTS 朗读稿和可见字幕文本分离。默认 QQ 可见文本和打字机字幕保持中文直播回复；开启 `subtitle_use_tts_spoken_text` 后，打字机字幕显示实际送入 TTS 的朗读文本。
- 强制语音场景下，先发文字会跳过字幕 hook，只在语音补发/播放阶段推送一次打字机字幕，避免重复打字机。
- 自动回应默认可使用 Bot 自己的私聊会话。
- 补强直播观众身份边界提示，避免把直播昵称误判成私聊用户或群友。
- 直播 TTS 联动会标记来源，只让直播自动回应触发本机播放和直播 overlay，普通聊天语音不会串到直播字幕或本机播放。
