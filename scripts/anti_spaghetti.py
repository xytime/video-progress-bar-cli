#!/usr/bin/env python3
"""只读 Python 结构指标与有限的项目依赖规则检查。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Antigravity | 初始 AST 结构扫描 |
| 1.1.0 | 2026-09-23 | Codex | 修复扫描完整性、模块边界、参数和嵌套口径；明确退出码与覆盖范围 |
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import stat
import tokenize
from dataclasses import dataclass, field

MAX_FUNC_LINES = 60
MAX_CLASS_LINES = 400
MAX_FUNC_ARGS = 5
MAX_NESTING_DEPTH = 4
MAX_CLASS_METHODS = 16
PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXCLUDE_DIRS = {'.venv', 'venv', '__pycache__', 'build', 'dist', 'draft-code', 'scratch'}
SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
BLOCKS = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try)
BLOCKS += tuple(getattr(ast, name) for name in ('TryStar', 'Match') if hasattr(ast, name))


@dataclass
class CodeSmell:
    file_path: str
    line_no: int
    rule: str
    severity: str
    message: str
    suggestion: str


@dataclass
class FileMetrics:
    file_path: str
    total_lines: int = 0
    class_count: int = 0
    function_count: int = 0
    smells: list[CodeSmell] = field(default_factory=list)
    failure: str | None = None
    project_rules: bool = False


def project_relative(path: Path, root: Path) -> Path | None:
    """只在已知扫描器所属项目内启用规则，不以目标目录名猜项目。"""
    markers = ('src/video_processing/pipeline_manager.py', 'src/config/settings.py', 'pyproject.toml')
    if not all((root / marker).is_file() for marker in markers):
        return None
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def local_module_paths(node: ast.Import | ast.ImportFrom, source: Path, root: Path) -> set[Path]:
    """解析静态导入的本地候选，不导入/执行目标模块，不推断动态 import。"""
    if isinstance(node, ast.Import):
        names = [alias.name for alias in node.names]
        bases = [root, root / 'src']
    else:
        names = [node.module] if node.module else []
        names += ['.'.join(filter(None, (node.module, alias.name)))
                  for alias in node.names if alias.name != '*']
        if node.level:
            base = source.parent
            for _ in range(node.level - 1):
                base = base.parent
            if not base.is_relative_to(root):
                return set()
            bases = [base]
        else:
            bases = [root, root / 'src']
    candidates = set()
    for base in bases:
        for name in names:
            candidate = base.joinpath(*name.split('.'))
            for path in (candidate.with_suffix('.py'), candidate):
                if path.is_file() or path.is_dir():
                    resolved = path.resolve()
                    if resolved.is_relative_to(root):
                        candidates.add(resolved.relative_to(root))
    return candidates


def nesting_depth(root: ast.AST) -> int:
    """函数体为 0；elif 同级；try/except/finally、match/case 计一层。"""
    maximum = 0
    stack = [(root, 0)]
    while stack:
        node, depth = stack.pop()
        maximum = max(maximum, depth)
        for child in ast.iter_child_nodes(node):
            if isinstance(child, SCOPES):
                continue
            increment = int(isinstance(child, BLOCKS))
            # elif 与 if 的列偏移相同；else 内嵌 if 的列偏移不同。
            if (isinstance(node, ast.If) and isinstance(child, ast.If)
                    and child in node.orelse and child.col_offset == node.col_offset):
                increment = 0
            stack.append((child, depth + increment))
    return maximum


class ArchitectureAstVisitor(ast.NodeVisitor):
    """尺寸指标仅提示；项目边界规则仅针对可解析的本地静态导入。"""

    def __init__(self, file_path: str, source_lines: list[str], project_root: Path = PROJECT_ROOT):
        self.file_path = file_path
        self.source_lines = source_lines
        self.project_root = project_root.resolve()
        self.relative = project_relative(Path(file_path), self.project_root)
        self.smells: list[CodeSmell] = []
        self.class_count = 0
        self.function_count = 0
        self.scopes: list[ast.AST] = []

    def add(self, node, rule, severity, message, suggestion):
        self.smells.append(CodeSmell(self.file_path, node.lineno, rule, severity, message, suggestion))

    def visit_ClassDef(self, node):
        self.class_count += 1
        lines = node.end_lineno - node.lineno + 1
        methods = sum(isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) for item in node.body)
        if lines > MAX_CLASS_LINES:
            self.add(node, 'ANTI-GOD-CLASS', 'WARNING', f'类 `{node.name}` 为 {lines} 行',
                     '核对职责与变化原因；行数不构成强制拆分依据')
        if methods > MAX_CLASS_METHODS:
            self.add(node, 'SRP-BLOWUP', 'WARNING', f'类 `{node.name}` 有 {methods} 个方法',
                     '结合调用关系检查职责是否内聚')
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()

    def visit_FunctionDef(self, node):
        self.function_count += 1
        positional = node.args.posonlyargs + node.args.args
        args_count = len(positional) + len(node.args.kwonlyargs)
        decorators = [ast.unparse(item) for item in node.decorator_list]
        direct_method = self.scopes and isinstance(self.scopes[-1], ast.ClassDef)
        if (direct_method and 'staticmethod' not in decorators and positional
                and positional[0].arg in ('self', 'cls')):
            args_count -= 1
        lines = node.end_lineno - node.lineno + 1
        if lines > MAX_FUNC_LINES:
            self.add(node, 'COMPACT-FUNCTION', 'WARNING', f'函数 `{node.name}` 为 {lines} 行',
                     '确认是否存在可独立验证的职责；声明式代码可以保留')
        if args_count > MAX_FUNC_ARGS:
            self.add(node, 'PARAMETER-DTO', 'INFO', f'函数 `{node.name}` 参数多达 {args_count} 个',
                     '仅当参数共享语义和约束时考虑参数对象；*args/**kwargs 不计入具名参数')
        depth = nesting_depth(node)
        if depth > MAX_NESTING_DEPTH:
            self.add(node, 'EARLY-RETURN', 'WARNING', f'函数 `{node.name}` 嵌套深度为 {depth} 层',
                     '检查能否在保持副作用顺序的前提下简化控制流')
        self.scopes.append(node)
        self.generic_visit(node)
        self.scopes.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node):
        core_roots = (Path('src/video_processing/core'), Path('src/video_processing/db'), Path('src/config'))
        if self.relative is None or not any(self.relative.is_relative_to(p) for p in core_roots):
            return
        outer_roots = (Path('scripts'), Path('src/cli'), Path('src/web'))
        for candidate in sorted(local_module_paths(node, Path(self.file_path), self.project_root)):
            if any(candidate.is_relative_to(p) for p in outer_roots):
                self.add(node, 'DAG-REVERSE-IMPORT', 'ERROR', f'核心域反向依赖本地外层模块 `{candidate}`',
                         '按项目依赖约束调整边界；此检查不证明全图无环')
                break

    visit_ImportFrom = visit_Import


def inspect_file(file_path: Path, project_root: Path = PROJECT_ROOT) -> FileMetrics:
    result = FileMetrics(str(file_path))
    try:
        if not stat.S_ISREG(file_path.stat().st_mode):
            raise ValueError('目标不是普通文件')
        # 尊重 Python 的编码声明与 UTF-8 BOM。
        with tokenize.open(file_path) as stream:
            content = stream.read()
        result.total_lines = len(content.splitlines())
        tree = ast.parse(content, filename=str(file_path))
        visitor = ArchitectureAstVisitor(str(file_path), content.splitlines(), project_root)
        visitor.visit(tree)
    except (OSError, UnicodeError, SyntaxError, ValueError, RecursionError) as exc:
        result.failure = f'{type(exc).__name__}: {exc}'
        return result
    result.class_count = visitor.class_count
    result.function_count = visitor.function_count
    result.smells = visitor.smells
    result.project_rules = visitor.relative is not None
    return result


def collect_target_files(paths: list[str]) -> tuple[list[Path], list[str]]:
    """保留每个显式目标的错误；不静默吞掉目录遍历失败或空目录。"""
    targets: set[Path] = set()
    failures: list[str] = []
    for name in paths:
        path = Path(name).absolute()
        found = []
        try:
            mode = path.stat().st_mode
            if stat.S_ISREG(mode) and path.suffix == '.py':
                found = [path.resolve()]
            elif stat.S_ISDIR(mode):
                def onerror(exc):
                    failures.append(f'{path}: 目录遍历失败: {exc}')
                for base, dirs, files in os.walk(path, onerror=onerror, followlinks=False):
                    retained = []
                    for directory in dirs:
                        if directory.startswith('.') or directory in EXCLUDE_DIRS:
                            continue
                        child = Path(base) / directory
                        if child.is_symlink():
                            failures.append(f'{child}: 未遍历符号链接目录，请显式指定目标')
                        else:
                            retained.append(directory)
                    dirs[:] = retained
                    found.extend((Path(base) / item).resolve() for item in files if item.endswith('.py'))
            else:
                failures.append(f'{path}: 目标不是 Python 文件或目录')
        except (OSError, RuntimeError) as exc:
            failures.append(f'{path}: {exc}')
        if not found:
            failures.append(f'{path}: 未找到可扫描的 Python 文件')
        targets.update(found)
    return sorted(targets), failures


def print_report(metrics: list[FileMetrics], failures: list[str], check_mode: bool) -> int:
    failed = [item for item in metrics if item.failure]
    complete = [item for item in metrics if not item.failure]
    print(f'扫描成功文件: {len(complete)} | 失败文件: {len(failed)} | 目标/遍历错误: {len(failures)}')
    for failure in failures:
        print(f'[INCOMPLETE] {failure}')
    for item in metrics:
        mode = 'Video-precessing 静态依赖规则 + 通用指标' if item.project_rules else '通用指标'
        print(f'文件: {item.file_path} [{mode}]')
        if item.failure:
            print(f'  [INCOMPLETE] {item.failure}')
        for smell in item.smells:
            print(f'  L{smell.line_no} [{smell.severity}] {smell.rule}: {smell.message}')
            print(f'    {smell.suggestion}')
    smells = [smell for item in complete for smell in item.smells]
    print(f'命中规则: {len(smells)}；尺寸/参数/嵌套只作提示。')
    print('范围限制: 仅解析本地存在的静态模块路径；不分析动态导入、运行时路径修改、'
          '依赖图环路或行为等价；未做基线/增量比较。')
    print('口径: 函数体嵌套为 0，elif 同级，try/except/finally 和 match/case 各计一层；'
          '参数包含位置专用/关键字专用，排除直接方法 self/cls 和 *args/**kwargs。')
    if failures or failed or not complete:
        print('检查不完整，不能作为通过证据。')
        return 2
    if not smells:
        print('在已扫描范围内未命中所实现规则。')
    return int(check_mode and any(smell.severity == 'ERROR' for smell in smells))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0],
                                     epilog='退出码: 0=完整扫描且当前模式通过; 1=--check 规则违规; 2=输入/扫描不完整。')
    parser.add_argument('paths', nargs='*', default=['src/'], help='相对调用者目录；默认 src/')
    parser.add_argument('--check', action='store_true', help='仅确定性依赖违规阻断；输入失败始终退出 2')
    args = parser.parse_args(argv)
    targets, failures = collect_target_files(args.paths)
    print(f'调用目录: {Path.cwd()}')
    metrics = [inspect_file(path) for path in targets]
    return print_report(metrics, failures, args.check)


if __name__ == '__main__':
    raise SystemExit(main())
