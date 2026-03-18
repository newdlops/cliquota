#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
PAYLOAD_DIR="$SCRIPT_DIR/payload"
CLIQUOTA_HOME="${CLIQUOTA_HOME:-$HOME/.cliquota}"
BACKUP_DIR="$CLIQUOTA_HOME/backups/$(date +%Y%m%d-%H%M%S)"

log() {
    printf '[cliquota] %s\n' "$*"
}

backup_file() {
    local target="$1"
    local rel backup_target

    [ -e "$target" ] || return 0

    rel="${target#$HOME/}"
    if [ "$rel" = "$target" ]; then
        rel="$(basename "$target")"
    fi

    backup_target="$BACKUP_DIR/$rel"
    mkdir -p "$(dirname "$backup_target")"
    cp -p "$target" "$backup_target"
}

install_file() {
    local src="$1"
    local dst="$2"
    local mode="$3"

    mkdir -p "$(dirname "$dst")"
    backup_file "$dst"
    install -m "$mode" "$src" "$dst"
    log "installed $dst"
}

rewrite_managed_block() {
    local file="$1"
    local begin_marker="$2"
    local end_marker="$3"
    local block_line="$4"
    local tmp

    mkdir -p "$(dirname "$file")"
    backup_file "$file"
    tmp="$(mktemp)"

    if [ -f "$file" ]; then
        awk -v begin="$begin_marker" -v end="$end_marker" '
            $0 == begin { skip = 1; next }
            $0 == end { skip = 0; next }
            !skip { print }
        ' "$file" >"$tmp"
    else
        : >"$tmp"
    fi

    printf '\n%s\n%s\n%s\n' "$begin_marker" "$block_line" "$end_marker" >>"$tmp"
    mv "$tmp" "$file"
    log "updated $file"
}

require_binary() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf '[cliquota] missing required command: %s\n' "$1" >&2
        exit 1
    fi
}

ensure_tmux() {
    if command -v tmux >/dev/null 2>&1; then
        return 0
    fi

    if [[ "$OSTYPE" == "darwin"* ]]; then
        log "tmux not found. attempting to install via homebrew for macOS..."

        local brew_exe=""
        if [[ "$(uname -m)" == "arm64" ]] && [[ -x "/opt/homebrew/bin/brew" ]]; then
            brew_exe="/opt/homebrew/bin/brew"
        elif [[ -x "/usr/local/bin/brew" ]]; then
            brew_exe="/usr/local/bin/brew"
        elif command -v brew >/dev/null 2>&1; then
            brew_exe=$(command -v brew)
        fi

        if [[ -n "$brew_exe" ]]; then
            log "using homebrew: $brew_exe"
            "$brew_exe" install tmux
        else
            log "homebrew not found. please install homebrew first: https://brew.sh"
            exit 1
        fi
    else
        log "tmux not found. please install tmux manually."
        exit 1
    fi
}

ensure_tmux
require_binary install
require_binary awk
require_binary python3
require_binary tmux

install_file "$PAYLOAD_DIR/.gemini/tmux_status.py" "$HOME/.gemini/tmux_status.py" 0644
install_file "$PAYLOAD_DIR/.codex/bin/codex-rate-limits" "$HOME/.codex/bin/codex-rate-limits" 0755
install_file "$PAYLOAD_DIR/.codex/bin/codex-status-pane" "$HOME/.codex/bin/codex-status-pane" 0755
install_file "$PAYLOAD_DIR/tmux.conf" "$CLIQUOTA_HOME/tmux.conf" 0644
install_file "$PAYLOAD_DIR/gemini-wrapper.zsh" "$CLIQUOTA_HOME/gemini-wrapper.zsh" 0644
install_file "$PAYLOAD_DIR/bin/copy-text" "$CLIQUOTA_HOME/bin/copy-text" 0755

rewrite_managed_block \
    "$HOME/.tmux.conf" \
    "# >>> cliquota tmux >>>" \
    "# <<< cliquota tmux <<<" \
    "source-file \"$CLIQUOTA_HOME/tmux.conf\""

rewrite_managed_block \
    "$HOME/.zshrc" \
    "# >>> cliquota gemini >>>" \
    "# <<< cliquota gemini <<<" \
    "source \"$CLIQUOTA_HOME/gemini-wrapper.zsh\""

python3 -m py_compile "$HOME/.gemini/tmux_status.py"

if [ "${CLIQUOTA_SKIP_TMUX_RELOAD:-0}" != "1" ] && command -v tmux >/dev/null 2>&1 && tmux list-sessions >/dev/null 2>&1; then
    tmux source-file "$HOME/.tmux.conf" || true
fi

if [ "${CLIQUOTA_SKIP_ZSH_CHECK:-0}" != "1" ] && command -v zsh >/dev/null 2>&1; then
    zsh -n "$HOME/.zshrc"
fi

log "backups saved under $BACKUP_DIR"
log "open a new shell or run: source ~/.zshrc"
