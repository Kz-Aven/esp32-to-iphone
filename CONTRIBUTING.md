# 参与贡献

## 开发环境

```bash
./setup.sh --dev
HIDAGENT_DATA="$PWD/server/.local-data" server/.venv/bin/python -m pytest server/tests -q
server/.venv/bin/ruff check server
```

测试包含本机 TCP/HTTP 与真实 stdio 子进程，需要运行环境允许本机网络监听，不需要连接真实手机或提供模型 API Key。

修改固件后，先复制 `secrets.example.h` 为本地 `secrets.h`，执行 `./hardware/flash.sh --build-only` 检查编译。CI 使用示例配置，不需要真实 Wi-Fi 凭据。

Python 依赖在 `server/pyproject.toml` 声明，`server/uv.lock` 由 uv 维护。变更依赖后更新锁文件。不要提交虚拟环境、`secrets.h`、`.env`、编译输出、校准文件和私人截图。

## 提交问题或修改

请写明板型（含 Flash/PSRAM）、iPhone/iOS、电脑系统、USB 接口与适配器、Wi-Fi 环境、复现步骤，以及去除敏感信息后的错误。兼容性声明应区分代码测试、实机成功和未验证推测。

手机任务的成功以实际可见结果为准；ACK、画面变化或模型声称完成都不足以证明成功。涉及发送的动作不得在异常后自动重放。改动截图复用或指针定位时，应保留过期凭据、动画、延迟帧与点击失败保护的回归覆盖。

现有硬件链路可独立运行。请保持修改聚焦，并在 PR 描述中说明行为变化、测试与实机验证范围。
