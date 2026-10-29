"""Record source provenance, actual layout and the scope of this pending preview."""
from pathlib import Path
import hashlib
import json
import subprocess
from timeline import load_plan, write_json
ROOT=Path(__file__).resolve().parent.parent
REPO=ROOT.parents[1]
plan=load_plan(ROOT/'plan.json')
audit=json.loads((ROOT/'cache/capture-audit.json').read_text(encoding='utf-8'))
data=json.loads((ROOT/'cache/source-texts.json').read_text(encoding='utf-8'))
assert audit['planSha256']==plan['planSha256']
paths=[str(p.relative_to(REPO)).replace('\\','/') for p in (REPO/'frontend/src').rglob('*') if p.is_file() and p.suffix in ('.ts','.tsx','.css')]
paths+=['README.md','docs/skill-evolution.md','docs/maintenance.md','docs/architecture-decisions.md','src/deep_research/skill_evolution.py','src/deep_research/skill_evolution_runner.py','src/deep_research/skill_evolution_models.py','src/deep_research/skill_evolution_store.py']
paths += [str(p.relative_to(REPO)).replace('\\','/') for p in (ROOT/'source').iterdir() if p.is_file()]
sources=[{'path':p,'sha256':hashlib.sha256((REPO/p).read_bytes()).hexdigest()} for p in sorted(paths)]
write_json(ROOT/'brief.json',{
 'version':'2026-10-29-v4','state':'pending','date':'2026-10-29','timezone':'Asia/Shanghai','planSha256':plan['planSha256'],
 'product':'星图工作台 / Deep Research Agent',
 'audience':{'text':'需要可追溯研究流程与可验证方法论改进的开发者、研究工作流使用者','basis':'根据 README 与本次需求推断，随分镜确认'},
 'value':'研究过程可见；Skill 修订由失败证据驱动，经独立验证后由操作者采纳。',
 'tagline':{'text':'让研究的每一步，看得见。','source':'现有 v3 品牌文案'},
 'scenario':{'type':'existing_original_synthetic','source':'frontend/src/data/demo.ts 与 mock.ts','question':data['prompt'],'clarification':data['demoReply'],'report':data['demoReport'],'reportKey':'demoReport','citations':[],'sourceTitles':[],'sourceExcerpts':[],'limitation':'现有合成报告没有编号引用或真实来源原文；仅展示同一演示路径，不新增引用操作。'},
 'evolution':{'type':'documentation_based_mechanism_animation','dataPolicy':'没有新增优化实验、假失败样本、候选正文、评估分数或提升结论。候选 A/B 仅标识功能允许的分支，并非实验产物。未使用单元 fixture 作为实验结果。',
  'facts':[
   {'shot':'diagnose','source':'docs/skill-evolution.md / 证据诊断；src/deep_research/skill_evolution.py / validate_diagnosis','text':'只有内容归因成立且证据充分时才允许生成修订'},
   {'shot':'candidate','source':'docs/skill-evolution.md；src/deep_research/skill_evolution.py / Manifest, Candidate','text':'首版仅 product-comparison；每实验最多一轮、两个候选；保存正文、diff、理由与预期改善'},
   {'shot':'validate','source':'docs/skill-evolution.md / 冻结、最终验证、晋升和回退；skill_evolution_runner.py','text':'开发、选择、最终集分开；选择集配对通过后冻结一个候选，再读最终集；最终反馈不回流'},
   {'shot':'release','source':'docs/skill-evolution.md；src/deep_research/skill_evolution_store.py / promote, rollback','text':'默认停在报告；门槛通过后显式晋升；归档旧版，重启生效；回退核对修订'},
  ],'limitations':['后端 CLI、SQLite 和 Markdown 报告，不是新增前端界面','尚无真实模型优化实验与效果提升结论','研究员 compressed_research 的评估不直接代表 final_report 质量','缺失运行、反馈或完整成本不能冻结或晋升']},
 'coverage':[
  {'item':'产品全貌','decision':'show','shotIds':['question'],'evidence':'0–2 秒完整原生工作台；preview/frame-0045.png','reason':'建立产品上下文'},
  {'item':'关键配置','decision':'show','shotIds':['skills'],'evidence':'preview/frame-0150.png、frame-0210.png；四次原生回调核验','reason':'展开 Skills 菜单并选中产品对比；不展开额外模型配置，沿用内置模拟配置'},
  {'item':'核心操作','decision':'show','shotIds':['parallel','inspect','diagnose','candidate','validate'],'evidence':'workflow.mp4、evolution.mp4','reason':'研究自动推进、真实节点检查器；优化部分用明确标注的机制图解'},
  {'item':'结果','decision':'show','shotIds':['report','release','brand'],'evidence':'frame-0435.png、frame-1125.png、frame-1215.png','reason':'原合成报告、采纳决策、品牌收尾；原文核对不适用，合成数据无引用原文'},
 ],
 'layout':{'measured':audit['layouts'][0]['nativeLayout'],'videoPixels':[1920,1080],'nativeCSSSource':['frontend/src/apple.css','frontend/src/app.css','frontend/src/demo.css'],'newBoard':[570,164,1272,814],'explanationFonts':{'headline':58,'description':23,'diagramHeading':29,'body':20},'nativeGraphSemantics':'原生节点、连接、返回回路与逐次调用时间线分别保留；节点检查器触发真实组件回调','runtimeEvidence':'cache/capture-audit.json；不是旧截图'},
 'spec':{'video':plan['video'],'audio':plan['audio'],'recommendation':'42 秒；前16秒复用现有产品路径，新机制23秒，品牌3秒。为每个新增阶段保留稳定阅读区间。','preview':'两段无声小样；正式配乐和完整 MP4 等待本版确认'},
 'provenance':{'repositoryCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip(),'nativeAdapter':'从 v3 源码复制至本版并切换统一派生时间轴；本版运行不依赖旧版目录','timelineCompiler':'复制 product-demo-video/scripts/timeline.py；无需安装新依赖'},
 'sources':sources,'restrictions':{'modelCalls':0,'searchCalls':0,'realUserData':False,'publication':False,'commitsCreated':False},
})
print('brief.json recorded')
