import {GlassButton} from '../../../components/ui/GlassButton';
import {useLayoutEffect, useRef, useState} from 'react';
import type {PointerEvent} from 'react';
import {pickEdge} from './geometry';
import {CHARM_WIDTH, CHARM_HEIGHT, renderCharm} from './renderer';
import type {CharmGeometry} from './renderer';
import {createPreviewController, previewKey} from './preview';
import type {Placement, PreviewInput, PreviewState} from './preview';

type Result = {canvas: HTMLCanvasElement; geometry: CharmGeometry};
export type GoodsMockupProps = PreviewInput & {
  interactive?: boolean;
  className?: string;
  onChange?: (placement: Placement) => void;
  /** A pending/error notification invalidates any previously exportable preview. */
  onPreview?: (state: PreviewState<Result>) => void;
};
function loadImage(src: string, signal: AbortSignal): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.crossOrigin = 'anonymous';
    const cleanup = () => { image.onload = null; image.onerror = null; signal.removeEventListener('abort', abort); };
    const abort = () => { cleanup(); image.removeAttribute('src'); reject(new DOMException('Aborted', 'AbortError')); };
    image.onload = () => { cleanup(); resolve(image); };
    image.onerror = () => { cleanup(); reject(new Error('Image unavailable')); };
    if (signal.aborted) { abort(); return; }
    signal.addEventListener('abort', abort, {once: true});
    image.src = src;
  });
}
async function produce(input: PreviewInput, signal: AbortSignal): Promise<Result> {
  const artwork = await loadImage(input.src, signal);
  const hardware = input.product === 'keyring' ? await loadImage('/goods/mockup/silver-hardware-v1.webp', signal) : null;
  signal.throwIfAborted();
  const canvas = document.createElement('canvas');
  const geometry = renderCharm(canvas, artwork, hardware, input.product, input.placement);
  return {canvas, geometry};
}
/** The host supplies shared panel/layout; no API or workflow decisions live here. */
export function GoodsMockup(props: GoodsMockupProps) {
  const {src, product, placement, interactive = false, className = ''} = props;
  const canvas = useRef<HTMLCanvasElement>(null);
  const pointerStart = useRef<{x:number;y:number;id:number}|null>(null);
  const callback = useRef(props.onPreview);
  const [state, setState] = useState<PreviewState<Result> | null>(null);
  const [hint, setHint] = useState('');
  const [retry, setRetry] = useState(0);
  const key = previewKey({src, product, placement});
  useLayoutEffect(() => { callback.current = props.onPreview; });
  useLayoutEffect(() => {
    const controller = createPreviewController(produce, next => {
      setState(next);
      setHint('');
      const visible = canvas.current;
      if (visible) {
        visible.width = CHARM_WIDTH; visible.height = CHARM_HEIGHT;
        if (next.status === 'ready') visible.getContext('2d')?.drawImage(next.result.canvas, 0, 0);
      }
      callback.current?.(next);
    });
    void controller.update({src, product, placement});
    return () => controller.dispose();
  }, [key, retry]);
  const ready = state?.key === key && state.status === 'ready' ? state.result : null;
  const error = state?.key === key && state.status === 'error';
  function select(event: PointerEvent<HTMLCanvasElement>) {
    const start = pointerStart.current; pointerStart.current = null;
    if (!start || start.id !== event.pointerId || Math.hypot(event.clientX-start.x,event.clientY-start.y)>10) return;
    if (!interactive || product !== 'keyring' || !ready || !props.onChange) return;
    const bounds = event.currentTarget.getBoundingClientRect();
    if (bounds.width <= 0 || bounds.height <= 0) return;
    const g = ready.geometry;
    const x = ((event.clientX - bounds.left) * CHARM_WIDTH / bounds.width - g.left) / g.w;
    const y = ((event.clientY - bounds.top) * CHARM_HEIGHT / bounds.height - g.top) / g.h;
    const anchor = pickEdge(g.outline, x, y, placement.widthMm);
    if (!anchor) { setHint('그림의 테두리 가까이를 눌러 주세요.'); return; }
    props.onChange({...placement, holeX: anchor.x, holeY: anchor.y});
  }
  return <figure className={className} style={{margin: 0}}>
    <canvas ref={canvas} onPointerDown={event=>{pointerStart.current=event.isPrimary&&event.button===0?{x:event.clientX,y:event.clientY,id:event.pointerId}:null;}} onPointerUp={select} onPointerCancel={()=>{pointerStart.current=null;}} role="img" aria-label="굿즈 목업" style={{display:'block', width:'100%', height:'auto', aspectRatio:'800 / 840'}}/>
    {!ready && !error && <p role="status">미리보기를 만들고 있어요.</p>}
    {error && <p role="alert">그림을 불러오지 못했어요. <GlassButton variant="secondary" onClick={() => setRetry(n => n + 1)}>다시 시도</GlassButton></p>}
    {interactive && product === 'keyring' && <p className="goods-note">그림의 테두리를 클릭하거나 터치해 고리 위치를 골라 주세요.</p>}
    {hint && <p role="status">{hint}</p>}
    <figcaption>실물과 차이가 있을 수 있는 미리보기입니다.</figcaption>
  </figure>;
}
