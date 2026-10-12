# ─── Powerlevel10k Instant Prompt ────────────────────────
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# ─── Source P10k ─────────────────────────────────────────
[[ ! -r ~/powerlevel10k/powerlevel10k.zsh-theme ]] || source ~/powerlevel10k/powerlevel10k.zsh-theme

# ─── History ─────────────────────────────────────────────
HISTFILE=~/.zsh_history
HISTSIZE=100000            # Disarankan dinaikkan agar tidak cepat terpotong
SAVEHIST=100000
setopt append_history      # Mencegah file history tertimpa (overwrite) oleh sesi lain
setopt extended_history    # Opsional: Menyimpan timestamp (waktu) eksekusi perintah
setopt hist_ignore_dups
setopt hist_ignore_space
setopt share_history
alias clear-history="rm ~/.zsh_history && exec zsh"

# ─── Plugin ──────────────────────────────────────────────
[[ ! -r /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh ]] || source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh

# ─── Completion ──────────────────────────────────────────
autoload -Uz compinit && compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'

# ─── Colors (vivid) ──────────────────────────────────────
if (( $+commands[vivid] )); then
  export LS_COLORS="$(vivid generate solarized-dark)"
fi

# ─── Alias ───────────────────────────────────────────────
if (( $+commands[eza] )); then
  alias ls='eza --icons --color=always'
  alias ll='eza -lah --icons --color=always'
  alias la='eza -a --icons --color=always'
  alias lt='eza --tree --icons --color=always'
else
  alias ll='ls -lah --color=auto'
  alias la='ls -a --color=auto'
fi
alias grep='grep --color=auto'
alias ..='cd ..'
alias ...='cd ../..'
alias cls='clear'
if (( $+commands[fastfetch] )); then
  alias status='fastfetch -l arch2'
fi
# Pacman
alias pac='sudo pacman -S'
alias pacu='sudo pacman -Syu'
alias pacr='sudo pacman -Rns'
alias pacs='pacman -Ss'
alias pacq='pacman -Qi'
# Sway
alias sway-reload='swaymsg reload'
# Snapshot
alias snap-list='sudo snapper -c root list'
alias snap-create='sudo snapper -c root create --description'

# ─── Keybind ─────────────────────────────────────────────
bindkey -e
bindkey '^[[A' history-search-backward
bindkey '^[[B' history-search-forward

# ─── Environment ─────────────────────────────────────────
if (( $+commands[nvim] )); then
  export EDITOR=nvim
else
  export EDITOR=vi
fi
export VISUAL=$EDITOR
typeset -U path
path=("$HOME/.local/bin" $path)
export PATH

# ─── P10k Config ─────────────────────────────────────────
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh

# Load syntax highlighting last so it can wrap the final line-editor widgets.
[[ ! -r /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh ]] || source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh
