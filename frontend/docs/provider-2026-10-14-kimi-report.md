# Python 3.13 自由线程 CPython 与默认 GIL 构建对比报告

## 一、GIL 状态

自 Python 3.13 起，CPython 提供**实验性**的自由线程（free-threaded）配置，可在禁用全局解释器锁（GIL）的情况下运行；默认构建不受影响，仍保留 GIL [1][2]。启用方式为使用 `--disable-gil` 构建选项编译解释器，或安装标记为 free-threaded 的实验性构建 [1][2]。自由线程构建还支持在运行时通过环境变量 `PYTHON_GIL` 或命令行选项 `-X gil` 选择性地重新启用 GIL [2]。

PEP 703 状态为 Final，于 2023 年 10 月被指导委员会接受，但附带明确条件：推广必须渐进、尽量减少破坏，并保留在必要时完全回滚的可能性，即该特性**可能变化** [1]。PEP 703 提出的 2028–2030 年默认禁用 GIL 的长期目标属提案规划，**可能变化** [1]。

## 二、C 扩展兼容性

`--disable-gil` 构建与标准 CPython ABI **不兼容**，C 扩展必须针对自由线程构建专门重新编译 [1][3]。扩展模块必须显式声明支持无 GIL 运行，否则导入时会发出警告并在运行时启用 GIL [3]。声明方式：多阶段初始化扩展添加 `Py_mod_gil` 槽位；单阶段初始化扩展调用 `PyUnstable_Module_SetGIL()`，并需用 `#ifdef Py_GIL_DISABLED` 保护 [3]。Windows 上 `Py_GIL_DISABLED` 宏不会自动定义，须编译时显式指定 [3]。

线程安全方面，大部分 C API 是线程安全的，但直接访问可能被并发修改的对象字段、以及返回借用引用的函数在容器被并发修改时**不是线程安全的** [3]。依赖 GIL 保护全局状态的扩展需添加显式锁 [1]。

## 三、适用限制

该模式为**实验性**，官方明确说明其"存在一些预期的 bug 和显著的单线程性能损失" [2]。指导委员会保留完全回滚的权利，未来形态**可能变化** [1]。

**不确定之处**：运行时重新启用 GIL 后是否仍属实验性，官方来源**未明确**；自由线程模式的具体适用场景边界或禁用情形清单，官方文档**未给出明确列举，证据不足**。

### 来源

[1] PEP 703 – Making the Global Interpreter Lock Optional in CPython: https://peps.python.org/pep-0703
[2] What's New In Python 3.13 — Free-threaded CPython: https://docs.python.org/3.13/whatsnew/3.13.html#free-threaded-cpython
[3] C API Extension Support for Free Threading — Python 3.13 documentation: https://docs.python.org/3.13/howto/free-threading-extensions.html