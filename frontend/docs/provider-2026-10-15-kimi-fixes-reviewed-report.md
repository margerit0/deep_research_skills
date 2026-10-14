# Python 3.13 free-threaded CPython 与默认 GIL 构建对比报告

## 一、GIL 状态

Python 3.13 提供实验性 free-threaded 构建，GIL 被禁用，线程可在多核上并行运行；默认构建保持 GIL 启用 [1]。安装途径包括官方 macOS/Windows 安装程序的可选二进制，源码构建则用 `--disable-gil` 选项 [1]。运行时开关：free-threaded 构建可通过环境变量 `PYTHON_GIL` 或命令行选项 `-X gil` 在启动时以启用 GIL 的方式运行；两页未展开其具体取值语义，也未说明运行中可动态切换——**官方指南未说明** [1]。检查方式：`sys._is_gil_enabled()` 可检查运行进程中 GIL 是否实际禁用 [1]。

## 二、C 扩展兼容性

扩展必须显式声明支持在 GIL 禁用下运行；未声明支持的扩展导入时会发出警告并在运行时自动启用 GIL，这是该特定路径的行为，两页未说明其他加载失败的一般处理方式——**证据不足** [1][2]。但声明支持并针对该构建重新编译不代表线程安全适配完成：官方要求审查扩展内部共享状态（如全局缓存、全局状态）的并发访问，必要时加锁或改用线程局部存储 [2]。若包含对象被并发修改，相关借用引用 API 可能不安全，应换用强引用版本 [2]。该构建目前不支持 Limited C API 和稳定 ABI [2]。

## 三、适用限制与建议

官方定性为**实验性**，"预计会有 bug 和显著的单线程性能损失" [1]。3.13 在 pyperformance 套件上单线程开销约 40%，主因是自适应解释器被禁用；主要耗时于 C 扩展或 I/O 的程序受影响较小；10% 或更低是该文档所述的未来目标，并非已兑现保证 [1]。其他已知限制：部分对象被永生化、永不释放，可能增加内存占用；跨线程访问 frame 对象不安全、可能崩溃；多线程共享同一迭代器不安全 [1]。生产使用方面，两页仅强调实验性质与风险，未给出明确禁令或支持承诺——**官方指南未说明**。依据上述来源建议：适合评估多线程 CPU 密集型场景；用 `sys._is_gil_enabled()` 验证 GIL 状态，必要时以 `PYTHON_GIL`/`-X gil` 回退；依赖未声明支持的 C 扩展时会自动启用 GIL 并告警，并行收益可能因此受限，需实测性能与内存影响 [1][2]。

### 来源

[1] Python experimental support for free threading: https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading: https://docs.python.org/3.13/howto/free-threading-extensions.html