# 更改记录

## 1.6.1

- 新增 `subtitle_scope` 配置，可选择 OBS 打字机字幕触发范围：
  - `all`：保持旧行为，所有 Bot 最终回复都会推送到字幕层。
  - `bili_live`：只推送 B 站直播自动回应和直播 TTS 字幕，普通聊天不会显示到 OBS 字幕层。
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
