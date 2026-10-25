import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..')
const html=`<!doctype html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>星图工作台 · 产品演示</title>
<style>body{margin:40px auto;max-width:1200px;padding:0 24px;background:#f5f5f7;color:#202126;font:16px/1.8 "Segoe UI","Microsoft YaHei",sans-serif}h1{font-size:34px}p{color:#626670}video{width:100%;border-radius:18px;background:#eee}a{color:#005bbb;text-decoration:none}footer{margin:35px 0;padding:18px;border-top:1px solid #ddd}.facts{display:flex;gap:22px;flex-wrap:wrap}#playback-status{min-height:1.8em;font-size:14px}</style></head>
<body><h1>星图工作台 · 产品演示</h1><p>让研究的每一步，看得见。</p>
<video id="movie" controls preload="none" poster="poster.png"><source src="product-demo.mp4" type="video/mp4"></video>
<p id="playback-status" role="status">正在准备播放…</p>
<p class="facts"><span>12 秒</span><span>1920 × 1080</span><span>30 fps</span><span>代码合成配乐 · 120 BPM</span></p>
<p><a href="product-demo.mp4" download>保存 MP4</a>　·　<a href="check-sheet.png">成片检查图</a>　·　<a href="verification.md">检查记录</a>　·　<a href="reproduce.md">复现说明</a></p>
<footer>合成演示 · 流程已压缩。仅使用项目内置原创合成数据；演示时长不代表真实产品响应速度。</footer>
<script>
const movie=document.getElementById('movie'),status=document.getElementById('playback-status');movie.controls=false;
(async()=>{
  try{
    const response=await fetch('product-demo.mp4');if(!response.ok)throw new Error('Video fetch failed');
    const blob=await response.blob();const mediaUrl=URL.createObjectURL(blob);
    movie.src=mediaUrl;movie.dataset.fullyBuffered='true';movie.preload='auto';movie.load();
    await new Promise(resolve=>movie.readyState>=4?resolve():movie.addEventListener('canplaythrough',resolve,{once:true}));
    addEventListener('pagehide',()=>URL.revokeObjectURL(mediaUrl),{once:true});
  }catch{
    movie.preload='auto';movie.load();
  }
  movie.controls=true;status.textContent='已就绪 · 点击播放可听配乐';
})();
</script></body></html>`
await fs.writeFile(path.join(root,'final/index.html'),html,'utf8')
console.log('Built the fully buffered final player.')
