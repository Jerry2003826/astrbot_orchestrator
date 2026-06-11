# 配置说明

配置由根目录 [`_conf_schema.json`](../_conf_schema.json) 定义，经 `AstrBot` 插件配置面板暴露。

推荐起点（默认值即安全可用）：

```json
{
  "llm_provider": "",
  "max_iterations": 10,
  "task_timeout": 120,
  "enable_plugin_management": true,
  "enable_skill_creation": true,
  "enable_mcp_config": true,
  "enable_code_execution": true,
  "enable_self_debug": true,
  "enable_workflows": true,
  "enable_dynamic_agents": true,
  "auto_fix_sandbox": true,
  "allow_local_fallback": false
}
```

## 配置分组

### 1. LLM 与 /agent 执行

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `llm_provider` | `string` / `""` | `/agent` 使用的模型提供商；留空则跟随会话当前聊天模型 |
| `max_iterations` | `int` / `10` | 传给官方 `tool_loop_agent` 的 `max_steps`，防止工具循环失控 |
| `task_timeout` | `int` / `120` | 单个 `/agent` 任务的整体超时（秒） |

### 2. 能力开关（控制 FunctionTool 注册）

| 配置项 | 默认值 | 控制的工具组 |
| --- | --- | --- |
| `enable_plugin_management` | `true` | `plugin_search/list/install/uninstall/update` |
| `enable_skill_creation` | `true` | `skill_list/read/create/delete` |
| `enable_mcp_config` | `true` | `mcp_list/add/remove/test/list_tools` |
| `enable_code_execution` | `true` | `sandbox_exec_python/bash`、`sandbox_file_read/write`、`sandbox_install_packages` |
| `enable_self_debug` | `true` | `debug_status/debug_recent_errors` |
| `enable_workflows` | `true` | `workflow_list/workflow_run` |

说明：

- 关闭某组开关后，对应工具不会注册给宿主 Agent，同名命令入口也会提示能力未启用。
- 高危工具（安装、写文件、执行代码等）内置管理员门控，与开关独立生效。

### 3. 子代理

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `enable_dynamic_agents` | `bool` / `true` | 插件启动时把预设模板写入宿主 `subagent_orchestrator` 配置并热加载 |

子代理的并发、超时、路由等行为由宿主官方 `subagent_orchestrator` 配置控制（AstrBot WebUI → 配置），不再由本插件重复管理。也可随时用 `/agent sync` 手动同步模板。

### 4. 执行环境与安全策略

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `auto_fix_sandbox` | `bool` / `true` | 检测到沙盒环境问题时尝试自动修复（拉镜像、建网络） |
| `allow_local_fallback` | `bool` / `false` | Shipyard 沙盒不可用时是否回退本地执行 |

`allow_local_fallback` 默认关闭：

- 关闭时：沙盒不可用直接失败，不会静默切到本地执行。
- 开启时：可用性更高，但必须接受本地执行风险。

沙盒模式（local/shipyard）跟随宿主全局配置 `provider_settings.computer_use_runtime`，本插件不再单独配置。

### 5. 调试

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `debug_mode` | `bool` / `false` | 控制台输出详细执行日志 |

## 自 v4.0 移除的配置项

以下配置项随自研编排层一起删除，升级后无需迁移（残留值会被忽略）：

`enable_natural_language_control`、`natural_language_router_scope`、`max_parallel_tasks`、`max_concurrent_agents`、`agent_timeout`、`auto_cleanup_agents`、`use_llm_task_analyzer`、`force_subagents_for_complex_tasks`、`subagent_template_overrides`、`subagent_verbose_logs`、`show_thinking_process`

子代理模板如需定制，直接在 AstrBot WebUI 的 `subagent_orchestrator` 配置中修改（`/agent sync` 写入的条目带 `orchestrator_v5_` 前缀标识）。

## 排查建议

- `任务执行过早中止`：检查 `max_iterations`、`task_timeout`
- `LLM 不调用插件工具`：确认对应 `enable_*` 开关已开、触发者具备管理员身份（高危工具）
- `子代理不生效`：执行 `/agent sync`，再用 `/agent status` 查看官方 handoffs 状态
- `执行环境异常`：检查宿主 `provider_settings.computer_use_runtime` 与 `auto_fix_sandbox`
- `沙盒失败后仍希望继续`：明确评估是否启用 `allow_local_fallback`

## 相关文档

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/commands.md](commands.md)
- [SECURITY.md](../SECURITY.md)
