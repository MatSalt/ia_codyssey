import type {GenerationView,TaskView} from '../../api/types';
export type StepStatus='pending'|'running'|'complete'|'attention';
export interface GenerationStep {label:string;status:StepStatus}
function status(tasks:TaskView[]):StepStatus {if(tasks.some(t=>['failed','unknown','cancelled'].includes(t.status)))return 'attention';if(tasks.length&&tasks.every(t=>t.status==='succeeded'))return 'complete';if(tasks.some(t=>['running','retry_wait','succeeded'].includes(t.status)))return 'running';return 'pending';}
export function generationSteps(view:GenerationView):GenerationStep[]{const tasks=view.pages.flatMap(p=>p.tasks);return [{label:'사진 준비',status:'complete'},{label:'사진첩 만들기',status:status(tasks.filter(t=>t.stage!=='optimize'))},{label:'마무리',status:status(tasks.filter(t=>t.stage==='optimize'))}];}
