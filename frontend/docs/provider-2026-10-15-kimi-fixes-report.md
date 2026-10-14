# Python 3.13 free-threaded CPython 与默认 GIL 构建对比报告

## 一、GIL 状态差异

Python 3.13 提供实验性的 free-threaded 构建，其中 GIL 被禁用，线程可在多核 CPU 上并行运行；默认构建则保持 GIL 启用，行为与旧版一致 [1]。从源码构建需使用 configure 选项 `--disable-gil`，官方 macOS 和 Windows 安装程序也可选装 free-threaded 二进制 [1]。**运行时开关**：free-threaded 构建支持通过环境变量 `PYTHON_GIL` 或命令行选项 `-X gil` 在启动时重新启用 GIL [1]。**检查方式**：`python -VV` 与 `sys.version` 会包含 "experimental free-threading build" 字样；`sys._is_gil_enabled()` 可检查运行进程中 GIL 是否实际启用；`sysconfig.get_config_var("Py_GIL_DISABLED")` 为 1 表示构建支持 free threading [1]。

## 二、C 扩展兼容性

扩展必须显式声明支持在 GIL 禁用下运行，否则导入时会发出警告并在运行时自动重新启用 GIL——即回退而非加载失败 [1][2]。声明方式：多阶段初始化的扩展在模块定义中添加 `{Py_mod_gil, Py_MOD_GIL_NOT_USED}` 槽；单阶段初始化的扩展调用 `PyUnstable_Module_SetGIL(m, Py_MOD_GIL_NOT_USED)`，需用 `#ifdef Py_GIL_DISABLED` 保护 [2]。扩展需针对 free-threaded 构建单独编译（wheel 以 `t` 后缀标识），且该构建目前不支持 Limited C API 和稳定 ABI [2]。

## 三、适用限制

官方明确定性为**实验性**，"预计会有 bug 和显著的单线程性能损失" [1]。3.13 在 pyperformance 套件上单线程开销约 40%，主因是自适应解释器（PEP 659）被禁用，官方目标是在未来版本降至 10% 或更低 [1]。其他已知限制：部分对象被永生化、永不释放，可能增加内存占用；跨线程访问 frame 对象不安全、可能崩溃；多线程共享同一迭代器不安全 [1]。关于生产环境使用，两页仅强调实验性质与上述风险，未给出明确的生产禁令或支持承诺——**官方指南未说明**。

## 四、试用建议

适合评估多线程 CPU 密集型场景；用 `sys._is_gil_enabled()` 验证 GIL 状态，必要时用 `PYTHON_GIL`/`-X gil` 回退；依赖未适配 C 扩展时会自动启用 GIL 并告警，需实测性能与内存影响 [1][2]。

### 来源

[1] Python experimental support for free threading: https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading: https://docs.python.org/3.13/howto/free-threading-extensions.html