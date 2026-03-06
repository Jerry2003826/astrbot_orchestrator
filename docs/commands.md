# 命令参考

`astrbot_orchestrator_v5` 的命令入口定义在 `main.py`，实际分发逻辑位于 `entrypoints/command_handlers.py`。

这份文档面向两类读者：

- `使用者`
  希望快速知道每条命令能做什么、怎么用
- `开发者`
  希望理解入口层如何被组织，以及哪些命令会触发高风险副作用

## 总览

| 命令 | 说明 | 典型场景 |
| --- | --- | --- |
| `/agent` | 综合智能体入口 | 自然语言任务、复杂编排、多步骤自动化 |
| `/plugin` | 插件管理 | 搜索市场、安装、卸载、更新插件 |
| `/skill` | Skill 管理 | 创建、编辑、删除、读取 `SKILL.md` |
| `/mcp` | MCP 管理 | 添加、删除、测试服务并查看工具 |
| `/exec` | 统一执行入口 | 执行命令、Python 代码、查看执行配置 |
| `/debug` | 自诊断入口 | 查看系统状态、近期错误、问题分析 |
| `/sandbox` | 底层沙盒接口 | 直接执行代码、管理文件、安装包、重启沙盒 |

## `/agent`

`/agent` 是最核心的自然语言入口。  
适合让系统自己判断：应该直接回答、调用工具、还是升级为多 `SubAgent` 协作。

### 适合的问题

- 帮我分析这个需求并生成实现方案
- 帮我搜索有没有合适的翻译插件
- 帮我写一个查询天气的 Skill
- 帮我配置一个联网搜索的 MCP
- 这段代码为什么报错，帮我分析一下

### 示例

```text
/agent 帮我分析一个支持多租户的聊天系统应该如何设计
/agent 帮我写一个查询天气的 Skill，并告诉我怎么接入
/agent 帮我检查当前执行环境为什么跑不起来
```

## `/plugin`

用于插件市场相关的操作。

### Plugin 子命令

- `/plugin search <关键词>`
- `/plugin install <url>`（管理员）
- `/plugin list`
- `/plugin remove <名称>`（管理员）
- `/plugin update <名称>`（管理员）
- `/plugin proxy`

### Plugin 示例

```text
/plugin search 翻译
/plugin install https://github.com/example/plugin-repo
/plugin list
```

## `/skill`

用于管理 AstrBot Skill。

### Skill 子命令

- `/skill list`（管理员）
- `/skill create <名称>`
- `/skill edit <名称>`
- `/skill delete <名称>`（管理员）
- `/skill read <名称>`（管理员）

### Skill 示例

```text
/skill list
/skill create weather_query
/skill read weather_query
```

## `/mcp`

用于管理 MCP 服务和工具。

### MCP 子命令

- `/mcp list`（管理员）
- `/mcp add <名称> <url>`（管理员）
- `/mcp remove <名称>`（管理员）
- `/mcp test <名称>`（管理员）
- `/mcp tools <名称>`（管理员）

### MCP 示例

```text
/mcp list
/mcp add search https://example.com/mcp
/mcp test search
```

## `/exec`

这是统一执行器入口，适合希望用当前配置执行命令或代码的场景。

### Exec 子命令

- `/exec <命令>`（管理员）
- `/exec local <命令>`（管理员）
- `/exec sandbox <命令>`（管理员）
- `/exec python <代码>`（管理员）
- `/exec config`（管理员）

### Exec 示例

```text
/exec python print("hello")
/exec local ls
/exec config
```

## `/debug`

用于查看状态、自诊断和问题分析，仅管理员可用。

### Debug 子命令

- `/debug status`（管理员）
- `/debug logs`（管理员）
- `/debug analyze <问题描述>`（管理员）

### Debug 示例

```text
/debug status
/debug logs
/debug analyze 为什么刚才的命令执行失败了
```

## `/sandbox`

这是更底层的沙盒接口，适合直接操作执行环境，仅管理员可用。

### Sandbox 子命令

- `/sandbox status`（管理员）
- `/sandbox exec <代码>`（管理员）
- `/sandbox bash <命令>`（管理员）
- `/sandbox files [路径]`（管理员）
- `/sandbox upload <路径> <内容>`（管理员）
- `/sandbox download <路径>`（管理员）
- `/sandbox install <包名>`（管理员）
- `/sandbox packages`（管理员）
- `/sandbox variables`（管理员）
- `/sandbox restart`（管理员）
- `/sandbox url <url> <路径>`（管理员）

### Sandbox 示例

```text
/sandbox status
/sandbox exec print("hello from sandbox")
/sandbox files /workspace
/sandbox install pandas
```

## 权限与风险说明

下列能力都属于高风险副作用：

- 插件安装与更新
- Skill 创建与删除
- MCP 配置变更
- 代码执行
- 文件写入与持久化

这些能力不应仅依赖模型判断，必须由宿主侧权限策略共同控制。

## 使用建议

如果你希望：

- `一句话完成复杂任务`
  优先使用 `/agent`
- `直接管理具体资源`
  使用 `/plugin`、`/skill`、`/mcp`
- `快速执行命令或代码`
  使用 `/exec`
- `深入操作执行环境`
  使用 `/sandbox`
- `分析问题而不是执行任务`
  使用 `/debug`

## 相关文档

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/configuration.md](configuration.md)
- [SECURITY.md](../SECURITY.md)
