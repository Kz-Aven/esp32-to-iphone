# 从零搭建 ESP32 to iPhone

本文帮助你复现：Agent 通过 MCP 看见手机画面，经 ESP32-S3 操作真实 iPhone。主路径为 macOS Apple Silicon + ESP32-S3-DevKitC-1-N16R8 + Lightning iPhone。

## 搭建检查表

- [ ] 数据线可以传数据，不只是充电。
- [ ] ESP32-S3 的 UART 连接电脑后出现串口。
- [ ] 固件中的 Wi-Fi 与电脑 IP 正确，板子在线。
- [ ] 手机辅助触控开启，原生 USB 连接后出现圆形指针。
- [ ] AirPlay 连接后网页有实时画面。
- [ ] 校准完成，`device`、`screen`、`calibrated` 都为 `true`。
- [ ] MCP 最小测试只移动指针成功，再开始业务任务。

## 安装基础工具

macOS 首次使用编译工具时，先安装 Command Line Tools（已安装可跳过）：

```bash
xcode-select --install
```

安装 [Homebrew](https://brew.sh/) 后执行：

```bash
brew install uv arduino-cli cmake pkg-config gstreamer libplist openssl@3
```

获取本仓库：

```bash
git clone https://github.com/Kz-Aven/esp32-to-iphone.git
cd esp32-to-iphone
./setup.sh
```

`setup.sh` 使用 uv 管理 Python 3.12，安装锁定的后端与 MCP 依赖。应用代码要求 Python 3.10+；复现优先使用脚本指定的版本。

## 安装 UxPlay（macOS）

UxPlay 是本项目的外部 AirPlay 接收器，不是手机端 App。以下固定在已用于实测的 `v1.73.7`，在本仓库之外下载、构建，避免把第三方构建产物提交到项目中：

```bash
mkdir -p "$HOME/Developer"
cd "$HOME/Developer"
git clone --depth 1 --branch v1.73.7 https://github.com/FDH2/UxPlay.git
cmake -S UxPlay -B UxPlay/build -DCMAKE_INSTALL_PREFIX="$HOME/.local"
cmake --build UxPlay/build --parallel
cmake --install UxPlay/build
export PATH="$HOME/.local/bin:$PATH"
uxplay -h
```

若已存在 `UxPlay` 目录，先检查该目录，不要重复覆盖。将 `export PATH="$HOME/.local/bin:$PATH"` 添加到 shell 配置，确保启动后端的终端能找到 `uxplay`。Apple Silicon 与 Intel Homebrew 前缀不同，命令不依赖个人绝对路径。

安装方式参考 [UxPlay 官方 macOS 构建说明](https://github.com/FDH2/UxPlay#building-uxplay-on-macos-intel-x86_64-and-apple-silicon-macs)。若 CMake 找不到 Homebrew 依赖，可加 `-DCMAKE_PREFIX_PATH="$(brew --prefix)"` 重新配置。GStreamer 管线还需 `videorate`、`jpegenc`、`fdsink` 和 H.264 解码插件；可用 `gst-inspect-1.0 jpegenc` 检查插件。

Linux 可通过发行版安装 UxPlay、GStreamer 及 Avahi，Python/MCP 使用同样代码。Ubuntu/Debian 的常见安装方式如下；Linux 硬件链路尚未在本项目完成实机验收：

```bash
sudo apt install uxplay avahi-daemon gstreamer1.0-plugins-base \
  gstreamer1.0-plugins-good gstreamer1.0-plugins-bad gstreamer1.0-libav
```

## 烧录固件

回到本仓库根目录，在 Arduino CLI 安装已验证的 ESP32 core：

```bash
arduino-cli --config-file arduino-cli.yaml core update-index
arduino-cli --config-file arduino-cli.yaml core install esp32:esp32@3.3.12
cp hardware/hid_bridge/secrets.example.h hardware/hid_bridge/secrets.h
```

编辑 `hardware/hid_bridge/secrets.h`：

| 配置项 | 填写内容 |
|---|---|
| `WIFI_SSID` | 2.4GHz Wi-Fi 名称 |
| `WIFI_PASS` | Wi-Fi 密码 |
| `SERVER_HOST` | 运行电脑服务的局域网 IP，如 `192.168.1.10`，不能填 `127.0.0.1` |
| `SERVER_PORT` | 默认 `7300`，应与后端 `DEVICE_PORT` 相同 |

Mac IP 可以在“系统设置 → Wi-Fi → 当前网络详情 → TCP/IP”查看。建议在路由器配置 DHCP 地址保留，避免重启网络后 IP 改变。Wi-Fi 凭据只保存本地，不提交 Git。

### UART 与原生 USB 的区别

```text
烧录时：电脑 ── USB 数据线 ── 开发板 UART
运行时：iPhone ── OTG 数据连接 ── 开发板原生 USB
                               │
                               └── Wi-Fi ── 电脑控制服务
```

首次烧录前断开手机，只把 UART 接到电脑。N16R8 的脚本默认参数：

| 项目 | 参数 |
|---|---|
| 板型 | ESP32-S3 / `esp32:esp32:esp32s3` |
| Flash / PSRAM | 16MB / OPI |
| 分区 | `app3M_fat9M_16MB` |
| CPU | 80MHz |
| USB 模式 | TinyUSB，原生 USB CDC 启动关闭 |
| 上传速度 | 460800 |
| 调试输出 | UART Serial，原生 USB 用于 HID |

macOS 查看并选择实际串口：

```bash
ls /dev/cu.*
./hardware/flash.sh /dev/cu.usbserial-XXXX
```

Linux 选择实际的 `/dev/ttyUSB*` 或 `/dev/ttyACM*`。串口名字由系统决定，示例不能照抄。找不到板子时检查数据线；上传无法进入引导模式时，可按住 BOOT，短按 RESET/EN，再松开 BOOT 后重试。

只编译、不上传：

```bash
./hardware/flash.sh --build-only
```

其他 ESP32-S3 板需要核对容量和 USB 引脚。可通过 `FQBN='匹配开发板的完整参数' ./hardware/flash.sh 实际串口` 覆盖默认板型；不要把 16MB/OPI 参数盲目用于其他板子。未引出原生 USB 的板不能按此方案直接接手机。

## 启动与连接手机

```bash
./run-local.sh
```

服务默认网页/API 为 `127.0.0.1:8890`，设备监听 TCP 7300。后端日志出现板子连接后，说明 Wi-Fi 指令链路连通；这不证明手机 USB HID 已就绪。

1. 断开电脑烧录线，使用兼容 OTG 数据连接把手机接到板子的原生 USB。
2. 保持手机解锁，打开“设置 → 辅助功能 → 触控 → 辅助触控”。
3. 检查是否出现圆形鼠标指针。自动隐藏后可以通过移动指针唤起。
4. 在手机“控制中心 → 屏幕镜像”选择 **ESP32 to iPhone**。
5. 浏览器打开 <http://127.0.0.1:8890/>，确认实时画面、控制器和指针。
6. 打开手动控制，选择 Calibrate。自动校准失败时，根据提示在镜像中点击实际指针位置完成校准。

后端会尝试维持设备唤醒，但不能保证手机或 USB 永远不休眠。不要同时连接多个手机或多个控制者。

## 安装 MCP 与验收

在仓库根目录执行：

```bash
codex mcp add iphone \
  --env IPHONE_AGENT_URL=http://127.0.0.1:8890 \
  --env IPHONE_MCP_ENABLE_DELEGATE=0 \
  -- "$PWD/run-mcp.sh"
```

其他客户端以及完整工具说明见 [MCP README](../mcp/README.md)。客户端要能看懂 MCP 图片，不能只读取 JSON 元数据。

最小验收任务：

> 检查状态，读取截图，只把指针移到屏幕中央，核对定位结果并停止，不点击。

预期：状态中 `device=true`、`screen=true`、`calibrated=true`；`iphone_point` 没有错误，返回实际指针位置与操作后图片。不要仅凭板子灯亮、手机有圆点或一次 ACK 就宣布全链路成功。

## 换 Wi-Fi 环境

当前没有配网门户，Wi-Fi 名称、密码与电脑 IP 在编译时写入固件。任意一项改变后，更新 `secrets.h`，UART 接回电脑重新烧录，再恢复手机连接。若三项都保持一致，则不用重刷。

MCP 与后端同机运行时，`IPHONE_AGENT_URL=http://127.0.0.1:8890` 无需因换 Wi-Fi 修改。不要把该本机地址填进开发板的 `SERVER_HOST`。

## 故障排查

| 现象 | 检查项 |
|---|---|
| UART 灯亮但无串口 | 换确认支持数据传输的线；供电正常不代表数据正常 |
| `device=false` | 2.4GHz Wi-Fi、电脑 IP、TCP 7300、防火墙、访客网络隔离 |
| `screen=false` | 手机解锁，停止镜像后重连，确认电脑与手机网络互通 |
| 镜像显示已连接但网页无画面 | 切换一次页面；仍无帧时重启后端再重连镜像，检查 UxPlay/GStreamer 日志 |
| `phone usb asleep` | 解锁手机，必要时拔插 OTG，检查原生 USB 口与辅助触控 |
| 点击被拒绝 | 检查指针是否可见、目标位置、动画和校准；重新看图，不自动盲点 |
| 过期/已消费的 `screen_id` | 重新观察，使用新凭据；不要自动重放可能已经发送的动作 |
| 中文只有拼音 | 确认中文拼音键盘、候选选择与 Space 键；查看 MCP 中文输入指引 |
| Home/Back 无效 | 机型手势差异，Home 键机型可使用辅助触控菜单 |
| 配件耗电量太大 | 检查 OTG 与电源；必要时使用支持外部供电的兼容适配器，软件配置不保证解决电流问题 |

## 运行配置与文件

默认直接控制不需要模型密钥，也不需要创建 `.env`。需要改端口、镜像名称或主动启用备用模型时，可以复制 `server/.env.example` 为 `server/.env` 并编辑，随后重启服务、重新连接镜像。

`run-local.sh` 默认网页绑定 `127.0.0.1`。设备 TCP 仍监听局域网，无认证；只在可信局域网使用，不要直接做公网端口映射。修改 `DEVICE_PORT` 还要同步修改固件。

校准与调试数据在 `server/.local-data/`，已被 Git 忽略。API Key、Wi-Fi 密码、运行截图和构建输出都不应提交仓库。
