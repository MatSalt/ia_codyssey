import type {UploadPreprocessing} from '../../api/types';

export interface PreparedFile { file:File; preprocessing?:UploadPreprocessing }
interface ImageInfo { width:number; height:number; orientation:number; date:string|null; timezone:string|null; omit:[number,number][] }
const ascii=(b:Uint8Array)=>String.fromCharCode(...b);
// Parsing is deliberately conservative. Unrecognized color/HDR metadata stays on the
// server path; this optimization must never change which input formats we accept.
function exif(bytes:Uint8Array, info:ImageInfo) {
 const d=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 const little=ascii(bytes.subarray(0,2))==='II';
 if(!little && ascii(bytes.subarray(0,2))!=='MM')throw Error('TIFF endian');
 const u16=(p:number)=>d.getUint16(p,little), u32=(p:number)=>d.getUint32(p,little);
 if(u16(2)!==42)throw Error('TIFF header');
 const visited=new Set<number>();
 function ifd(offset:number, nested=false) {
  if(offset<8 || visited.has(offset))throw Error('TIFF offset');visited.add(offset);
  const count=u16(offset);if(count>512 || offset+2+count*12+4>bytes.length)throw Error('TIFF bounds');
  const tags=new Set<number>();
  for(let i=0;i<count;i++) {
   const p=offset+2+i*12,tag=u16(p),type=u16(p+2),n=u32(p+4);
   if(tags.has(tag))throw Error('duplicate EXIF');tags.add(tag);
   if(tag===274 || tag===40961) {
    if(type!==3 || n!==1)throw Error('EXIF type');const value=u16(p+8);
    if(tag===274){if(value<1 || value>8)throw Error('orientation');info.orientation=value;}
    else if(value!==1)throw Error('non-sRGB');
   }
   if(tag===34665) {if(nested || type!==4 || n!==1)throw Error('EXIF pointer');ifd(u32(p+8),true);}
   if(tag===36867 || tag===36881) {
    if(type!==2 || n!==(tag===36867?20:7))throw Error('EXIF date');
    const start=u32(p+8);if(start+n>bytes.length || bytes[start+n-1]!==0)throw Error('EXIF bounds');
    const value=ascii(bytes.subarray(start,start+n-1));
    if(tag===36867){if(!/^\d{4}:\d{2}:\d{2} \d{2}:\d{2}:\d{2}$/.test(value))throw Error('date');info.date=value;}
    else {if(!/^[+-]\d{2}:\d{2}$/.test(value))throw Error('timezone');info.timezone=value;}
   }
  }
  // Embedded thumbnail is not used by the decoder after EXIF is stripped.
 }
 ifd(u32(4));
}
export function inspectImage(bytes:Uint8Array,mime:string):ImageInfo|null {
 try {
  const info:ImageInfo={width:0,height:0,orientation:1,date:null,timezone:null,omit:[]};
  const d=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);let hasExif=false;
  const readExif=(data:Uint8Array)=>{if(hasExif)throw Error('multiple EXIF');hasExif=true;exif(data,info);};
  if(mime==='image/jpeg') {
   if(d.getUint16(0)!==0xffd8)return null;
   let p=2,sof=false,sos=false;
   while(p<bytes.length) {
    const start=p;if(bytes[p++]!==255)return null;
    while(bytes[p]===255)p++;
    const marker=bytes[p++];if(marker===217)break;
    const len=d.getUint16(p);if(len<2 || p+len>bytes.length)return null;
    const body=bytes.subarray(p+2,p+len);
    if(marker===218){sos=true;break;}
    if(marker===192 || marker===194) {
     if(sof || body[0]!==8 || body[5]!==3)return null;sof=true;
     info.height=d.getUint16(p+3);info.width=d.getUint16(p+5);
    } else if(marker===225) {
     if(ascii(body.subarray(0,6))!=='Exif\0\0')return null;
     readExif(body.subarray(6));info.omit.push([start,p+len]);
    } else if(marker===224) {if(ascii(body.subarray(0,5))!=='JFIF\0')return null;}
    else if(![196,219,221].includes(marker))return null;
    p+=len;
   }
   if(!sof || !sos)return null;
  } else if(mime==='image/png') {
   if(ascii(bytes.subarray(0,8))!=='\x89PNG\r\n\x1a\n')return null;
   let p=8,ihdr=false,idat=false,end=false;
   while(p+12<=bytes.length) {
    const n=d.getUint32(p),name=ascii(bytes.subarray(p+4,p+8));if(p+12+n>bytes.length)return null;
    const start=p+8;
    if(name==='IHDR') {
     if(ihdr || p!==8 || n!==13)return null;ihdr=true;
     info.width=d.getUint32(start);info.height=d.getUint32(start+4);
     if(bytes[start+8]>8 || ![0,2,3,4,6].includes(bytes[start+9]) || bytes[start+10]!==0 || bytes[start+11]!==0)return null;
    } else if(name==='eXIf'){readExif(bytes.subarray(start,start+n));info.omit.push([p,p+12+n]);}
    else if(name==='gAMA'){if(n!==4 || d.getUint32(start)!==45455)return null;}
    else if(name==='cHRM') {
     if(n!==32 || [31270,32900,64000,33000,30000,60000,15000,6000].some((v,i)=>d.getUint32(start+i*4)!==v))return null;
    } else if(name==='sRGB'){if(n!==1 || bytes[start]>3)return null;}
    else if(name==='IDAT')idat=true;
    else if(name==='IEND'){if(n!==0 || p+12!==bytes.length)return null;end=true;break;}
    else if(!['PLTE','tRNS','pHYs','tIME'].includes(name))return null;
    p+=12+n;
   }
   if(!ihdr || !idat || !end)return null;
  } else return null;
  if(!info.width || !info.height || info.width*info.height>12_000_000)return null;
  return info;
 } catch {return null;}
}
export function resizeDimensions(width:number,height:number):[number,number] {
 const scale=Math.min(1,4096/Math.max(width,height));
 return [Math.max(1,Math.round(width*scale)),Math.max(1,Math.round(height*scale))];
}
async function prepare(file:File,signal:AbortSignal):Promise<PreparedFile> {
 const original={file};let bitmap:ImageBitmap|undefined,canvas:HTMLCanvasElement|undefined;
 try {
  signal.throwIfAborted();
  if(!['image/jpeg','image/png'].includes(file.type) || file.size>20*1024*1024 ||
    typeof createImageBitmap!=='function' || typeof document==='undefined')return original;
  const bytes=new Uint8Array(await file.arrayBuffer());signal.throwIfAborted();
  const info=inspectImage(bytes,file.type);if(!info)return original;
  // Strip EXIF before decoding so browser-specific auto-orientation cannot apply twice.
  const pieces:BlobPart[]=[];let start=0;
  for(const [from,to] of info.omit){pieces.push(file.slice(start,from));start=to;}pieces.push(file.slice(start));
  bitmap=await createImageBitmap(new Blob(pieces,{type:file.type}));signal.throwIfAborted();
  if(bitmap.width!==info.width || bitmap.height!==info.height)return original;
  const rotated=info.orientation>=5;
  const originalWidth=rotated?info.height:info.width,originalHeight=rotated?info.width:info.height;
  const [width,height]=resizeDimensions(originalWidth,originalHeight);
  canvas=document.createElement('canvas');canvas.width=width;canvas.height=height;
  const ctx=canvas.getContext('2d');if(!ctx)return original;
  const matrices:number[][]=[[1,0,0,1,0,0],[-1,0,0,1,width,0],[-1,0,0,-1,width,height],[1,0,0,-1,0,height],
   [0,1,1,0,0,0],[0,1,-1,0,width,0],[0,-1,-1,0,width,height],[0,-1,1,0,0,height]];
  const m=matrices[info.orientation-1];ctx.transform(m[0],m[1],m[2],m[3],m[4],m[5]);
  ctx.drawImage(bitmap,0,0,rotated?height:width,rotated?width:height);
  const blob=await new Promise<Blob|null>(resolve=>canvas!.toBlob(resolve,'image/webp',.9));signal.throwIfAborted();
  if(!blob || blob.type!=='image/webp' || !blob.size || blob.size>=file.size)return original;
  const header=new Uint8Array(await blob.slice(0,12).arrayBuffer());signal.throwIfAborted();
  if(ascii(header.subarray(0,4))!=='RIFF' || ascii(header.subarray(8,12))!=='WEBP')return original;
  return {file:new File([blob],file.name.replace(/\.[^.]*$/,'')+'.webp',{type:'image/webp',lastModified:file.lastModified}),
   preprocessing:{version:1,original_width:originalWidth,original_height:originalHeight,captured_at_raw:info.date,captured_timezone:info.timezone}};
 } catch {signal.throwIfAborted();return original;}
 finally {bitmap?.close();if(canvas){canvas.width=0;canvas.height=0;}}
}
// No parallel decoders: one <=12MP bitmap/canvas is live at a time. File objects
// returned here are retained by the upload intent, including all PUT retries.
export async function prepareFiles(files:readonly File[],signal:AbortSignal,onProgress?:(name:string)=>void):Promise<PreparedFile[]> {
 const prepared:PreparedFile[]=[];
 for(const file of files){signal.throwIfAborted();onProgress?.(file.name);prepared.push(await prepare(file,signal));}
 signal.throwIfAborted();return prepared;
}
