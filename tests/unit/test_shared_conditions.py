"""共享条件求值器关键路径测试。"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, cast

import pytest

from astrbot_orchestrator_v5.shared.conditions import (
    SafeConditionError,
    _SafeEvaluator,
    evaluate_condition,
)

if TYPE_CHECKING:
    from _pytest.capture import CaptureFixture
    from _pytest.fixtures import FixtureRequest
    from _pytest.logging import LogCaptureFixture
    from _pytest.monkeypatch import MonkeyPatch
    from pytest_mock.plugin import MockerFixture

    _PYTEST_TYPE_IMPORTS = (
        CaptureFixture,
        FixtureRequest,
        LogCaptureFixture,
        MonkeyPatch,
        MockerFixture,
    )


def test_evaluate_condition_supports_boolean_and_builtin_calls() -> None:
    """条件求值器应支持布尔逻辑和白名单函数。"""

    variables = {"items": [1, 2, 3], "enabled": True}

    result = evaluate_condition("enabled and len(items) == 3", variables)

    assert result is True


def test_evaluate_condition_blocks_attribute_access() -> None:
    """条件求值器应拒绝属性访问这类危险表达式。"""

    with pytest.raises(SafeConditionError):
        evaluate_condition("().__class__", {})


def test_evaluate_condition_supports_arithmetic_membership_and_identity() -> None:
    """条件求值器应支持算术、成员判断和身份比较。"""

    variables = {
        "disabled": False,
        "count": 2,
        "tags": ["agent", "python"],
        "empty": None,
    }

    result = evaluate_condition(
        "not disabled and count + 1 == 3 and 'agent' in tags and empty is None",
        variables,
    )

    assert result is True


def test_evaluate_condition_supports_casts_and_not_in() -> None:
    """条件求值器应支持白名单类型转换与 not in。"""

    variables = {"status": "2", "blocked": ["9"], "value": 7}

    result = evaluate_condition(
        "int(status) == 2 and '1' not in blocked and str(value) == '7'",
        variables,
    )

    assert result is True


def test_evaluate_condition_rejects_invalid_syntax() -> None:
    """非法语法应被包装为 SafeConditionError。"""

    with pytest.raises(SafeConditionError, match="条件语法错误"):
        evaluate_condition("enabled and", {"enabled": True})


def test_evaluate_condition_rejects_unknown_variable() -> None:
    """未知变量名应直接拒绝。"""

    with pytest.raises(SafeConditionError, match="未知变量"):
        evaluate_condition("missing_value > 0", {})


def test_evaluate_condition_rejects_unsupported_function() -> None:
    """非白名单函数调用应被拒绝。"""

    with pytest.raises(SafeConditionError, match="不支持的函数"):
        evaluate_condition("sum(items) > 1", {"items": [1, 2]})


def test_evaluate_condition_rejects_keyword_arguments() -> None:
    """白名单函数也不应接受关键字参数。"""

    with pytest.raises(SafeConditionError, match="不支持关键字参数"):
        evaluate_condition("len(obj=[1, 2]) == 2", {})


def test_evaluate_condition_supports_literal_collections() -> None:
    """条件求值器应支持列表、元组、集合和字典字面量。"""

    variables = {
        "pair": (1, 2),
        "mapping": {"mode": "safe"},
    }

    result = evaluate_condition(
        "1 in [1, 2] and pair == (1, 2) and 2 in {1, 2} and mapping == {'mode': 'safe'}",
        variables,
    )

    assert result is True


def test_evaluate_condition_supports_numeric_operators() -> None:
    """条件求值器应支持常见数值运算和一元运算。"""

    variables = {"value": 2, "other": 3, "total": 5}

    result = evaluate_condition(
        "(-value) == -2 and (+other) == 3 and total - 1 == 4 and total * 2 == 10 "
        "and total / 5 == 1 and total % 2 == 1",
        variables,
    )

    assert result is True


def test_evaluate_condition_supports_comparison_variants() -> None:
    """条件求值器应支持多种比较运算符。"""

    variables = {"count": 2, "blocked": ["9"], "token": "abc"}

    result = evaluate_condition(
        "1 < count <= 3 and count != 4 and count > 0 and count >= 2 "
        "and '1' not in blocked and token is not None",
        variables,
    )

    assert result is True


def test_evaluate_condition_supports_or_short_circuit() -> None:
    """布尔 or 分支应被正常处理。"""

    result = evaluate_condition("False or True", {})

    assert result is True


def test_evaluate_condition_returns_false_when_comparison_chain_breaks() -> None:
    """比较链中任一条件不满足时应返回 False。"""

    result = evaluate_condition("1 < 0 < 2", {})

    assert result is False


def test_evaluate_condition_rejects_dict_unpack() -> None:
    """字典解包应被拒绝，避免扩大表达式能力。"""

    with pytest.raises(SafeConditionError, match="不支持字典解包"):
        evaluate_condition("{**payload} == {}", {"payload": {"key": "value"}})


def test_evaluate_condition_rejects_unsupported_unary_operator() -> None:
    """不在白名单中的一元运算应被拒绝。"""

    with pytest.raises(SafeConditionError, match="不支持的一元运算"):
        evaluate_condition("~value == 1", {"value": 1})


def test_evaluate_condition_rejects_non_name_call_target() -> None:
    """函数调用目标不是名字节点时应拒绝。"""

    with pytest.raises(SafeConditionError, match="只允许调用白名单函数"):
        evaluate_condition("str.upper('a') == 'A'", {})


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        (
            ast.Expression(
                body=ast.BoolOp(
                    op=cast(ast.boolop, ast.BitAnd()),
                    values=[ast.Constant(value=True), ast.Constant(value=False)],
                )
            ),
            "不支持的布尔运算",
        ),
        (
            ast.Expression(
                body=ast.BinOp(
                    left=ast.Constant(value=2),
                    op=ast.Pow(),
                    right=ast.Constant(value=3),
                )
            ),
            "不支持的二元运算",
        ),
        (
            ast.Expression(
                body=ast.Compare(
                    left=ast.Constant(value=1),
                    ops=[cast(ast.cmpop, ast.Add())],
                    comparators=[ast.Constant(value=2)],
                )
            ),
            "不支持的比较运算",
        ),
    ],
)
def test_safe_evaluator_rejects_remaining_manual_ast_operator_variants(
    expression: ast.Expression,
    message: str,
) -> None:
    """手工构造的非法 AST 运算节点也应被拒绝。"""

    evaluator = _SafeEvaluator({})

    with pytest.raises(SafeConditionError, match=message):
        evaluator.visit(expression)
