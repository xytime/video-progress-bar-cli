"""CLI主入口"""
import sys
import logging
from pathlib import Path
import click
from config.settings import settings

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """视频处理工具 - 提供视频加工相关的工具方法"""
    # 确保必要的目录存在
    settings.ensure_directories()
    pass


@cli.command()
def info():
    """显示项目信息"""
    click.echo("视频处理工具 v0.1.0")
    click.echo("提供视频加工相关的工具方法")


# 导入并注册命令模块
try:
    from cli.commands.add_progressbar import add_progressbar
    from cli.commands.auto_caption import auto_caption
    from cli.commands.extract_subs import extract_subs
    cli.add_command(add_progressbar)
    cli.add_command(auto_caption)
    cli.add_command(extract_subs)
except ImportError:
    # 如果相对导入失败，尝试绝对导入
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from cli.commands.add_progressbar import add_progressbar
    from cli.commands.auto_caption import auto_caption
    from cli.commands.extract_subs import extract_subs
    cli.add_command(add_progressbar)
    cli.add_command(auto_caption)
    cli.add_command(extract_subs)


def main():
    """主函数"""
    cli()


if __name__ == "__main__":
    main()

