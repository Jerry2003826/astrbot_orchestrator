# 命令参考

命令入口定义在 `main.py`（官方 `@filter.command` / `@filter.command_group` 装饰器），分发逻辑位于 `entrypoints/command_handlers.py`。

权限标注：

- **（管理员）** = 官方 `@filter.permission_type(ADMIN)` 装饰器控制，非管理员命令不会触发。
- 此外，对应能力的 FunctionTool 在默认聊天中被 LLM 调用时，工具内部还有一层 `event.is_admin()` 门控。

## 总览

| 命令 | 说明 |
| --- | --- |
| `/agent` | 官方 tool_loop_agent 驱动的综合任务入口 |
| `/plugin` | 插件市场搜索、安装、卸载、更新 |
| `/skill` | Skill 列表、创建、读取、删除 |
| `/mcp` | MCP 服务器管理 |
| `/exec` | 统一执行器（自动/本地/沙盒/Python） |
| `/sandbox` | 底层沙盒接口 |
| `/debug` | 系统状态与问题分析 |

## `/agent`

```text
/agent <任务描述>     全自主执行任务（受限流）
/agent status        查看官方子代理(handoffs)状态
/agent templates     查看预设子代理模板
/agent sync          同步模板到宿主 subagent 配置（管理员）
```

`/agent <任务>` 的执行方式：组装本插件工具 + 宿主已有工具 → `context.tool_loop_agent`（`max_steps` 取配置 `max_iterations`，整体超时取 `task_timeout`）→ 回答 + 代码产物摘要。

示例：

```text
/agent 帮我搜索有没有合适的翻译插件并装上
/agent 写一个脚本统计 /workspace 下的文件类型分布并执行
/agent 帮我配置一个联网搜索的 MCP
```

## `/plugin`

```text
/plugin search <关键词>   搜索插件市场
/plugin list             列出已安装插件
/plugin proxy            查看 GitHub 加速代理
/plugin install <url>    安装插件（管理员）
/plugin remove <名称>    卸载插件（管理员）
/plugin update <名称>    更新插件（管理员）
```

## `/skill`

```text
/skill create <名称>     创建 Skill 的引导
/skill list             列出全部 Skill（管理员）
/skill read <名称>       读取 SKILL.md（管理员）
/skill delete <名称>     删除 Skill（管理员）
```

## `/mcp`（全部管理员）

```text
/mcp list               列出 MCP 服务器
/mcp add <名称> <url>    添加服务器（仅公网 HTTPS）
/mcp remove <名称>       移除服务器
/mcp test <名称>         测试连通性
/mcp tools <名称>        列出服务器的工具
```

## `/exec`（全部管理员）

```text
/exec run <命令>         自动模式执行
/exec local <命令>       本地执行
/exec sandbox <命令>     沙盒执行
/exec python <代码>      执行 Python 代码
/exec config            查看执行模式配置
```

## `/sandbox`（全部管理员）

```text
/sandbox status                 健康检查
/sandbox exec <代码>            执行 Python
/sandbox bash <命令>            执行 Shell
/sandbox stream <代码>          流式执行
/sandbox files [路径]           列出文件
/sandbox upload <路径> <内容>   写入文件
/sandbox download <路径>        读取文件
/sandbox install <包名>         安装 Python 包
/sandbox packages               列出已安装包
/sandbox variables              查看会话变量
/sandbox restart                重启沙盒
/sandbox url <url> <路径>       从 URL 下载文件到沙盒
```

## `/debug`（全部管理员）

```text
/debug status            系统状态（Python/内存/插件/模型/MCP/最近错误）
/debug logs              最近错误记录
/debug analyze <描述>     LLM 辅助分析问题
```

## 默认聊天中的工具调用

开启对应配置开关后，下列 FunctionTool 会注册给宿主默认 Agent，普通聊天即可触发（高危操作要求触发者是管理员）：

| 工具组 | 工具 |
| --- | --- |
| 插件 | `plugin_search` `plugin_list` `plugin_install`* `plugin_uninstall`* `plugin_update`* |
| Skill | `skill_list` `skill_read` `skill_create`* `skill_delete`* |
| MCP | `mcp_list` `mcp_list_tools` `mcp_add`* `mcp_remove`* `mcp_test`* |
| 沙盒 | `sandbox_exec_python`* `sandbox_exec_bash`* `sandbox_file_read`* `sandbox_file_write`* `sandbox_install_packages`* |
| 调试 | `debug_status`* `debug_recent_errors`* |
| 工作流 | `workflow_list` `workflow_run`* |

`*` = 工具内置管理员门控。

## 相关文档

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/configuration.md](configuration.md)
- [SECURITY.md](../SECURITY.md)
