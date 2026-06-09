# 我会直播圈米养你

`astrbot_plugin_live_stream_companion` 是面向 AstrBot 的直播陪伴、弹幕互动与 Live2D 演出控制插件。它把 B 站直播间弹幕读取、LLM 自动回应、VTube Studio 表情动作、TTS 嘴型联动和 OBS 字幕层组织到同一条直播链路里，让 Bot 不只是会聊天，也能坐到直播间里看弹幕、接话、摆表情、动嘴和上字幕。

- 插件名：`astrbot_plugin_live_stream_companion`
- 中文名：`我会直播圈米养你`
- 版本：`1.4.4`
- 适配平台：`aiocqhttp`（OneBot v11）
- AstrBot 版本：`>=4.16,<5`
- 编码要求：UTF-8

## 功能简介

本插件不是单独的 VTube Studio 控制器，也不是单独的 B 站弹幕监听器。它更像 AstrBot 之上的“直播演出层”：把模型控制、直播间上下文、自动回应、字幕展示和语音嘴型放到同一个流程里，让 Bot 能以虚拟主播的方式参与直播互动。

核心目标是让 Bot 具备“能直播”的现场感。观众发弹幕时，Bot 可以读取最近直播间事件；需要回应时，插件会把弹幕摘要送回 AstrBot 原生回复链路；回复生成后，字幕、语音和 Live2D 表情动作可以一起接上，形成更完整的直播表现。

主要能力：

- VTube Studio 连接：自动发现 VTS 地址，完成插件 API 认证，并保持 Live2D 模型控制连接。
- 表情与热键控制：读取当前模型热键和表情，支持触发动作、切换表情、移动模型和注入 Live2D 参数。
- 自主 Live2D 标签：在回复前把可用表情说明注入给 LLM，回复后截获 `<l2d:...>` 标签并触发对应 VTS 热键。
- B 站直播弹幕：支持公开直播间 `web` 模式和开放平台 `open_live` 模式，缓存弹幕、礼物、SC、点赞、进场和上舰等事件。
- 直播间上下文注入：在 Bot 回复前注入最近弹幕，让 LLM 能自然理解“观众刚刚在说什么”。
- 弹幕自动回应：可把直播事件投递回 AstrBot 原生事件队列，继续使用当前人格、世界书、记忆、TTS 和分段等能力。
- OBS 字幕层：提供透明网页字幕 overlay，支持打字机效果、停留、淡出、描边、位置和最大长度控制。
- TTS 嘴型联动：等待最终语音组件生成后读取本地 `wav`，按音量包络驱动 VTS 嘴部参数。
- 调试与状态命令：可查看 VTS、直播监听、字幕和嘴型状态，方便直播前试播。

## 使用场景

- 让 AstrBot 驱动 Live2D 模型，按聊天内容自主摆表情或触发动作。
- 在 B 站直播间读取弹幕，让 Bot 能回答观众、感谢礼物或接住醒目留言。
- 用 OBS 浏览器源展示透明字幕层，让回复像直播字幕一样逐字出现。
- 配合 TTS 插件生成语音，再由本插件驱动 Live2D 嘴型。
- 用 AstrBot 原本的人格、世界书、记忆和工具链，给直播间提供连续的角色感。

## 安装方式

### 方式一：AstrBot 插件市场安装

在 AstrBot WebUI 的插件市场中搜索：

```text
astrbot_plugin_live_stream_companion
```

安装后重启 AstrBot，并进入插件配置页完成 VTube Studio、直播间和字幕相关配置。

### 方式二：手动安装

将插件目录放入 AstrBot 插件目录，并确保目录名为：

```text
astrbot_plugin_live_stream_companion
```

Windows 常见路径：

```text
C:\Users\你的用户名\.astrbot\data\plugins\astrbot_plugin_live_stream_companion
```

安装完成后重启 AstrBot。

## 初次使用

第一次启用时，建议按“先连 Live2D，再读弹幕，最后打开自动回应和字幕”的顺序配置：

1. 启动 VTube Studio。
2. 在 VTube Studio 中进入“设置 / 常规设置 / 插件 API”，打开 WebSocket API。默认端口通常是 `8001`。
3. 在 AstrBot 聊天中发送 `/vts_auth`。VTube Studio 弹出授权窗口后点击允许，Token 会自动保存。
4. 发送 `/vts_status` 确认连接状态，发送 `/vts_list` 查看当前模型热键和表情。
5. 如果要读取 B 站弹幕，先在配置里开启 `bilibili_enabled`，填写 `bilibili_room_id`，或临时发送 `/bili_live_start <房间号>`。
6. 发送 `/bili_live_recent` 检查是否能看到最近直播事件。
7. 如果要让 Bot 主动回应弹幕，在希望输出回复的聊天中发送 `/bili_live_bind_here`，再开启 `bili_live_auto_reply_enabled`。
8. 如果要上 OBS 字幕，开启 `subtitle_enabled`，在 OBS 中添加浏览器源并填写字幕地址。

公开直播间一般不需要 Cookie。如果遇到登录态限制、昵称隐藏或 `code=-352`，可以在 `bilibili_sessdata` 中填写浏览器 Cookie 里的 `SESSDATA`，也可以直接粘贴完整 Cookie。

## 拓展页

安装后可以在 AstrBot WebUI 的插件详情页打开 `直播面板`。面板会展示直播监听状态、VTube Studio/字幕/嘴型链路、自动回应限流、直播专用记忆、观众活跃度画像、最近直播事件和关键配置状态，也可以直接启动或停止 B 站直播监听。

页面文件位于：

```text
pages/直播面板/
```

后端接口前缀为：

```text
/astrbot_plugin_live_stream_companion/page
```

## 常用命令

VTube Studio：

```text
/vts_auth       认证 VTube Studio
/vts_status     查看连接状态和当前模型
/vts_discover   重新扫描并自动发现 VTS 地址
/vts_list       列出所有热键和表情
/vts_l2d_list   查看当前启用的自主 L2D 标签
```

B 站直播：

```text
/bili_live_start <房间号>  启动 B 站直播弹幕监听
/bili_live_stop           停止 B 站直播弹幕监听
/bili_live_status         查看弹幕监听状态
/bili_live_recent [数量]  查看最近缓存的直播事件
/bili_live_memory [数量]  查看直播专用记忆上下文
/bili_live_bind_here      将当前聊天绑定为直播弹幕自动回应输出会话
```

字幕与嘴型：

```text
/subtitle_status          查看字幕 overlay 状态
/subtitle_test [文本]     测试打字机字幕
/subtitle_clear           清空字幕 overlay
/mouth_sync_test 2        测试嘴型联动
```

## Live2D 表情编排

开启 `autonomous_l2d_enabled` 后，可以在 `l2d_hotkeys` 中配置 LLM 可选择的表情标签。

| 字段 | 说明 |
|---|---|
| `name` | 表情名称，例如 `开心`、`害羞`、`认真` |
| `tag` | 给 LLM 使用的标签名，例如 `happy`，模型会输出 `<l2d:happy>` |
| `hotkey_id` | VTube Studio 当前模型里的热键 ID 或名称，可用 `/vts_list` 查看 |
| `description` | 表情适用语气和场景，LLM 会据此自主选择 |
| `duration` | 持续时间，设为 `0` 表示只触发一次 |
| `release_after_duration` | 持续时间结束后是否再次触发同一热键，适合开关型表情 |

LLM 输出示例：

```text
谢谢老板的舰长，我今天就靠这口饭活了。
<l2d:happy>
```

观众最终只会看到正文；`<l2d:happy>` 会被插件移除，并在后台触发对应热键。如果本次不适合表情，模型可输出 `<l2d:none>`，插件会同样移除且不触发动作。

## 直播弹幕链路

直播功能由 `bilibili_enabled` 作为总开关。关闭时不会自动启动监听、不会手动启动直播连接、不会向 LLM 注入弹幕上下文，相关工具也不可用。

支持两种监听类型：

| 模式 | 说明 |
|---|---|
| `web` | 适合公开直播间，配置房间号即可。默认使用内置 `blivedm` 后端解析直播事件 |
| `open_live` | 适合 B 站直播开放平台，需填写开放平台密钥和主播身份码 |

可注入给 LLM 的事件类型：

| 事件类型 | 说明 |
|---|---|
| `danmaku` | 普通弹幕 |
| `gift` | 礼物 |
| `super_chat` | 醒目留言 |
| `buy_guard` | 大航海 |
| `enter_room` | 进入直播间 |
| `follow` | 关注直播间 |
| `like` | 点赞 |
| `live_start` | 开始直播 |
| `live_end` | 结束直播 |

自动回应默认走 `native` 模式，也就是把弹幕摘要投递回 AstrBot 原生事件队列。这样 Bot 仍然可以吃到当前人格、世界书、记忆、TTS、分段和其它插件链路。重启插件后需要重新发送一次 `/bili_live_bind_here`，因为原生事件模板只保存在当前进程内。

## 与“我会永远陪着你”联动

如果同一 AstrBot 中启用了 `astrbot_plugin_private_companion`，本插件会尝试读取它的关系网和群聊观察数据，把直播用户名按关系网姓名、别名、观察名进行候选匹配。匹配到后，会把该用户最近在 QQ 群里的发言作为直播互动线索注入给 LLM。

这样当某个熟悉的群友来到直播间发弹幕时，Bot 可以自然说出类似：

```text
你刚刚还在群里聊这个，怎么这么快就跑到直播间来了。
```

这条能力默认开启，但不会强依赖陪伴插件：读不到插件实例或没有匹配用户时会自动跳过。由于直播平台通常拿不到 QQ 号，匹配主要依靠名称和别名，提示词里会要求模型把它当作“候选线索”，不要把 QQ 号、关系网、匹配过程或内部备注说出来。默认也不会注入关系网里的身份备注；如确实需要，可开启 `private_companion_live_context_include_identity_note`。

直播回流能力也默认开启，会把直播间发生过的事写回陪伴插件：

- 重要互动写入关系记忆：默认只把礼物、醒目留言和上舰写入已识别用户的 `important_memories`，避免普通弹幕刷爆关系网。
- 直播观众候选登记：未匹配到关系网的直播用户名多次出现后，会创建一个 `bili_live_*` 候选关系节点，标记为直播观众，后续可以人工合并或修正。
- 直播影响当日状态：直播间高频互动、礼物或 SC 会给陪伴插件添加短时“直播余韵”状态，让 Bot 后续语气更像刚从直播里出来。
- 下播生成小结：停止直播监听或监听任务结束时，会把本场直播整理成一条 `live_stream_summary` 日记/直播小结，写入陪伴插件的日记列表。
- 关系网称呼风格：识别到熟人后，会把可用称呼、别名和互动边界注入给直播回复，让 Bot 能按熟悉程度称呼对方。
- 直播观众活跃画像：按直播用户名或已识别关系节点累计互动次数、事件类型、最近弹幕和重要互动，让 Bot 记得“谁常来、常聊什么”。

## 直播专用记忆

插件现在有一套单独面向直播场景的记忆上下文。它存放在陪伴插件数据里的 `live_stream_companion` 区域，但由本插件独立维护和注入，和 QQ 群关系网线索不是同一个提示块。

直播记忆会整理这些内容：

- 本场直播状态：直播时长、互动数量、活跃观众和事件分布。
- 可承接记忆：观众表达过的偏好、下次想看什么、刚才提到的未完问题。
- 最近高光：礼物、醒目留言、上舰等重要事件。
- 常见话题：从弹幕中提取并累计的高频话题词。
- 未完话题：带问号、下次、待会、继续、记得等语义的弹幕请求。
- 观众记忆：结合活跃度画像形成“谁常来、常聊什么”的轻量背景。

这些内容会在直播自动回应、直播相关 LLM 回复中以 `直播专用记忆上下文` 注入。模型会被要求只把它当作现场连续性的背景，不要说出内部字段、存储位置或分析过程。可以用 `/bili_live_memory [数量]` 查看当前整理出的直播记忆，也可以让 LLM 调用 `bili_live_memory_context` 工具读取。

## OBS 字幕层

开启 `subtitle_enabled` 后，插件会启动透明网页字幕层。默认地址：

```text
http://127.0.0.1:18081/
```

在 OBS 中添加“浏览器源”，URL 填上面的地址，背景会保持透明。字幕会默认清理 `<l2d:...>`、CQ 码和常见尖括号控制标签，避免控制指令出现在画面上。

常用配置：

| 配置项 | 说明 |
|---|---|
| `subtitle_enabled` | 字幕总开关 |
| `subtitle_port` | 本地字幕网页端口 |
| `subtitle_typing_speed_ms` | 每个字符出现的间隔 |
| `subtitle_hold_seconds` | 打完字后的停留时间 |
| `subtitle_max_length` | 字幕最大长度，避免遮挡 |
| `subtitle_font_size` | 字号 |
| `subtitle_text_color` | 字幕颜色 |
| `subtitle_stroke_color` | 描边颜色 |
| `subtitle_position` | `bottom` / `center` / `top` |

如果回复里包含语音组件，默认只显示语音后面的普通文本，适合“日语语音 + 中文字幕”的输出方式。

## TTS 嘴型联动

开启 `mouth_sync_enabled` 后，插件会在最终消息链中等待 TTS 语音组件生成完成，读取本地 `wav` 音频，并按音量包络驱动 VTube Studio 嘴部参数。这样语音、字幕和嘴型会以“语音文件已生成”为同步起点一起开始。

常用配置：

| 配置项 | 说明 |
|---|---|
| `mouth_sync_enabled` | 嘴型联动总开关 |
| `mouth_sync_open_parameter` | 嘴部开闭参数，默认 `ParamMouthOpenY` |
| `mouth_sync_form_parameter` | 嘴型变形参数，可填 `ParamMouthForm`，留空则不驱动 |
| `mouth_sync_fps` | 每秒推送参数次数，建议 `20~30` |
| `mouth_sync_gain` | 音量增益，越大嘴张得越明显 |
| `mouth_sync_smoothing` | 平滑程度，越大越柔和但响应越慢 |
| `mouth_sync_noise_gate` | 静音阈值，减少底噪导致的微张嘴 |
| `mouth_sync_form_strength` | 嘴型变形强度 |

当前嘴型联动优先读取本地 `wav` 文件。如果 TTS 插件生成的是远程 URL，或格式无法由 Python 标准库直接读取，嘴型联动会跳过；这种场景仍可使用 VTube Studio 自带麦克风或虚拟声卡方案。

## 配置概览

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `vts_host` | `localhost` | VTube Studio 所在主机地址 |
| `vts_port` | `8001` | VTube Studio API 端口 |
| `auto_discover` | `true` | 自动发现 VTS 地址 |
| `auto_connect` | `true` | 插件启动时自动认证 |
| `autonomous_l2d_enabled` | `true` | 启用自主 Live2D 标签机制 |
| `l2d_max_tags_per_reply` | `1` | 每次回复最多触发的 L2D 标签数量 |
| `l2d_hotkeys` | `[]` | Live2D 表情按键条目列表 |
| `bilibili_enabled` | `false` | B 站直播功能总开关 |
| `bilibili_type` | `web` | B 站直播监听类型，支持 `web` / `open_live` |
| `bilibili_room_id` | `0` | B 站直播房间号 |
| `bilibili_web_backend` | `blivedm` | Web 弹幕后端 |
| `bilibili_sessdata` | `""` | 可选 B 站完整 Cookie 或 SESSDATA |
| `bili_live_inject_enabled` | `true` | 向 LLM 注入最近直播弹幕 |
| `bili_live_inject_max_events` | `8` | 每次注入的最大直播事件数 |
| `bili_live_inject_event_types` | `["danmaku"]` | 注入给 LLM 的事件类型 |
| `bili_live_cache_size` | `80` | 内存中缓存的直播事件数量 |
| `private_companion_live_context_enabled` | `true` | 联动陪伴插件关系网和群聊观察，按直播用户名/别名识别观众 |
| `private_companion_live_context_max_age_seconds` | `900` | 只引用该时间范围内的最近群聊发言 |
| `private_companion_live_context_recent_limit` | `3` | 每个观众最多注入多少条群聊线索 |
| `private_companion_live_context_max_users` | `3` | 一次上下文最多识别多少个直播观众 |
| `private_companion_live_context_include_identity_note` | `false` | 是否额外注入关系网身份备注 |
| `private_companion_relationship_style_context_enabled` | `true` | 注入关系网称呼、别名和互动边界 |
| `private_companion_relationship_style_include_profile` | `false` | 是否注入关系节点画像 |
| `private_companion_relationship_style_include_memories` | `false` | 是否注入少量重要记忆 |
| `private_companion_writeback_enabled` | `true` | 将直播事件回流到陪伴插件 |
| `private_companion_viewer_activity_enabled` | `true` | 记录直播观众活跃度画像 |
| `private_companion_viewer_activity_context_enabled` | `true` | 将观众活跃画像注入直播回复 |
| `private_companion_writeback_memory_event_types` | `["gift","super_chat","buy_guard"]` | 写入关系重要记忆的直播事件类型 |
| `private_companion_auto_register_viewers` | `true` | 为多次出现的陌生直播用户名创建候选关系节点 |
| `private_companion_auto_register_min_events` | `2` | 自动登记候选关系需要的最少互动次数 |
| `private_companion_live_state_enabled` | `true` | 直播互动影响陪伴插件当日状态 |
| `private_companion_live_state_cooldown_seconds` | `300` | 状态余韵写入冷却时间 |
| `private_companion_live_state_duration_hours` | `2` | 直播状态余韵持续时间 |
| `private_companion_live_summary_enabled` | `true` | 下播时生成直播小结/日记 |
| `live_memory_enabled` | `true` | 启用直播专用记忆 |
| `live_memory_context_enabled` | `true` | 将直播专用记忆注入直播回复 |
| `live_memory_context_max_lines` | `12` | 每次注入的直播记忆上下文行数 |
| `live_memory_max_items` | `80` | 可承接直播记忆条目上限 |
| `live_memory_topic_enabled` | `true` | 记录直播常聊话题 |
| `live_memory_max_topics` | `80` | 直播话题词上限 |
| `live_memory_max_open_threads` | `20` | 未完话题上限 |
| `live_memory_max_highlights` | `40` | 直播高光事件上限 |
| `live_memory_highlight_event_types` | `["gift","super_chat","buy_guard"]` | 会进入直播高光记忆的事件类型 |
| `bili_live_log_events` | `true` | 将捕获到的直播事件写入 AstrBot 日志 |
| `bili_live_auto_reply_enabled` | `false` | 启用直播弹幕自动回应 |
| `bili_live_auto_reply_mode` | `native` | 自动回应模式，默认走 AstrBot 原生事件队列 |
| `bili_live_auto_reply_max_per_minute` | `6` | 普通弹幕每分钟最多自动回复数，`0` 表示不限流 |
| `bili_live_auto_reply_rate_limit_exempt_event_types` | `["gift","super_chat","buy_guard"]` | 不受每分钟限流影响的事件类型 |
| `mouth_sync_enabled` | `false` | 启用 TTS 语音嘴型联动 |
| `subtitle_enabled` | `false` | 启用打字机字幕 overlay |
| `subtitle_host` | `127.0.0.1` | 字幕服务监听地址 |
| `subtitle_port` | `18081` | 字幕服务端口 |
| `debug_mode` | `false` | 输出详细调试日志 |

`open_live` 模式还需要填写：

```text
bilibili_ACCESS_KEY_ID
bilibili_ACCESS_KEY_SECRET
bilibili_APP_ID
bilibili_ROOM_OWNER_AUTH_CODE
```

## LLM 工具

配置好模型后，LLM 可以按对话语义主动调用工具：

| 工具函数 | 说明 |
|---|---|
| `vts_get_hotkeys` | 获取当前模型所有热键列表 |
| `vts_trigger_hotkey` | 触发指定热键 |
| `vts_get_expressions` | 获取所有表情及当前激活状态 |
| `vts_set_expression` | 激活或停用指定表情 |
| `vts_move_model` | 移动、旋转或缩放模型 |
| `vts_inject_parameter` | 直接注入 Live2D 参数值 |
| `vts_get_parameters` | 获取所有可用 Live2D 参数 |
| `vts_model_info` | 获取当前模型基本信息 |
| `bili_live_recent_danmaku` | 读取最近直播事件 |
| `bili_live_memory_context` | 读取直播专用记忆上下文 |

示例：

```text
用户：弹幕刚刚在说什么？
Bot：调用 bili_live_recent_danmaku 读取最近事件，然后自然总结。

用户：谢谢刚刚送礼物的观众。
Bot：回应礼物，并通过 <l2d:happy> 触发开心表情。
```

## 开发者信息

- 开发者：`menglimi`
- 插件仓库：<https://github.com/menglimi/astrbot_plugin_live_stream_companion>
- 插件版本：`1.4.4`
- 主要文件：
  - `main.py`：插件主体、VTS 控制、直播事件注入、自动回应、字幕和嘴型联动。
  - `bilibili_live.py`：B 站直播 Web / Open Live 连接与事件标准化。
  - `vts_client.py`：VTube Studio WebSocket API 客户端封装。
  - `vts_discovery.py`：跨平台自动发现 VTube Studio 地址。
  - `subtitle_server.py`：透明字幕 overlay 服务。
  - `_conf_schema.json`：AstrBot 配置项。
  - `metadata.yaml`：插件元数据。

本插件面向直播陪伴体验。建议先以手动命令方式跑通 VTS 认证、弹幕监听和字幕显示，再逐步开启自动回应、TTS 嘴型和自主表情，避免第一次直播时把所有变量一起打开。

## License

MIT

## 致谢

本插件由原 `AstrBot VTube Studio Live2D 控制插件` 重构信息页与产品定位而来，保留并继续使用原有 VTube Studio 控制、B 站直播弹幕、字幕 overlay 和 TTS 嘴型联动能力。

原插件信息：

- 原中文名：`VTube Studio Live2D 控制`
- 原英文名：`astrbot_plugin_vtube_studio`
- 原作者：`EterUltimate`
- 原仓库：<https://github.com/EterUltimate/astrbot_plugin_vtube_studio>
- 原简介：为 AstrBot 提供 VTube Studio 连接支持，让 LLM 能够控制 Live2D 模型，包括触发热键、切换表情、注入参数、读取 B 站直播弹幕、显示字幕和驱动嘴型。

相关实现参考：

- `Raven95676/astrbot_plugin_bilibili_live`：参考并使用其二开 `blivedm` 后端思路，解析 B 站普通弹幕、礼物、醒目留言、点赞、进场和上舰等事件。
- `VTube Studio Plugin API`：提供 Live2D 模型热键、表情、参数注入和模型状态能力。
