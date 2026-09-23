"""扫描完整性、结构口径、本地依赖边界及 Shell 入口回归。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-09-23 | Antigravity | 初始扫描测试 |
| 1.1.0 | 2026-09-23 | Codex | 增加错误退出、参数/控制流边界、导入配对及跨项目真实命令测试 |
"""
import ast
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import anti_spaghetti as scanner


@pytest.fixture
def project(tmp_path):
    root = tmp_path / 'video project'
    for relative in ('src/video_processing/pipeline_manager.py', 'src/config/settings.py',
                     'pyproject.toml', 'scripts/uploader.py', 'src/cli/main.py', 'src/web/app.py'):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('')
    return root


def scan(tmp_path, code, project_root=None, relative='source.py'):
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code)
    return scanner.inspect_file(path, project_root or scanner.PROJECT_ROOT)


def rules(metric):
    assert metric.failure is None
    return {item.rule for item in metric.smells}


@pytest.mark.parametrize('code', ['def add(a,b): return a+b\n', 'x = 1\n'])
def test_clean_code(tmp_path, code):
    assert rules(scan(tmp_path, code)) == set()


@pytest.mark.parametrize('signature,expected', [
    ('a,b,c,d,e', False), ('a,b,c,d,e,f', True),
    ('a,b,c,d,e,/', False), ('a,b,c,d,e,f,/', True),
    ('*,a,b,c,d,e', False), ('*,a,b,c,d,e,f', True),
    ('a,b,/,c,*,d,e,f', True), ('a,b,c,d,e,*args,**kwargs', False),
])
def test_parameters(tmp_path, signature, expected):
    assert ('PARAMETER-DTO' in rules(scan(tmp_path, f'def f({signature}): pass\n'))) is expected


@pytest.mark.parametrize('code,expected', [
    ('class C:\n def f(self,a,b,c,d,e): pass\n', False),
    ('class C:\n def f(self,/,a,b,c,d,e,f): pass\n', True),
    ('class C:\n @classmethod\n def f(cls,a,b,c,d,e): pass\n', False),
    ('class C:\n @staticmethod\n def f(self,a,b,c,d,e): pass\n', True),
    ('class C:\n def outer(self):\n  def inner(self,a,b,c,d,e): pass\n', True),
    ('class C:\n async def f(self,*,a,b,c,d,e,f): pass\n', True),
])
def test_method_scope(tmp_path, code, expected):
    assert ('PARAMETER-DTO' in rules(scan(tmp_path, code))) is expected


def nested(block, count):
    return 'async def f(a):\n' + ''.join('    ' * (i+1) + block + '\n' for i in range(count)) + '    ' * (count+1) + 'pass\n'


@pytest.mark.parametrize('block', ['if a:', 'for a in []:', 'while a:', 'with a:',
                                  'async with a:', 'async for a in a:'])
@pytest.mark.parametrize('count', [4, 5])
def test_nesting_threshold(tmp_path, block, count):
    metric = scan(tmp_path, nested(block, count))
    assert ('EARLY-RETURN' in rules(metric)) is (count == 5)


@pytest.mark.parametrize('code,expected', [
    ('def f(a):\n if a: pass\n elif a: pass\n elif a: pass\n elif a: pass\n elif a: pass\n', 1),
    ('def f(a):\n if a: pass\n else:\n  if a: pass\n', 2),
    ('def f(a):\n try:\n  if a: pass\n except Exception:\n  if a: pass\n finally:\n  if a: pass\n', 2),
    ('def f(a):\n match a:\n  case 1:\n   if a: pass\n  case _:\n   pass\n', 2),
    ('def f(a):\n try:\n  if a: pass\n except* Exception:\n  if a: pass\n', 2),
    ('def f(a):\n def inner():\n  if a:\n   if a: pass\n', 0),
])
def test_control_flow_semantics(code, expected):
    assert scanner.nesting_depth(ast.parse(code).body[0]) == expected


@pytest.mark.parametrize('size', [60, 61])
def test_function_size(tmp_path, size):
    metric = scan(tmp_path, 'def f():\n' + '    pass\n' * (size-1))
    assert ('COMPACT-FUNCTION' in rules(metric)) is (size == 61)
    assert scanner.print_report([metric], [], True) == 0


@pytest.mark.parametrize('size', [400, 401])
def test_class_size(tmp_path, size):
    metric = scan(tmp_path, 'class C:\n' + '    x = 1\n' * (size-1))
    assert ('ANTI-GOD-CLASS' in rules(metric)) is (size == 401)


@pytest.mark.parametrize('count', [16, 17])
def test_method_count(tmp_path, count):
    metric = scan(tmp_path, 'class C:\n' + ''.join(f'    def m{i}(self): pass\n' for i in range(count)))
    assert ('SRP-BLOWUP' in rules(metric)) is (count == 17)


@pytest.mark.parametrize('source,expected', [
    ('import click', False), ('import client', False),
    ('import scripts.uploader', True), ('from scripts import uploader', True),
    ('import cli.main', True), ('from cli.main import run', True),
    ('from src.cli import main', True), ('from ...cli import main', True),
    ('from ...web import app', True), ('from web import app', True),
    ('from .. import cli', False), ('import missing_module', False),
])
def test_local_imports(project, source, expected):
    metric = scan(project, source+'\n', project, 'src/video_processing/core/action.py')
    assert ('DAG-REVERSE-IMPORT' in rules(metric)) is expected
    assert scanner.print_report([metric], [], True) == int(expected)
    assert scanner.print_report([metric], [], False) == 0


@pytest.mark.parametrize('relative', ['src/video_processing/core_helpers/a.py', 'src/video_processing/db_utils/a.py',
                                     'src/configuration/a.py', 'src/other/a.py'])
def test_exact_domain_paths(project, relative):
    assert rules(scan(project, 'import scripts.uploader\n', project, relative)) == set()


def test_foreign_project_is_generic(tmp_path, project):
    metric = scan(tmp_path / 'other', 'import cli.main\n', project, 'src/video_processing/core/a.py')
    assert not metric.project_rules
    assert rules(metric) == set()


@pytest.mark.parametrize('check', [False, True])
@pytest.mark.parametrize('bad', ['missing', 'empty', 'syntax', 'encoding', 'non_python'])
def test_cli_incomplete(tmp_path, bad, check, capsys):
    path = tmp_path / 'bad.py'
    if bad == 'empty':
        path.mkdir()
    elif bad == 'syntax':
        path.write_text('def broken(:')
    elif bad == 'encoding':
        path.write_bytes(b'\xff\xfe')
    elif bad == 'non_python':
        path = tmp_path / 'bad.txt'; path.write_text('text')
    good = tmp_path / 'good.py'; good.write_text('x=1\n')
    assert scanner.main((['--check'] if check else []) + [str(good), str(path)]) == 2
    output = capsys.readouterr().out
    assert '检查不完整' in output
    assert str(good) in output


def test_encoding_cookie(tmp_path):
    path = tmp_path / 'encoded.py'
    path.write_bytes('# coding: latin-1\nx="é"\n'.encode('latin-1'))
    assert rules(scanner.inspect_file(path)) == set()


def test_unreadable_file(tmp_path, monkeypatch):
    path = tmp_path / 'denied.py'; path.write_text('x=1')
    def denied(_):
        raise PermissionError('test read denied')
    monkeypatch.setattr(scanner.tokenize, 'open', denied)
    assert scanner.main([str(path)]) == 2


def test_walk_failure(tmp_path, monkeypatch):
    def denied(path, *, onerror, followlinks):
        onerror(PermissionError('test directory denied'))
        return iter(())
    monkeypatch.setattr(scanner.os, 'walk', denied)
    assert scanner.main([str(tmp_path)]) == 2


def test_duplicate_exclusion_and_symlink(tmp_path):
    good = tmp_path / 'good.py'; good.write_text('x=1')
    excluded = tmp_path / '.venv'; excluded.mkdir(); (excluded/'bad.py').write_text('broken(')
    files, failures = scanner.collect_target_files([str(tmp_path), str(good)])
    assert files == [good.resolve()] and failures == []
    (tmp_path / 'linked').symlink_to(excluded, target_is_directory=True)
    assert scanner.main([str(tmp_path)]) == 2


def test_incomplete_takes_precedence(project):
    metric = scan(project, 'import cli.main\n', project, 'src/config/extra.py')
    assert scanner.print_report([metric], ['missing target'], True) == 2


@pytest.fixture
def wrapper(tmp_path):
    # 实际维护的包装器与扫描器副本；通过专用隔离 runner 纳入 vpanel。
    root = tmp_path / 'tool home'
    (root / 'scripts').mkdir(parents=True)
    (root / '.venv/bin').mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[2] / 'vpanel', root / 'vpanel')
    shutil.copyfile(scanner.__file__, root / 'scripts/anti_spaghetti.py')
    (root / '.venv/bin/python').symlink_to(sys.executable)
    return root


def run_wrapper(wrapper, cwd, *args):
    return subprocess.run(['/bin/bash', str(wrapper / 'vpanel'), *args], cwd=cwd,
                          capture_output=True, text=True, timeout=15)


def test_wrapper_caller_paths(wrapper, tmp_path):
    for name, code, expected in [('project one', 'x=1', 0), ('project two', 'def broken(:', 2)]:
        root = tmp_path / name
        (root/'src').mkdir(parents=True)
        target = root/'src/same.py'; target.write_text(code)
        for command in [('craft', '--check'), ('antishit', '--check', 'src/'),
                        ('craft', '--check', 'src/same.py', str(target))]:
            result = run_wrapper(wrapper, root, *command)
            assert result.returncode == expected, result.stderr + result.stdout
            assert str(target.resolve()) in result.stdout
            assert str(wrapper/'src') not in result.stdout
    assert not (wrapper/'output').exists()


def test_wrapper_own_root_and_missing_interpreter(wrapper):
    (wrapper/'src').mkdir(); (wrapper/'src/a.py').write_text('x=1')
    assert run_wrapper(wrapper, wrapper, 'craft', '--check').returncode == 0
    (wrapper/'.venv/bin/python').unlink()
    result = run_wrapper(wrapper, wrapper, 'craft')
    assert result.returncode == 2


def test_wrapper_preserves_other_commands(wrapper, tmp_path):
    result = run_wrapper(wrapper, tmp_path, 'help')
    assert result.returncode == 0
    assert (wrapper/'output').is_dir()
    assert not (tmp_path/'output').exists()


def test_actual_read_permission(tmp_path):
    path = tmp_path / 'unreadable.py'; path.write_text('x=1')
    path.chmod(0)
    try:
        assert scanner.main([str(path)]) == 2
    finally:
        path.chmod(0o600)


def test_real_cli_exit_codes(project):
    shutil.copyfile(scanner.__file__, project / 'scripts/anti_spaghetti.py')
    core = project / 'src/video_processing/core/a.py'
    core.parent.mkdir(parents=True)
    core.write_text('import cli.main\n')
    def run(*args):
        return subprocess.run([sys.executable, '-B', str(project/'scripts/anti_spaghetti.py'), *args],
                              cwd=project, capture_output=True, text=True, timeout=10).returncode
    assert run(str(core)) == 0
    assert run('--check', str(core)) == 1
    assert run('--check', str(core), 'missing.py') == 2
    assert run('--check', 'missing.py') == 2


def test_nonregular_python_target(tmp_path):
    # 防止目录遍历遇到 .py FIFO 后阻塞读取。
    import os
    path = tmp_path / 'pipe.py'
    os.mkfifo(path)
    assert scanner.main([str(tmp_path)]) == 2
