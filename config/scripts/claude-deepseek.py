#!/usr/bin/env python3
"""Launch Claude Code with a custom DeepSeek profile, scoped to this process."""
import getpass
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from urllib.parse import urlparse


def model_label(model):
    identifier = model.replace('[1m]', '')
    return {'deepseek-flash': 'DeepSeek V4.1 Flash', 'deepseek-v4-pro': 'DeepSeek V4 Pro'}.get(identifier, identifier)


def configure_profile(path, config, input_fn=input, password_fn=getpass.getpass):
    updated = dict(config)
    print('Configure the custom DeepSeek profile. Leave a field blank to keep it.')
    key = password_fn('New DeepSeek API key (hidden): ').strip()
    if key:
        updated['api_key'] = key
    base = updated.get('base_url', 'https://api.deepseek.com/anthropic')
    url = input_fn(f'Anthropic-compatible API endpoint [{base}]: ').strip() or base
    parsed = urlparse(url)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('Enter a valid HTTP or HTTPS API endpoint.')
    print('1. DeepSeek V4.1 Flash — deepseek-flash\n2. DeepSeek V4 Pro — deepseek-v4-pro')
    choice = input_fn('Default model [Enter = keep current, 1 or 2]: ').strip()
    if choice not in ('', '1', '2'):
        raise ValueError('Choose 1, 2, or press Enter to keep the current model.')
    updated['base_url'] = url
    if choice:
        updated['model'] = {'1': 'deepseek-flash[1m]', '2': 'deepseek-v4-pro[1m]'}[choice]
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
            temporary = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            json.dump(updated, file, indent=2)
            file.write('\n')
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    print('Saved the custom profile. Normal Claude settings are unchanged.')
    if os.environ.get('DEEPSEEK_API_KEY'):
        print('An exported DEEPSEEK_API_KEY takes priority. Unset it to use the saved key.')


def build_launch(config, environment, args):
    env = dict(environment)
    token = env.get('DEEPSEEK_API_KEY') or config.get('api_key')
    if not token:
        raise ValueError('Set DEEPSEEK_API_KEY or enter your DeepSeek API key when prompted.')
    model = env.get('DEEPSEEK_MODEL') or config.get('model', 'deepseek-flash[1m]')
    small_model = config.get('small_model', model.replace('[1m]', ''))
    pro_model = config.get('pro_model', 'deepseek-v4-pro[1m]')
    options = [
        {'model': 'deepseek-flash[1m]', 'label': 'DeepSeek V4.1 Flash', 'description': 'API ID: deepseek-flash'},
        {'model': pro_model, 'label': model_label(pro_model), 'description': pro_model.replace('[1m]', '')},
    ]
    if model not in {option['model'] for option in options}:
        if model.replace('[1m]', '') == 'deepseek-flash':
            options[0]['model'] = model
        else:
            options.append({'model': model, 'label': model_label(model), 'description': 'Custom DeepSeek model'})
    env.pop('ANTHROPIC_API_KEY', None)
    env.pop('ANTHROPIC_DEFAULT_MODEL', None)
    for name in ('CLAUDE_CODE_USE_BEDROCK', 'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY'):
        env.pop(name, None)
    env.update({
        'ANTHROPIC_BASE_URL': env.get('DEEPSEEK_BASE_URL') or config.get('base_url', 'https://api.deepseek.com/anthropic'),
        'ANTHROPIC_AUTH_TOKEN': token,
        'ANTHROPIC_MODEL': model,
        'ANTHROPIC_DEFAULT_OPUS_MODEL': model,
        'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME': model_label(model),
        'ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION': model.replace('[1m]', ''),
        'ANTHROPIC_DEFAULT_SONNET_MODEL': model,
        'ANTHROPIC_DEFAULT_SONNET_MODEL_NAME': model_label(model),
        'ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION': model.replace('[1m]', ''),
        'ANTHROPIC_DEFAULT_HAIKU_MODEL': small_model,
        'ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME': model_label(small_model),
        'ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION': small_model.replace('[1m]', ''),
        'ANTHROPIC_CUSTOM_MODEL_OPTION': pro_model,
        'ANTHROPIC_CUSTOM_MODEL_OPTION_NAME': model_label(pro_model),
        'ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION': pro_model.replace('[1m]', ''),
        'CLAUDE_CODE_SUBAGENT_MODEL': small_model,
        'CLAUDE_CONFIG_DIR': str(Path(env.get('XDG_CONFIG_HOME') or Path(env['HOME']) / '.config') / 'claude-deepseek/state'),
    })
    flags = ['--dangerously-skip-permissions'] if config.get('always_proceed', True) and '--dangerously-skip-permissions' not in args else []
    picker = {'modelPicker': {'replaceBuiltInOptions': True, 'options': options}}
    return ['claude', *flags, '--settings', json.dumps(picker), '--model', model, *args], env


def main():
    path = Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'claude-deepseek/config.json'
    config = json.loads(path.read_text()) if path.exists() else {}
    if sys.argv[1:] == ['--configure']:
        configure_profile(path, config)
        return
    if sys.argv[1:] == ['--help']:
        print('Usage: claude-deepseek [Claude Code options]\n'
              '  --configure  Change API key, API endpoint, and default DeepSeek model.\n'
              '  --version    Show the installed Claude Code version.\n'
              'Models: DeepSeek V4.1 Flash (deepseek-flash), DeepSeek V4 Pro (deepseek-v4-pro).')
        return
    if not shutil.which('claude'):
        raise ValueError('Claude Code is not installed. Install @anthropic-ai/claude-code first.')
    if sys.argv[1:] == ['--version']:
        os.execvp('claude', ['claude', *sys.argv[1:]])
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
