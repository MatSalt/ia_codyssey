import type {GenerationStep} from './steps';
const labels={pending:'대기',running:'진행 중',complete:'완료',attention:'확인 필요'};
export function GenerationSteps({steps}:{steps:GenerationStep[]}){return <ol className="generation-steps">{steps.map(s=><li key={s.label}><span>{s.label}</span><span className={`step-symbol step-${s.status}`} aria-label={labels[s.status]}>{s.status==='complete'?'✓':s.status==='attention'?'!':s.status==='running'?'◌':'○'}</span></li>)}</ol>;}
