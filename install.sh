#!/usr/bin/env bash
set -euo pipefail

install_dir="${HOME}/.local/bin"
target="${install_dir}/claude-env"
app_dir="${HOME}/.local/share/claude-env"
source_url="${CLAUDE_ENV_URL:-https://github.com/felix021/claude-env/archive/refs/heads/main.tar.gz}"

mkdir -p "${install_dir}"

write_launcher() {
  cat >"${target}" <<EOF
#!/usr/bin/env bash
export PYTHONPATH="${app_dir}:\${PYTHONPATH:-}"
export CLAUDE_ENV_EXECUTABLE="\$0"
invoked="\$(basename "\$0")"
if [[ "\${invoked}" == claude-* && "\${invoked}" != "claude-env" ]]; then
  exec python3 -m claude_env run "\${invoked#claude-}" "\$@"
fi
exec python3 -m claude_env "\$@"
EOF
  chmod +x "${target}"
}

if [[ -n "${CLAUDE_ENV_SOURCE_DIR:-}" ]]; then
  rm -rf "${app_dir}"
  mkdir -p "${app_dir}"
  cp -R "${CLAUDE_ENV_SOURCE_DIR}/claude_env" "${app_dir}/"
  write_launcher
elif [[ -n "${CLAUDE_ENV_SOURCE:-}" ]]; then
  cp "${CLAUDE_ENV_SOURCE}" "${target}"
  chmod +x "${target}"
else
  tmp_dir="$(mktemp -d)"
  cleanup() {
    rm -rf "${tmp_dir}"
  }
  trap cleanup EXIT

  archive="${tmp_dir}/claude-env.tar.gz"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "${source_url}" -o "${archive}"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "${archive}" "${source_url}"
  else
    echo "error: curl or wget is required to download claude-env" >&2
    exit 1
  fi
  tar -xzf "${archive}" -C "${tmp_dir}"
  source_root="$(find "${tmp_dir}" -mindepth 1 -maxdepth 1 -type d | head -n 1)"
  rm -rf "${app_dir}"
  mkdir -p "${app_dir}"
  cp -R "${source_root}/claude_env" "${app_dir}/"
  write_launcher
fi

echo "installed ${target}"

case ":${PATH}:" in
  *":${install_dir}:"*) ;;
  *)
    echo "${install_dir} is not in PATH."
    shell_name="$(basename "${SHELL:-}")"
    case "${shell_name}" in
      zsh)
        echo "Add this to ~/.zshrc: export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
      bash)
        echo "Add this to ~/.bashrc: export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
      *)
        echo "Add this to your shell profile: export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
    esac
    ;;
esac
