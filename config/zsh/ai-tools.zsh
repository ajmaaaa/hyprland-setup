# AI coding tools: automatic tool execution, requested by the user.
typeset -U path
path=("$HOME/.local/bin" $path)
export PATH

function claude {
  command claude --dangerously-skip-permissions "$@"
}

function codex {
  command codex --dangerously-bypass-approvals-and-sandbox "$@"
}

function claude-deepseek {
  command "$HOME/.local/bin/claude-deepseek" "$@"
}

# Preserve the old command name while using the current custom profile.
function claude-ds-auto {
  command "$HOME/.local/bin/claude-deepseek" "$@"
}
