# cliquota-managed Gemini launcher
gemini() {
    if [ -n "$TMUX" ]; then
        command gemini "$@"
    else
        local session_name="gemini-$(date +%s)-$$"
        local quoted_args=""
        if [ "$#" -gt 0 ]; then
            quoted_args=" ${(q)@}"
        fi
        tmux new-session -s "$session_name" "exec command gemini${quoted_args}"
    fi
}
