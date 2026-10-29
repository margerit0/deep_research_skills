# Python 3.13 free-threaded 与默认 GIL 构建对比

GIL 状态：3.13 起，free-threaded CPython 是实验性构建，GIL 被禁用，线程可在多核上并行；默认构建仍启用 GIL。[1] free-threaded 构建可在运行时选择启用 GIL，使用环境变量 PYTHON_GIL 或命令行选项 -X gil；导入未显式标记支持 free threading 的 C-API 扩展时，GIL 也可能自动启用并打印警告。[1] 可用 sys._is_gil_enabled() 查看运行进程 GIL 是否实际禁用，用 sysconfig.get_config_var("Py_GIL_DISABLED") 判断构建是否支持 free threading。[1] 两页未说明两个开关的具体取值、生效时机，也未说明能否在运行中的进程里任意切换。[1]

C 扩展兼容性：扩展模块必须显式表明支持 GIL 禁用，否则导入时警告并启用 GIL。[2] free-threaded 构建当前不支持 Limited C API 或 stable ABI；需要为它单独构建扩展；若使用 stable ABI，仍可为多个非 free-threaded 版本构建单个 wheel。[2] 直接访问可能被并发修改的结构体字段、使用不检查错误或加锁的访问宏、在包含对象可能并发修改时使用借用引用，均可能不安全；容器内部加锁，但 PyDict_Next 不加锁，需临界区保护；扩展内部状态可能需加锁。[2]

适用限制：free-threaded 模式实验性，预期一些 bug 和显著单线程性能损失。[1] 3.13 在 pyperformance 套件上单线程开销约 40%，主要因 specializing adaptive interpreter 被禁用；大部分时间在 C 扩展或 I/O 的程序影响较小。[1] 来源称未来目标为降到 10% 或以下，但非当前保证。[1] 3.13 free-threaded 构建会使某些对象 immortal，创建大量这些类型对象的应用可能增加内存使用，预计 3.14 处理；跨线程访问 frame 对象不安全，可能崩溃；跨线程共享同一迭代器一般不安全，可能重复或缺失元素或崩溃。[1]

建议（推断）：有多线程 CPU 密集需求者可小范围试用，但需接受实验性 bug 和单线程性能损失，并先确认依赖扩展已显式标记支持；未标记扩展会触发 GIL 自动启用，可能抵消并行收益。依赖 stable ABI 或大量 C 扩展内部状态的项目暂缓更稳妥。试用前应审查扩展内部状态和并发安全，不能仅凭导入、编译或性能实测判断安全。[1][2]

### 来源
[1] Python experimental support for free threading — Python 3.13.16 documentation, https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13.16 documentation, https://docs.python.org/3.13/howto/free-threading-extensions.html