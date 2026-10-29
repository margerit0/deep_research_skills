# Python 3.13 free-threaded 与默认 GIL 构建对比

**GIL 状态**：3.13 起 CPython 提供实验性 free threading 构建，GIL 被禁用，线程可在多核并行 [1]。该构建仍可在运行时启用 GIL，用环境变量 PYTHON_GIL 或命令行选项 -X gil [1]；来源未说明这两个选项的取值写法，也未说明能否在进程运行中随时切换。sys._is_gil_enabled() 可查运行进程中 GIL 是否实际禁用；sysconfig.get_config_var("Py_GIL_DISABLED") 为 1 表示构建支持 free threading，这是构建配置决策的推荐机制 [1]。

**C 扩展兼容性**：扩展模块须显式声明支持 GIL 禁用，否则导入时打印警告并在运行时启用 GIL [1][2]。声明方式随初始化方式而异：多阶段初始化加 Py_mod_gil 槽，单阶段初始化调用 PyUnstable_Module_SetGIL()，后者仅在 free-threaded 构建中定义 [2]。直接访问可能被并发修改的结构体字段、PyList_GET_ITEM 等访问宏、容器被并发修改时返回借用引用的 API 均不线程安全；PyDict_Next() 不加锁，需用临界区保护 [2]。该构建要求 Python 对象只能用 object 域分配，此前只是最佳实践 [2]。扩展须专门为该构建编译，产物带 t 后缀；目前不支持 Limited C API 与 stable ABI [2]。

**适用限制**：该模式是实验性的，预期有 bug 和显著单线程性能损失 [1]。3.13 在 pyperformance 套件上单线程开销约 40%，主因是特化自适应解释器被禁用；大部分时间花在 C 扩展或 I/O 的程序受影响较小 [1]。3.13 会将模块级函数、方法描述符、代码对象、模块对象及其字典、类等对象 immortal 化，大量创建这些对象的应用可能内存占用增加 [1]。跨线程访问 frame 对象不安全，可能崩溃；多线程共享同一迭代器对象通常不安全，可能重复或丢失元素甚至崩溃 [1]。内置 dict、list、set 的内部锁只是当前实现的描述，不构成保证，建议改用 threading.Lock 等同步原语 [1]。

**建议（推断）**：若程序以多线程并行计算为主、依赖扩展已声明支持 free threading，可试用该构建，并用 PYTHON_GIL 或 -X gil 对照测试；扩展未声明支持时导入会回退启用 GIL 并告警，并行收益不成立。试用前应确认扩展已为 t 后缀构建单独编译，并审查其内部缓存与全局状态的加锁情况 [2]。单线程性能敏感或依赖 stable ABI 的场景暂不宜作为默认选择。

### 来源
[1] Python experimental support for free threading — https://docs.python.org/3.13/howto/free-threading-python.html
[2] C API Extension Support for Free Threading — https://docs.python.org/3.13/howto/free-threading-extensions.html