# Free-threaded CPython 3.13 与默认 GIL 构建对比报告

## 一、GIL 状态

Python 3.13 起提供实验性的 free-threaded 构建，其中全局解释器锁（GIL）被禁用，线程可在多核 CPU 上真正并行运行；默认构建则始终启用 GIL [1]。官方 macOS 和 Windows 安装程序可选装 free-threaded 二进制，其他平台需用 `--disable-gil` 从源码构建 [1]。

**运行时开关方式**：free-threaded 构建可通过环境变量 `PYTHON_GIL` 或命令行选项 `-X gil` 在运行时重新启用 GIL；此外，导入未声明支持自由线程的 C 扩展时，GIL 会自动启用并发出警告 [1]。可通过 `sys._is_gil_enabled()` 检查运行时 GIL 状态，用 `sysconfig.get_config_var("Py_GIL_DISABLED")` 判断构建类型 [1]。`PYTHON_GIL` 的具体取值语义两页未说明。

## 二、C 扩展兼容性

这是试用的最大门槛。C 扩展必须**显式声明**支持 GIL 禁用模式，并针对 free-threaded 构建**专门重新编译** [2]：

- 多阶段初始化：在模块定义中添加 `Py_mod_gil` slot；
- 单阶段初始化：调用 `PyUnstable_Module_SetGIL()`，该函数仅存在于 free-threaded 构建，须用 `#ifdef Py_GIL_DISABLED` 保护 [2]。

**遇到不兼容扩展的处理办法**：导入未声明支持的扩展时会发出警告并自动回退启用 GIL，即并行收益归零；根本解决路径是改造扩展（加上述声明）并重新编译 [1][2]。此外，返回借用引用的 C API、直接访问对象字段等操作在并发下非线程安全，需开发者自行审查 [2]。

## 三、适用限制

- **实验性状态**：仍应预期 bug 和显著单线程性能损耗 [1]。
- **性能开销**：3.13 中单线程开销约 40%（因 PEP 659 特化解释器被禁用），官方目标在 3.14 降至 ≤10% [1]。
- **内存增长**：对象不朽化机制导致部分对象永不释放，预计 3.14 改善 [1]。
- **线程安全陷阱**：跨线程访问帧对象、多线程共享迭代器均不安全，可能崩溃；内置类型虽有内部锁，官方仍建议显式使用 `threading.Lock` [1]。

## 四、结论

想试用 free-threaded 构建的开发者：可用官方可选二进制或 `--disable-gil` 源码构建，用 `sys._is_gil_enabled()` 验证状态；GIL 可随时经 `PYTHON_GIL`/`-X gil` 或导入不兼容扩展而回退启用。依赖大量 C 扩展的项目应先确认扩展已适配并重新编译，否则等同退回 GIL 模式。鉴于约 40% 单线程开销与实验性状态，保守生产场景宜等待 3.14 的改进 [1][2]。

### 来源

[1] Python experimental support for free threading — Python 3.13 documentation: https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — Python 3.13 documentation: https://docs.python.org/3.13/howto/free-threading-extensions.html