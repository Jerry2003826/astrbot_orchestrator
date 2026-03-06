# 配置说明

`astrbot_orchestrator_v5` 的配置由根目录的 [`_conf_schema.json`](../_conf_schema.json) 定义，并由 `AstrBot` 插件配置面板暴露给用户。

如果你希望快速启用一套安全、可用、适合日常开发的配置，推荐先从下面这个最小集合开始：

```json
{
  "llm_provider": "your_provider_id",
  "max_iterations": 10,
  "max_parallel_tasks": 3,
  "task_timeout": 120,
  "enable_dynamic_agents": true,
  "max_concurrent_agents": 5,
  "agent_timeout": 300,
  "force_subagents_for_complex_tasks": true,
  "enable_plugin_management": true,
  "enable_skill_creation": true,
  "enable_mcp_config": true,
  "enable_code_execution": true,
  "auto_fix_sandbox": true,
  "allow_local_fallback": false
}
```

## 配置分组

### 1. LLM 与主编排

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `llm_provider` | `string` / 无默认值 | 选择用于意图识别、任务分析、代码生成和总结的模型提供商 |
| `max_iterations` | `int` / `10` | 单次自主执行允许的最大步骤数，用于阻止循环型任务失控 |
| `max_parallel_tasks` | `int` / `3` | 主编排链路下并行执行任务的上限 |
| `task_timeout` | `int` / `120` | 单个任务的超时时间，单位为秒 |

### 2. 动态 SubAgent 编排

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `enable_dynamic_agents` | `bool` / `true` | 是否启用动态 `SubAgent` 协作 |
| `max_concurrent_agents` | `int` / `5` | 动态代理的最大并发数 |
| `agent_timeout` | `int` / `300` | 单个 `SubAgent` 任务的超时时间，单位为秒 |
| `auto_cleanup_agents` | `bool` / `true` | 任务完成后是否自动清理动态代理 |
| `use_llm_task_analyzer` | `bool` / `true` | 是否启用基于 LLM 的任务分析与计划生成 |
| `force_subagents_for_complex_tasks` | `bool` / `true` | 对复杂任务强制使用多代理编排 |
| `subagent_verbose_logs` | `bool` / `false` | 是否输出更详细的 `SubAgent` 执行日志 |
| `subagent_template_overrides` | `string` / `""` | 以 JSON 字符串形式覆盖默认 `SubAgent` 模板 |

### 3. 副作用能力开关

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `enable_plugin_management` | `bool` / `true` | 允许搜索、安装、卸载、更新插件 |
| `enable_skill_creation` | `bool` / `true` | 允许创建和编辑 `SKILL.md` |
| `enable_mcp_config` | `bool` / `true` | 允许配置和测试 MCP 服务 |
| `enable_code_execution` | `bool` / `true` | 允许执行命令和代码 |

这些能力都属于高风险副作用，应与宿主侧权限控制一起使用。

### 4. 执行环境与安全策略

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `auto_fix_sandbox` | `bool` / `true` | 允许在检测到沙盒环境问题时尝试自动修复 |
| `allow_local_fallback` | `bool` / `false` | 沙盒失败时是否允许回退到本地执行 |

其中 `allow_local_fallback` 默认关闭，这是一个非常重要的安全选择：

- 关闭时：`Shipyard` 沙盒不可用会直接失败，不会静默切到本地执行
- 开启时：可以提高任务可用性，但必须接受更高的本地执行风险

### 5. 可观测性与调试

| 配置项 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `show_thinking_process` | `bool` / `true` | 是否在回复中展示模型的思考与决策过程 |
| `debug_mode` | `bool` / `false` | 是否在控制台输出更详细的调试日志 |

## `subagent_template_overrides` 示例

该配置项用于覆写默认的动态代理模板。它是一个 JSON 字符串，而不是 YAML 或 Python 对象。

示例：

```json
{
  "code": {
    "name": "code_agent",
    "system_prompt": "你是资深代码工程师，负责输出完整、可运行的代码。",
    "public_description": "生成或修改代码实现的子代理",
    "tools": ["sandbox", "skill_gen"]
  },
  "research": {
    "name": "research_agent",
    "system_prompt": "你是信息分析专家，负责梳理需求、总结方案与风险。",
    "public_description": "分析需求和风险的子代理",
    "tools": []
  }
}
```

在配置面板中填写时，需要把它作为单行 JSON 字符串输入。

## 推荐起点

### 更偏开发体验

- `enable_dynamic_agents = true`
- `use_llm_task_analyzer = true`
- `auto_fix_sandbox = true`
- `show_thinking_process = true`
- `debug_mode = false`

### 更偏生产安全

- `force_subagents_for_complex_tasks = true`
- `allow_local_fallback = false`
- `show_thinking_process = false`
- `debug_mode = false`
- 对高风险能力继续交由宿主侧权限矩阵控制

## 排查建议

如果遇到以下问题，可以优先检查对应配置：

- `任务执行过早中止`
  检查 `max_iterations`、`task_timeout`、`agent_timeout`
- `复杂任务没有走 SubAgent`
  检查 `enable_dynamic_agents` 与 `force_subagents_for_complex_tasks`
- `执行环境异常`
  检查 `auto_fix_sandbox` 和宿主沙盒配置
- `沙盒失败后仍希望继续`
  明确评估是否要启用 `allow_local_fallback`
- `日志太多或太少`
  调整 `show_thinking_process`、`debug_mode`、`subagent_verbose_logs`

## 相关文档

- [README.md](../README.md)
- [docs/architecture.md](architecture.md)
- [docs/commands.md](commands.md)
- [SECURITY.md](../SECURITY.md)
