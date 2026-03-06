"""安全的条件表达式求值器。"""

from __future__ import annotations

import ast
from collections.abc import Mapping
from typing import Any, Callable


class SafeConditionError(ValueError):
    """表示条件表达式不被允许或无法安全求值。"""


class _SafeEvaluator(ast.NodeVisitor):
    """基于 AST 的白名单表达式求值器。"""

    _allowed_functions: dict[str, Callable[..., Any]] = {
        "len": len,
        "bool": bool,
        "int": int,
        "str": str,
    }

    def __init__(self, variables: Mapping[str, Any]) -> None:
        self._variables = dict(variables)

    def visit_Expression(self, node: ast.Expression) -> Any:
        """访问顶层表达式。"""

        return self.visit(node.body)

    def visit_Name(self, node: ast.Name) -> Any:
        """读取变量值。"""

        if node.id in self._variables:
            return self._variables[node.id]
        raise SafeConditionError(f"未知变量: {node.id}")

    def visit_Constant(self, node: ast.Constant) -> Any:
        """返回常量值。"""

        return node.value

    def visit_List(self, node: ast.List) -> list[Any]:
        """返回列表值。"""

        return [self.visit(item) for item in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple[Any, ...]:
        """返回元组值。"""

        return tuple(self.visit(item) for item in node.elts)

    def visit_Set(self, node: ast.Set) -> set[Any]:
        """返回集合值。"""

        return {self.visit(item) for item in node.elts}

    def visit_Dict(self, node: ast.Dict) -> dict[Any, Any]:
        """返回字典值。"""

        result: dict[Any, Any] = {}
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                raise SafeConditionError("不支持字典解包")
            result[self.visit(key)] = self.visit(value)
        return result

    def visit_BoolOp(self, node: ast.BoolOp) -> bool:
        """处理布尔运算。"""

        if isinstance(node.op, ast.And):
            return all(bool(self.visit(value)) for value in node.values)
        if isinstance(node.op, ast.Or):
            return any(bool(self.visit(value)) for value in node.values)
        raise SafeConditionError("不支持的布尔运算")

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        """处理一元运算。"""

        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not bool(operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return +operand
        raise SafeConditionError("不支持的一元运算")

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        """处理安全的数值和字符串运算。"""

        left = self.visit(node.left)
        right = self.visit(node.right)

        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Mod):
            return left % right
        raise SafeConditionError("不支持的二元运算")

    def visit_Compare(self, node: ast.Compare) -> bool:
        """处理比较表达式。"""

        left = self.visit(node.left)
        comparators = [self.visit(item) for item in node.comparators]
        operands = [left, *comparators]

        for index, operator in enumerate(node.ops):
            current = operands[index]
            nxt = operands[index + 1]
            if isinstance(operator, ast.Eq):
                ok = current == nxt
            elif isinstance(operator, ast.NotEq):
                ok = current != nxt
            elif isinstance(operator, ast.Lt):
                ok = current < nxt
            elif isinstance(operator, ast.LtE):
                ok = current <= nxt
            elif isinstance(operator, ast.Gt):
                ok = current > nxt
            elif isinstance(operator, ast.GtE):
                ok = current >= nxt
            elif isinstance(operator, ast.In):
                ok = current in nxt
            elif isinstance(operator, ast.NotIn):
                ok = current not in nxt
            elif isinstance(operator, ast.Is):
                ok = current is nxt
            elif isinstance(operator, ast.IsNot):
                ok = current is not nxt
            else:
                raise SafeConditionError("不支持的比较运算")

            if not ok:
                return False

        return True

    def visit_Call(self, node: ast.Call) -> Any:
        """调用白名单函数。"""

        if not isinstance(node.func, ast.Name):
            raise SafeConditionError("只允许调用白名单函数")
        if node.func.id not in self._allowed_functions:
            raise SafeConditionError(f"不支持的函数: {node.func.id}")
        if node.keywords:
            raise SafeConditionError("不支持关键字参数")

        arguments = [self.visit(argument) for argument in node.args]
        return self._allowed_functions[node.func.id](*arguments)

    def generic_visit(self, node: ast.AST) -> Any:
        """拒绝所有未明确允许的 AST 节点。"""

        raise SafeConditionError(f"不支持的表达式节点: {type(node).__name__}")


def evaluate_condition(expression: str, variables: Mapping[str, Any]) -> bool:
    """安全地求值条件表达式。

    Args:
        expression: 条件表达式文本。
        variables: 可供表达式读取的变量。

    Returns:
        条件表达式的布尔结果。

    Raises:
        SafeConditionError: 当表达式不安全或求值失败时。
    """

    try:
        parsed = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise SafeConditionError(f"条件语法错误: {exc.msg}") from exc

    evaluator = _SafeEvaluator(variables=variables)
    return bool(evaluator.visit(parsed))
