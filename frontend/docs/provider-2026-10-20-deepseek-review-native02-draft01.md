标题：Python 3.13 free-threaded 与默认 GIL 构建对比

GIL 状态：free-threaded 构建从 3.13 起实验性支持禁用 GIL，默认 GIL 构建则启用 GIL。[1] free-threaded 构建可在运行时选择启用 GIL，途径是环境变量 PYTHON_GIL 或命令行选项 -X gil；导入未显式标记支持 free threading 的 C-API 扩展时，GIL 也可能自动启用并打印警告。[1] 可用 sys._is_gil_enabled() 检查运行进程是否实际禁用 GIL；判断构建是否支持 free threading 推荐用 sysconfig.get_config_var("Py_GIL_DISABLED")。[1] 限定来源未说明这两个开关的具体取值、生效时机，也未说明能否在运行中的进程里任意切换。[1]

C 扩展兼容性：扩展模块需显式表明支持 GIL 禁用，否则导入会警告并在运行时启用 GIL。[1][2] 若希望真正禁用 GIL 运行，还需处理 C API 的线程安全例外，包括并发修改的结构字段、访问器宏和借用引用，以及不锁字典的 PyDict_Next。[2] free-threaded 构建当前不支持 Limited C API 和 stable ABI，需单独构建扩展，产物带 t 后缀。[2]

适用限制：free-threaded 模式是实验性的，预期有 bug 和显著单线程性能损失。[1] 3.13 在 pyperformance 套件上，相比默认 GIL 构建，单线程开销约 40%；主要因 specializing adaptive interpreter 被禁用；大部分时间在 C 扩展或 I/O 的程序影响较小。[1] 此外，创建大量模块级函数、方法描述符、代码对象、模块及其字典、类等对象的应用可能因 immortalization 增加内存使用；跨线程访问帧对象不安全，可能崩溃；多线程共享同一迭代器一般不安全，可能重复或缺失元素，甚至崩溃。[1]

建议：依据上述证据，若工作负载以多线程并行计算为主，且能接受实验性 bug 和单线程开销，可在隔离环境试用 free-threaded 构建；但需先确认关键 C 扩展已显式标记支持，否则导入会启用 GIL，无法获得禁用 GIL 的运行状态。[1][2] 若依赖稳定 ABI 或受限 C API，或无法单独构建带 t 后缀扩展，则当前不适合。[2] 试用时用 sys._is_gil_enabled() 确认运行进程 GIL 状态，并完成扩展内部状态审查；不能仅凭声明支持或编译成功，并发正确性测试也不能替代该审查。[1][2]

### 来源
[1] Python experimental support for free threading — Python 3.13.16 documentation，https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13.16 documentation，https://docs.python.org/3.13/howto/free-threading-extensions.html