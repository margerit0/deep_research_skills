**Python 3.13 free-threaded 与默认 GIL 构建对比**

Python 3.13 的 free-threaded 构建是实验性构建，禁用 GIL，目标是让线程在可用 CPU 核上并行；默认构建仍启用 GIL。[1] free-threaded 构建可在运行时通过环境变量 PYTHON_GIL 或命令行选项 -X gil 启用 GIL；来源未说明这两个开关的取值，也未说明能否在进程运行中任意切换。[1] 导入未显式标记支持 free threading 的 C-API 扩展模块时，GIL 可能自动启用并打印警告。[1] 可用 sys._is_gil_enabled() 检查运行进程是否实际禁用 GIL，用 sysconfig.get_config_var("Py_GIL_DISABLED") 判断构建是否支持 free threading，后者是构建配置决策的推荐机制。[1]

C 扩展兼容性方面，扩展模块必须显式表明支持禁用 GIL；否则导入会警告并在运行时启用 GIL。[2] 扩展需专门为 free-threaded 构建编译，wheel、共享库和二进制以 t 后缀标识；free-threaded 构建目前不支持 Limited C API 或 stable ABI，因此需单独构建 wheel；默认 GIL 构建可继续使用 stable ABI 为多个非 free-threaded 版本构建单个 wheel。[2]

适用限制：free-threaded 模式实验性，预期有 bug 和显著单线程性能损失。[1] 在 3.13 的 pyperformance 套件上，其单线程开销相对默认 GIL 构建约 40%；大部分时间在 C 扩展或 I/O 的程序受影响较小。[1] 跨线程访问 frame 对象不安全，可能导致程序崩溃；同一迭代器对象在多线程间共享通常不安全，可能重复、缺失元素或崩溃；模块级函数、方法描述符、代码对象、模块、类等对象会被 immortal 化，大量创建这些类型可能增加内存使用。[1]

试用建议（推断）：若需评估多核并行且能接受实验风险，可先小范围试用 free-threaded 构建，并用上述检查确认实际 GIL 状态；若依赖未声明支持 free threading 的 C 扩展，导入会警告并启用 GIL，可能抵消并行收益，应先确认扩展已显式支持并为 free-threaded 构建单独构建，且不依赖 Limited C API/stable ABI。否则默认 GIL 构建更稳妥。来源未说明 PYTHON_GIL 和 -X gil 的具体取值及运行中切换行为，需另行核实。

### 来源
[1] Python experimental support for free threading — Python 3.13.16 documentation. https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13.16 documentation. https://docs.python.org/3.13/howto/free-threading-extensions.html