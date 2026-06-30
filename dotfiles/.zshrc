# ─── Powerlevel10k Instant Prompt ────────────────────────
if [[ -r "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh" ]]; then
  source "${XDG_CACHE_HOME:-$HOME/.cache}/p10k-instant-prompt-${(%):-%n}.zsh"
fi

# ─── Source P10k ─────────────────────────────────────────
source ~/powerlevel10k/powerlevel10k.zsh-theme

# ─── History ─────────────────────────────────────────────
HISTFILE=~/.zsh_history
HISTSIZE=100000            # Disarankan dinaikkan agar tidak cepat terpotong
SAVEHIST=100000
setopt append_history      # Mencegah file history tertimpa (overwrite) oleh sesi lain
setopt inc_append_history  # KUNCI UTAMA: Langsung simpan ke file begitu ditekan Enter
setopt extended_history    # Opsional: Menyimpan timestamp (waktu) eksekusi perintah
setopt hist_ignore_dups
setopt hist_ignore_space
setopt share_history
alias clear-history="rm ~/.zsh_history && exec zsh"

# ─── Plugin ──────────────────────────────────────────────
source /usr/share/zsh/plugins/zsh-autosuggestions/zsh-autosuggestions.zsh
source /usr/share/zsh/plugins/zsh-syntax-highlighting/zsh-syntax-highlighting.zsh

# ─── Completion ──────────────────────────────────────────
autoload -Uz compinit && compinit
zstyle ':completion:*' menu select
zstyle ':completion:*' matcher-list 'm:{a-z}={A-Z}'

# ─── Colors (vivid) ──────────────────────────────────────
export LS_COLORS="$(vivid generate solarized-dark)"

# ─── Alias ───────────────────────────────────────────────
alias ls='eza --icons --color=always'
alias ll='eza -lah --icons --color=always'
alias la='eza -a --icons --color=always'
alias lt='eza --tree --icons --color=always'
alias grep='grep --color=auto'
alias ..='cd ..'
alias ...='cd ../..'
alias cls='clear'
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
export EDITOR=nvim
export VISUAL=$EDITOR
export PATH="$HOME/.local/bin:$PATH"

# ─── P10k Config ─────────────────────────────────────────
[[ ! -f ~/.p10k.zsh ]] || source ~/.p10k.zsh
