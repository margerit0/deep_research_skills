Python 3.13 free-threaded 与默认 GIL 构建对比

GIL 状态：默认构建启用 GIL。free-threaded 构建自 3.13 起实验性支持禁用 GIL，可并行利用多核，但并非所有软件自动受益。[1] 它支持运行时重新启用 GIL，途径是环境变量 PYTHON_GIL 或命令行选项 -X gil；两页未说明其取值、生效时机及是否可在进行中的过程里任意切换。[1] 导入未显式标记支持 free threading 的 C-API 扩展时，GIL 可能自动启用并打印警告。[1] 可用 sys._is_gil_enabled() 检查运行进程是否实际禁用 GIL；构建是否支持 free threading 则用 sysconfig.get_config_var("Py_GIL_DISABLED") 判断。[1]

C 扩展兼容性：扩展模块必须显式声明支持 GIL 禁用，否则导入会警告并启用 GIL；具体声明接口见来源。[2] free-threaded 构建当前不支持 Limited C API 或 stable ABI，C 扩展需专门构建，wheel、共享库和二进制带 t 后缀。[2] 即使声明支持，扩展此前由 GIL 保护的内部状态仍可能需加锁或改为线程本地；缓存和全局状态是常见风险点。[2]

适用限制：free-threaded 模式是实验性的，预期有 bug 和显著单线程性能损失。[1] 3.13 在 pyperformance 套件上，相比默认 GIL 构建，单线程开销约 40%；大部分时间在 C 扩展或 I/O 的程序影响较小。[1] 内置 dict、list、set 使用内部锁，但来源称这只是当前实现描述，不是当前或未来行为保证，建议用 threading.Lock 等同步原语。[1] 跨线程访问 frame 对象不安全，可能崩溃；sys._current_frames() 一般不安全。[1] 多线程共享同一迭代器对象一般不安全，可能重复、缺失元素或崩溃。[1] 3.13 free-threaded 还会使部分对象 immortal，创建许多此类对象可能增加内存使用。[1]

建议（推断）：若工作负载是 CPU 密集多线程，且能接受实验性风险，可在隔离环境试用 free-threaded 构建；先检查扩展导入警告和 GIL 是否被启用，并用自身工作负载实测单线程与多线程表现。若依赖 stable ABI/Limited C API，或存在跨线程 frame、共享迭代器，当前限制可能不适合。扩展声明支持不等于安全：来源要求审查此前由 GIL 保护的内部状态并做必要适配；性能实测与并发正确性测试不能替代该审查。[1][2]

### 来源
[1] Python experimental support for free threading — Python 3.13.16 documentation, https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13.16 documentation, https://docs.python.org/3.13/howto/free-threading-extensions.html