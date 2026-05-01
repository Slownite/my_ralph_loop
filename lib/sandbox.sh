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

    bwrap \
      --bind "$worktree" /workspace \
      "${mounts[@]}" \
      --ro-bind "$HOME/.claude" "$HOME/.claude" \
      --ro-bind "$HOME/.config/gh" "$HOME/.config/gh" \
      --ro-bind "$HOME/.ssh" "$HOME/.ssh" \
      --ro-bind /etc /etc \
      --proc /proc \
      --dev /dev \
      --tmpfs /tmp \
      --setenv HOME "$HOME" \
      --setenv PATH "$PATH" \
      --chdir /workspace \
      "$@"
  else
    # TODO: implement sandbox-exec parity on macOS
    cd "$worktree" && "$@"
  fi
}
