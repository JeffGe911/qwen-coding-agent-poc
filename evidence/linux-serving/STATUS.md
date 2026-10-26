# Linux + Docker + vLLM：状态

**vLLM 尚未运行。**（2026-10-24 写，2026-10-26 更新）

2026-10-26 更新：经 Jeff 同意，已在本机安装 **WSL2**（WSL 3.0.3，内核 6.18.54.1，发行版 Ubuntu）。这次停在了安装这一步：
- 已写 `%UserProfile%\.wslconfig`：内存 8 GB、swap 4 GB、8 个处理器，并开启闲置内存自动归还（`autoMemoryReclaim=gradual`），副本见 `wslconfig-applied.txt`。上限**还没在 WSL 里核实**（`free -m`、`nproc`）；
- 没有安装 Docker Engine 或 NVIDIA Container Toolkit，没有拉取镜像，也没有下载权重；
- 安装过程：系统自带的 `wsl.exe` 启动器只接受不带参数的 `--install`，`--no-distribution` 和 `--no-launch` 都被拒绝（`wsl-install-*.txt`）；最后在一个单独窗口运行 `wsl.exe --install`，由 Jeff 本人处理授权和 Ubuntu 的建用户；
- 安装后，以 root 运行的只读命令和 `wsl --shutdown` 都超过 2 分钟没有返回，可能是在等首次启动建用户的窗口，原因**未查明**；
- 停在这里的原因：Jeff 要求停止；另外本机可用内存只有约 8 GB，而 WSL 运行 vLLM 时最多会用到 8 GB，启动前应先腾出 10 GB 以上。

继续时的顺序：确认 WSL 能正常启动、关闭，核实资源上限；Windows 可用内存 ≥ 10 GB 后，安装 Docker Engine 和 NVIDIA Container Toolkit；先用 1.5B 模型跑 `acceptance.sh`，再用 7B AWQ 跑 `migrate.sh`。结果一律标为 WSL2，不算独立服务器。

以下是 2026-10-24 的原始状态：

已完成（只有代码和静态检查，没有做集成验证）：

- `deploy/linux-vllm/`：compose（镜像按 digest 固定、只在 127.0.0.1 监听、API key、资源限制、健康检查、日志轮转、运行时离线）、env.example、wslconfig.example（8 GB / 4 GB swap）、download_model.sh（固定 revision）、acceptance.sh（8 项验证，含资源预检和 key 过滤）、RUNBOOK.md。
- `tests/test_linux_vllm.py`：静态检查，两个脚本的 `bash -n` 语法检查，以及用替身命令（假的 uname/free/nvidia-smi/docker/curl）驱动 acceptance.sh 的拒绝路径：没有明确确认或 key 不是十六进制时拒绝；可用内存不足或 GPU 已被占用时在预检阶段停下，不启动、不结束任何容器；工具把 key 打印出来时，证据文件里也只有 [REDACTED]。这些只是脚本逻辑测试，不是部署验证。
- 官方文档与版本核对：见 docs-check.md。
- 本机环境检查：见 environment-check.txt。WSL 未安装，没有 Docker；有 Hypervisor；GPU 为 RTX 5070 Ti Laptop，计算能力 12.0，驱动 591.91。

开始实测所需的最小条件，满足任意一种即可：

1. **本机 WSL2**：负责人同意执行 `wsl --install`（需要管理员权限，可能要重启），并按 wslconfig.example 设置 8 GB 内存、4 GB swap。在 WSL 中安装 Docker Engine 和 NVIDIA Container Toolkit，下载约 9.2 GB 的镜像和 3.1 GB 的 1.5B 权重。运行前关闭其他应用，并同意在测试期间让 11437 上的 Ollama 保持空闲或临时停止。计算能力 12.0 能否运行，要到这一步才能确认。
2. **一台 Linux GPU 机器的 SSH**：具备 NVIDIA 驱动、Docker 与 NVIDIA Container Toolkit，提供一个独立的端口和目录。
3. **云 GPU**：付费，需要事先确定平台和预算，并由负责人明确批准。

阻塞期间不做任何替代：CPU 推理、mock、Windows 上的 Ollama，或者仅仅“容器启动成功”，都不算作 Linux GPU + vLLM 验证通过。
