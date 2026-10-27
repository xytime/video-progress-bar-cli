#!/usr/bin/env python3
"""独立 YouTube 出口的显式安装与只读验收；不管理桌面 VPN。

依赖：scripts -> utils.youtube_egress / utils.youtube_route -> config.settings。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-27 | Codex | 固定版本内核、私有节点副本、LaunchAgent 恢复与验收。 |
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from config.settings import settings
from video_processing.utils.youtube_egress import core_config, controller_json
from video_processing.utils.youtube_route import verify_youtube_route

LABEL = 'us.optionbank.video-egress'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def private_write(path, data):
    with Path(path).open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(data)


def health(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    for name, expected in manifest['sha256'].items():
        if digest(root / name) != expected:
            raise RuntimeError('独立出口文件完整性检查未通过')
    sock = root / 'control.sock'
    actual = controller_json('/configs', sock)
    endpoint = manifest['proxy']
    expected = core_config(endpoint, sock, manifest['node'], manifest['interface'])
    if (actual.get('mode') != 'rule' or actual.get('mixed-port') != expected['mixed-port']
            or actual.get('tun', {}).get('enable') is not False):
        raise RuntimeError('独立出口运行模式不符')
    groups = controller_json('/proxies', sock)['proxies']
    group = groups.get('VIDEO_SELF_ONLY', {})
    if group.get('all') != [manifest['node']] or group.get('now') != manifest['node']:
        raise RuntimeError('独立出口不是唯一自建节点')
    rules = controller_json('/rules', sock).get('rules', [])
    if len(rules) != 1 or rules[0].get('type') != 'Match' or rules[0].get('proxy') != 'VIDEO_SELF_ONLY':
        raise RuntimeError('独立出口存在非自建回退规则')
    config = settings.model_copy(update={
        'youtube_download_proxy': endpoint, 'youtube_controller_socket': sock,
        'youtube_download_required_node': manifest['node'],
    })
    return {'status': 'healthy', 'route': verify_youtube_route(config=config),
            'interface': manifest['interface'], 'only_self_hosted': True,
            'desktop_dependency': False}


def install(args, root):
    if not args.execute:
        return {'executed': False, 'root': str(root), 'proxy': args.proxy,
                'actions': ['复制固定版本内核与已有私有节点文件', '安装用户登录服务', '验收自建出口']}
    plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
    if root.exists() or plist.exists():
        raise RuntimeError('已有安装，拒绝覆盖；请先检查状态')
    if not args.source_profile or not args.core:
        raise ValueError('安装必须显式提供已有节点文件和内核路径')
    config = core_config(args.proxy, root / 'control.sock', settings.youtube_download_required_node,
                         settings.youtube_egress_interface)
    root.mkdir(mode=0o700, parents=True)
    # 节点文件只作本机不透明副本，不输出、解析或重新录入凭据。
    shutil.copyfile(Path(args.source_profile).expanduser(), root / 'nodes.yaml')
    os.chmod(root / 'nodes.yaml', 0o600)
    shutil.copyfile(Path(args.core).expanduser(), root / 'mihomo')
    os.chmod(root / 'mihomo', 0o700)
    private_write(root / 'config.json', json.dumps(config, ensure_ascii=False).encode())
    check = subprocess.run([str(root / 'mihomo'), '-t', '-d', str(root), '-f', str(root / 'config.json')],
                           capture_output=True, timeout=30)
    if check.returncode:
        raise RuntimeError('内核配置检查失败；保留安装文件供本机检查')
    manifest = {'schema': 1, 'proxy': args.proxy, 'node': settings.youtube_download_required_node,
                'interface': settings.youtube_egress_interface, 'created_at': time.time(),
                'sha256': {name: digest(root / name) for name in ('mihomo', 'nodes.yaml', 'config.json')}}
    private_write(root / 'manifest.json', json.dumps(manifest, indent=2).encode())
    definition = {
        'Label': LABEL, 'ProgramArguments': [str(root / 'mihomo'), '-d', str(root), '-f', str(root / 'config.json')],
        'WorkingDirectory': str(root), 'RunAtLoad': True, 'KeepAlive': True,
        'ThrottleInterval': 10, 'ProcessType': 'Background', 'Umask': 0o077,
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null',
    }
    private_write(plist, plistlib.dumps(definition))
    subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(plist)], check=True, capture_output=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            result = health(root)
            return {'installed': True, **result}
        except Exception:
            time.sleep(1)
    # 安装不能以验收失败的常驻进程告终；保留文件但卸载本次服务。
    subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{LABEL}'], capture_output=True)
    raise RuntimeError('出口未通过验收，已卸载本次服务；保留文件，未更改视频项目或桌面代理配置')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    setup = sub.add_parser('install')
    setup.add_argument('--execute', action='store_true')
    setup.add_argument('--core')
    setup.add_argument('--source-profile')
    setup.add_argument('--proxy', default=settings.youtube_download_proxy)
    sub.add_parser('health')
    args = parser.parse_args()
    root = settings.youtube_egress_root.expanduser().absolute()
    try:
        result = install(args, root) if args.action == 'install' else health(root)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        # 不把内核输出、节点配置、签名 URL 或任意异常参数带入审计日志。
        message = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
        print(json.dumps({'status': 'unhealthy', 'reason': message}, ensure_ascii=False))
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
