import {GlassButton} from '../../components/ui/GlassButton';
import { useQuery } from '@tanstack/react-query';
import { api, errorText } from '../../api/client';
import type { Config } from '../../api/types';
import { useUploads } from './useUploads';
import { canSelectFiles } from './selection';
import { useState } from 'react';
export function UploadPanel({albumId,userId,refresh}: {albumId:string;userId:string;refresh:()=>Promise<unknown>}) {
 const config=useQuery({queryKey:['client-config',userId],queryFn:({signal})=>api<Config>('/client-config',{signal})});
 const upload=useUploads(albumId,userId,refresh); const [validation,setValidation]=useState('');
 return <section className="upload-panel" aria-label="사진 추가와 전송"><label className="file-label">＋ 사진 추가<input type="file" multiple disabled={!config.data || upload.busy || upload.locked} accept={config.data ? [...config.data.upload_allowed_extensions,...config.data.upload_allowed_mimes].join(',') : undefined} onChange={e=>{
 const files=Array.from(e.target.files ?? []); const c=config.data!;
 if(!canSelectFiles(files,c)){setValidation('지원하는 형식·용량·사진 수를 확인해 주세요. 선택한 파일은 전송하지 않았습니다.');return;}
 setValidation('');upload.select(files);
 }}/></label>{upload.files.length>0 && <><ul className="file-list">{upload.files.map((f,i)=><li key={i}>{f.name} <span>{(f.size/1024/1024).toFixed(1)}MiB</span></li>)}</ul><GlassButton disabled={upload.busy} onClick={()=>void upload.send()}>{upload.busy?'전송 중…':upload.locked?'같은 업로드 다시 시도':`${upload.files.length}장 업로드`}</GlassButton></>}{upload.locked && !upload.busy && <button className="secondary" onClick={()=>{if(window.confirm('이 요청의 재시도를 중단할까요? 이미 예약된 페이지는 아래에서 확인하고 삭제해 주세요.'))upload.discard();}}>재시도 중단</button>}<details className="upload-help"><summary>지원 형식과 업로드 안내</summary><p className="hint">JPEG · PNG · WebP · HEIF/HEIC, 한 장 최대 20MiB.</p><p className="hint">선택한 로컬 파일은 새로고침 후 복원되지 않습니다. HEIC도 서버 검증 후 미리보기가 표시됩니다. HDR/10bit 사진은 아직 지원하지 않습니다.</p></details>{upload.progress && <p role="status" aria-live="polite">{upload.progress}</p>}{(validation || upload.error) && <p role="alert">{validation || upload.error}</p>}{config.error && <p role="alert">{errorText(config.error)} <button onClick={()=>void config.refetch()}>설정 다시 불러오기</button></p>}</section>;
}
