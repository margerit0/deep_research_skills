# 独立预览资源

这些文件用于生成本地 HTML 预览，不是正式前端的应用依赖。

| 资源 | 归档版本与来源 | 许可证 |
| --- | --- | --- |
| `floating-ui.core.umd.min.js` | [@floating-ui/core 1.7.3](https://cdn.jsdelivr.net/npm/@floating-ui/core@1.7.3/dist/floating-ui.core.umd.min.js) | [MIT](floating-ui-core.LICENSE) |
| `floating-ui.dom.umd.min.js` | [@floating-ui/dom 1.7.4](https://cdn.jsdelivr.net/npm/@floating-ui/dom@1.7.4/dist/floating-ui.dom.umd.min.js) | [MIT](floating-ui-dom.LICENSE) |
| 预览 HTML 中内嵌的 Lucide | 来自校对环境已安装的 Lucide 1.8.0 UMD 包 | [ISC 及上游声明](lucide.LICENSE) |

Lucide 已内嵌在完整预览中，无需额外下载即可查看。重新生成时，校对脚本从 `ATLAS_LUCIDE_UMD` 或本机已有的 Node.js 依赖目录读取图标库。
