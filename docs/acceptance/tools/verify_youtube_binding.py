"""由配置负责人私下执行；不联网、不写文件、不输出密钥或其摘要。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0.0 | 2026-10-13 | Codex | 隐藏输入核对生产配置及 launchd 覆盖，只输出白名单结果 |
"""
import argparse
import getpass
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path('/Volumes/EXT2T/MacMini4_SSD/PycharmProjects/Video-precessing')
PROJECT = 'gen-lang-client-0993011647'
RESOURCE = '286cb0f6-4231-4ca2-831f-1e4646829b55'
KEY = 'YOUTUBE_DATA_API_KEY'


def same(a, b):
    return bool(a and b) and hmac.compare_digest(a.encode(), b.encode())


def classify(values, expected):
    if not expected or not values:
        return 'UNKNOWN'
    return 'MATCH' if all(same(value, expected) for value in values) else 'MISMATCH'


def command(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=10)
    if result.returncode:
        raise RuntimeError('host query unavailable')
    return result.stdout


def launch_values(text):
    # 仅分析已加载服务报告里的配置值；不把名称出现误当作配置值。
    return [match.group(1).strip().strip('"') for match in re.finditer(
        r'^\s*YOUTUBE_DATA_API_KEY\s*=>\s*(.*?)\s*$', text, re.M | re.I)]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--self-test', action='store_true')
    args = parser.parse_args()
    if args.self_test:
        assert classify(['synthetic-a'], 'synthetic-a') == 'MATCH'
        assert classify(['synthetic-a', 'synthetic-b'], 'synthetic-a') == 'MISMATCH'
        assert classify([], 'synthetic-a') == 'UNKNOWN'
        assert classify([''], 'synthetic-a') == 'MISMATCH'
        assert launch_values('environment = {\n YOUTUBE_DATA_API_KEY => synthetic-a\n}') == ['synthetic-a']
        print('SELF_TEST_PASS: 5 synthetic checks; no production reads')
        return 0
    if not sys.stdin.isatty():
        print('UNKNOWN: 请在本机交互终端运行，不要通过管道传入密钥。')
        return 2
    print('请从指定 Cloud 凭据复制密钥，粘贴到下一行；输入不会显示。')
    print('项目：' + PROJECT + '；凭据：video-precessing-youtube-catalog；资源：' + RESOURCE)
    result = {'project': PROJECT, 'credential_resource_id': RESOURCE,
              'network_requests': 0, 'secrets_written': False,
              'runtime_memory_verified': False,
              'scope': 'file and loaded launchd configuration; controlled restart/readback still required'}
    try:
        supplied = getpass.getpass('Cloud 密钥（隐藏输入）：').strip()
        # 不导入应用 settings，避免数据库初始化及解释器路径改变配置来源。
        from dotenv import dotenv_values
        import warnings
        import logging
        logging.getLogger('dotenv.main').disabled = True
        with warnings.catch_warnings():
            warnings.simplefilter('error')
            config = dotenv_values(ROOT / '.env', interpolate=False)
        found = [v for k, v in config.items() if k.upper() == KEY]
        if len(found) != 1 or not found[0] or '${' in found[0]:
            raise RuntimeError('configuration ambiguous')
        result['production_file'] = classify(found, supplied)
        label = 'gui/' + str(os.getuid()) + '/com.videopipeline.ui'
        service = command(['/bin/launchctl', 'print', label])
        cwd = re.search(r'^\s*working directory = (.*?)\s*$', service, re.M)
        pid = re.search(r'^\s*pid = (\d+)\s*$', service, re.M)
        if not cwd or Path(cwd.group(1)) != ROOT or not pid:
            raise RuntimeError('service identity unknown')
        overrides = launch_values(service)
        result['loaded_service'] = 'com.videopipeline.ui'
        result['launchd_override'] = classify(overrides, supplied) if overrides else 'NOT_LISTED'
        # shell/wrapper 可以在 launchd 之后改环境；此工具不声称已经证明进程内值。
        result['result'] = 'CONFIG_MATCH_RESTART_REQUIRED' if result['production_file'] == 'MATCH' and (
            not overrides or result['launchd_override'] == 'MATCH') else 'MISMATCH'
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print('只将上方 JSON 结果发回；请清空剪贴板，不发送密钥或配置截图。')
        return 0 if result['result'] == 'CONFIG_MATCH_RESTART_REQUIRED' else 1
    except (Exception, KeyboardInterrupt):
        # 不输出异常内容、子进程输出、配置值或 traceback，避免泄漏输入。
        result['result'] = 'UNKNOWN'
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
