export const discardMessage='작업 중인 굿즈는 저장되지 않습니다. 현재 사진과 시안, 대화, 고리 위치를 버리고 이동할까요?';
export async function replacePhoto<T>(hasWork:boolean,confirm:()=>boolean,prepare:()=>Promise<T>,discard:()=>Promise<void>):Promise<T|null>{
 if(hasWork&&!confirm())return null;
 const candidate=await prepare();
 await discard();return candidate;
}

export function generationParent(rows:readonly {id:string;status:string}[],selected:string|null):string|null{return rows.find(r=>r.id===selected&&r.status==='ready')?.id??null;}
export function workspaceKey(userId:string,visitKey:string){return `${userId}:${visitKey}`;}
