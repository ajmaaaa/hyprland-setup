#!/usr/bin/env python3
"""Launch Claude Code with a custom DeepSeek profile, scoped to this process."""
import getpass
import json
import os
from pathlib import Path
import shutil
import sys


def build_launch(config, environment, args):
    env = dict(environment)
    token = env.get('DEEPSEEK_API_KEY') or config.get('api_key')
    if not token:
        raise ValueError('Set DEEPSEEK_API_KEY or enter your DeepSeek API key when prompted.')
    model = env.get('DEEPSEEK_MODEL') or config.get('model', 'deepseek-flash[1m]')
    small_model = config.get('small_model', model.replace('[1m]', ''))
    env.pop('ANTHROPIC_API_KEY', None)
    for name in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(name, None)
    env.update({
        'ANTHROPIC_BASE_URL': env.get('DEEPSEEK_BASE_URL') or config.get('base_url', 'https://api.deepseek.com/anthropic'),
        'ANTHROPIC_AUTH_TOKEN': token,
        'ANTHROPIC_MODEL': model,
        'ANTHROPIC_DEFAULT_OPUS_MODEL': model,
        'ANTHROPIC_DEFAULT_SONNET_MODEL': model,
        'ANTHROPIC_DEFAULT_HAIKU_MODEL': small_model,
        'CLAUDE_CODE_SUBAGENT_MODEL': small_model,
        'CLAUDE_CONFIG_DIR': str(Path(env.get('XDG_CONFIG_HOME') or Path(env['HOME']) / '.config') / 'claude-deepseek/state'),
    })
    return ['claude', '--model', model, *args], env


def main():
    if not shutil.which('claude'):
        raise ValueError('Claude Code is not installed. Install @anthropic-ai/claude-code first.')
    if sys.argv[1:] in (['--help'], ['--version']):
        os.execvp('claude', ['claude', *sys.argv[1:]])
    path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'claude-deepseek/config.json'
    config = json.loads(path.read_text()) if path.exists() else {}
    env = dict(os.environ)
    if not env.get('DEEPSEEK_API_KEY') and not config.get('api_key') and sys.stdin.isatty():
        env['DEEPSEEK_API_KEY'] = getpass.getpass('DeepSeek API key (this session only): ')
    command, env = build_launch(config, env, sys.argv[1:])
    Path(env['CLAUDE_CONFIG_DIR']).mkdir(mode=0o700, parents=True, exist_ok=True)
    os.execvpe('claude', command, env)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as error:
        raise SystemExit(str(error))
