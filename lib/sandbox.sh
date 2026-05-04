#!/usr/bin/env bash
# Runs a command in a sandbox. On Linux+bwrap: full isolation. On Mac: degraded.
# Usage: sandbox_run <worktree_path> <command...>

sandbox_run() {
  local worktree="$1"
  shift

  if [[ "$(uname)" == "Linux" ]] && command -v bwrap &>/dev/null; then
    local mounts=()
    for dir in /nix/store /usr /bin /lib /lib64 /run; do
      [[ -d "$dir" ]] && mounts+=(--ro-bind "$dir" "$dir")
    done

    # Build a writable temp copy of .claude.json with /workspace pre-trusted so
    # Claude Code's interactive trust dialog is skipped (it reads hasTrustDialogAccepted).
    local tmp_claude_json
    tmp_claude_json=$(mktemp --suffix=.json)
    # shellcheck disable=SC2064
    trap "rm -f '$tmp_claude_json'" EXIT
    if [[ -f "$HOME/.claude.json" ]] && command -v node &>/dev/null; then
      node -e "
        const fs = require('fs');
        const d = JSON.parse(fs.readFileSync('$HOME/.claude.json', 'utf8'));
        if (!d.projects) d.projects = {};
        if (!d.projects['/workspace']) d.projects['/workspace'] = {};
        d.projects['/workspace'].hasTrustDialogAccepted = true;
        fs.writeFileSync('$tmp_claude_json', JSON.stringify(d));
      "
    elif [[ -f "$HOME/.claude.json" ]]; then
      cp "$HOME/.claude.json" "$tmp_claude_json"
    else
      printf '{"projects":{"/workspace":{"hasTrustDialogAccepted":true}}}' > "$tmp_claude_json"
    fi

    bwrap \
      --bind "$worktree" /workspace \
      "${mounts[@]}" \
      --ro-bind "$HOME/.claude" "$HOME/.claude" \
      --tmpfs "$HOME/.claude/session-env" \
      --bind "$tmp_claude_json" "$HOME/.claude.json" \
      --ro-bind "$HOME/.config/gh" "$HOME/.config/gh" \
      --ro-bind "$HOME/.ssh" "$HOME/.ssh" \
      --ro-bind /etc /etc \
      --proc /proc \
      --dev /dev \
      --tmpfs /tmp \
      --setenv HOME "$HOME" \
      --setenv PATH "$PATH" \
      --setenv GIT_SSH_COMMAND "ssh -F /dev/null" \
      --chdir /workspace \
      "$@"
  else
    # TODO: implement sandbox-exec parity on macOS
    cd "$worktree" && "$@"
  fi
}
