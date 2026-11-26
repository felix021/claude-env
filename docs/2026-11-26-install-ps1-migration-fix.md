# install.ps1 迁移报错修复记录（2026-11-26）

## 现象

Windows PowerShell 5.1 下执行安装脚本：

```powershell
iwr https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1 | iex
```

安装输出正常，`claude-env.cmd` 也已生成，但紧接着出现一段报错：

```text
python.exe :   File "<string>", line 1
At line:105 char:9
+         & python -c $migrateScript 2>$null
+         ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (  File "<string>", line 1:String) [], RemoteException
    + FullyQualifiedErrorId : NativeCommandError
```

结果就是：命令装好了，但配置迁移没有执行，旧版本的 `providers.json` 仍是旧格式。

## 根因

安装脚本把安装目录直接拼进了要执行的 Python 源码：

```python
sys.path.insert(0, 'C:\Users\<user>\.local\share\claude-env')
```

Python 字符串字面量里 `\U` 是 Unicode 转义符，后面跟的不是合法的 8 位十六进制，于是整段代码在解析阶段就报 `SyntaxError: truncated \UXXXXXXXX escape`，迁移函数根本没被导入。

报错看起来像脚本崩了，还有一层原因：PowerShell 5.1 会把原生程序的 stderr 包装成 `NativeCommandError`，而 `2>$null` 并不能可靠地把这种记录丢掉。

## 修复

处理思路：不再把路径写进 Python 源码，让路径只通过环境变量和启动器传递。

1. `claude_env/cli.py` 增加内部命令 `_migrate`：只是调用 `migrate_storage()`，help 列表里不显示。
2. `install.ps1` 和 `install.sh` 的迁移步骤改为调用刚装好的启动器：
   ```powershell
   & $Target _migrate
   ```
   安装目录由启动器里的 `PYTHONPATH` 负责，不再参与任何字符串拼接。
3. `install.ps1` 的迁移调用改成尽力而为：临时把 `$ErrorActionPreference` 设为 `Continue`，并用 `try/catch` 包住。迁移失败只输出一条警告，不影响安装和 PATH 设置。

## 其他脚本的同类问题核查

- `install.sh` 原本用的是同一种写法（`sys.path.insert(0, '${app_dir}')`）。Linux/macOS 路径一般不带反斜杠，所以平时不暴露；但 `HOME` 里含反斜杠或单引号时同样会出错。这次一并改成了调用启动器。
- 生成的 `claude-<name>` 快捷命令只使用 `%~dp0` 或相对调用，没有把绝对路径写进 Python 代码。
- 启动器（`.cmd` 和 bash 脚本）里的路径是写在 `set PYTHONPATH=...` 或 `export PYTHONPATH=...` 里的，不经过 Python 字符串解析，不属于这一类问题。
- 新增回归测试：两个安装脚本里都不允许出现 `sys.path.insert`，且必须通过 `_migrate` 执行迁移。

## 验证步骤

1. 跑全部单元测试：

   ```bash
   python3 -m unittest discover -s tests
   ```

2. Linux 端到端验证（覆盖安装脚本 + 迁移）：

   - 在临时 `HOME` 下造一个 v1 的配置：

     ```json
     {"version": 1, "providers": {"glm": {"base_url": "https://provider.example/v1", "token": "secret-token", "default_model": "glm-5-turbo"}}}
     ```

   - 用 `CLAUDE_ENV_SOURCE_DIR` 指向仓库执行 `install.sh`。
   - 预期：`providers.json` 的 `version` 变成 3，token 和模型进入 `env/settings.glm.json`。

   对应的自动化测试是 `tests/test_install.py::test_installer_migrates_storage_through_installed_launcher`。

3. Windows 手工验证：

   ```powershell
   iwr https://raw.githubusercontent.com/felix021/claude-env/main/install.ps1 | iex
   claude-env.cmd version
   claude-env.cmd list
   ```

   预期：

   - 不再出现 `SyntaxError` 或 `NativeCommandError`；
   - 如果配置是旧版本，会看到 `migrated N provider(s) to v2` / `to v3`；
   - `list` 能正常列出 provider 和默认模型。

4. 如果安装完成了但迁移没跑成功，可以手动补一次（幂等，重复执行无副作用）：

   ```bash
   claude-env _migrate
   ```

   ```powershell
   claude-env.cmd _migrate
   ```

   迁移会改写 `~/.config/claude-env/`（Windows 为 `%APPDATA%\claude-env\`）下的配置，操作前建议先备份该目录。
