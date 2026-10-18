Python 3.13 free-threaded 与默认 GIL 构建对比

GIL 状态：默认构建始终启用 GIL；free-threaded 构建自 3.13 起实验性禁用 GIL，使线程可在多核并行。[1] 它仍可在运行时启用 GIL，使用环境变量 PYTHON_GIL 或命令行选项 -X gil；导入未显式标记支持自由线程的 C-API 扩展时，GIL 也可能自动启用并警告。[1] 检查运行进程是否实际禁用 GIL 可用 sys._is_gil_enabled()。[1] 两页未说明 PYTHON_GIL 的取值、-X gil 的参数形式、生效时机及运行中切换限制。[1]

C 扩展兼容性：扩展必须显式声明支持 GIL 禁用，否则导入会警告并启用 GIL；未声明者即不兼容处理路径。[2] 多数 C API 线程安全，但直接访问可能被并发修改的结构字段、无锁访问器宏、借用引用在并发修改时并不安全。[2] free-threaded 构建当前不支持受限 C API 和稳定 ABI，需单独构建 wheel，Windows 从源码构建扩展还需手动定义 Py_GIL_DISABLED=1。[2]

适用限制：free-threaded 模式是实验性的，预期有 bug 和显著单线程性能损失。[1] 相比默认 GIL 构建，3.13 在 pyperformance 套件上单线程开销约 40%，C 扩展或 I/O 为主时影响较小；最大影响来自 specializing adaptive interpreter 被禁用。[1] 3.13 使部分对象 immortal，创建大量此类对象的应用可能增加内存占用。[1] 跨线程访问 frame 对象或共享同一迭代器对象一般不安全，可能崩溃或重复、缺失元素。[1] 内置 dict、list、set 的内部锁只是当前实现描述，不是并发修改保证，建议用 threading.Lock 等同步原语。[1]

试用建议（依据上述证据的推断）：若工作负载以多线程并行计算为主，且依赖扩展已显式声明支持自由线程，可在隔离环境试用，并用 sys._is_gil_enabled() 确认 GIL 实际状态；若扩展未标记，导入可能自动启用 GIL，需检查警告。试用前还应审查扩展内部共享状态是否需要加锁，不能仅凭声明支持、编译成功或性能实测判断安全。[2] 若单线程性能敏感或依赖稳定 ABI/受限 API，暂不宜作为生产默认。两页未给出完整兼容清单，需自行实测。

### 来源
[1] Python experimental support for free threading — Python 3.13.16 documentation，https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13.16 documentation，https://docs.python.org/3.13/howto/free-threading-extensions.html