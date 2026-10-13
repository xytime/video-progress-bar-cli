"""并行源码提交后的一次性上线接续：从真实已停机的维护态继续，不伪造原 journal。

# Modification History
| Version | Date | Author | Description |
| --- | --- | --- | --- |
| 1.0 | 2026-10-13 | Codex | 沿用宿主逐步 preflight/action/verify，保留失败现场 |
"""
from pathlib import Path
from video_processing.core.deployment import project_lock, read_json, write_json, require
from video_processing.core.deployment_host import HostDeployment

STEPS = ('backup', 'adopt', 'start', 'resume', 'restore', 'verify')


def continue_stopped(directory):
    directory = Path(directory).resolve()
    plan = read_json(directory / 'plan.json')
    host = HostDeployment(plan, directory)
    journal = directory / 'maintenance-continuation.json'
    with project_lock(host.lock_path):
        require(not journal.exists(), 'CONTINUATION_ALREADY_ATTEMPTED')
        # backup 的原生前置检查同时证明来源基线、保护、调度冻结、账本空闲、
        # 所有 worker 退出且 UI 已卸载；不能仅凭人工回执推断已停机。
        host.preflight('backup')
        state = {'kind':'explicit-maintenance-continuation', 'supersedes':plan['supersedes'],
                 'state':'RUNNING', 'done':[], 'pending':None}
        write_json(journal, state)
        for step in STEPS:
            try:
                host.preflight(step)
                state['pending'] = step
                write_json(journal, state)
                result = host.action(step)
                require(isinstance(result, dict) and result.get('ok') is True, 'ACTION_RESULT_INVALID')
                host.verify(step, result)
                write_json(directory / (step + '.json'), result)
                state['done'].append(step)
                state['pending'] = None
                write_json(journal, state)
            except Exception as exc:
                state.update(state='FAILED', failed_step=step, error=getattr(exc,'code',type(exc).__name__))
                write_json(journal, state)
                raise
        host.final_status()
        state['state'] = 'COMPLETE'
        write_json(journal, state)
        return state


if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--directory', required=True, type=Path)
    print(json.dumps(continue_stopped(parser.parse_args().directory), ensure_ascii=False))
