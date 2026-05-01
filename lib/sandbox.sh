#!/usr/bin/env bash
# Runs a command in a sandbox. On NixOS: bwrap isolation. On Mac: no-op (degraded).
# Usage: sandbox_run <worktree_path> <command...>

sandbox_run() {
  local worktree="$1"
  shift

  if [[ "$(uname)" == "Linux" ]] && command -v bwrap &>/dev/null; then
    bwrap \
      --bind "$worktree" /workspace \
      --ro-bind /nix/store /nix/store \
      --ro-bind "$HOME/.claude" "$HOME/.claude" \
      --ro-bind /etc /etc \
      --proc /proc \
      --dev /dev \
      --tmpfs /tmp \
      --setenv HOME "$HOME" \
      --chdir /workspace \
      "$@"
  else
    # TODO: implement sandbox-exec parity on macOS
    cd "$worktree" && "$@"
  fi
}
