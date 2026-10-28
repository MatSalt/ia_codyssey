/** Preview results are valid only for the exact artwork, product and placement. */
export type GoodsProduct = 'keyring' | 'magnet';
export type Placement = {holeX: number; holeY: number; widthMm: number};
export type PreviewInput = {src: string; product: GoodsProduct; placement: Placement};
export type PreviewState<T> = {key: string; status: 'pending' | 'error'} | {key: string; status: 'ready'; result: T};
export function previewKey(input: PreviewInput): string {
  return JSON.stringify([input.src, input.product, input.placement.holeX, input.placement.holeY, input.placement.widthMm]);
}
export function createPreviewController<T>(produce: (input: PreviewInput, signal: AbortSignal) => Promise<T>, publish: (state: PreviewState<T>) => void) {
  let active: AbortController | undefined;
  let disposed = false;
  return {
    async update(input: PreviewInput): Promise<void> {
      if (disposed) return;
      active?.abort();
      const request = new AbortController();
      active = request;
      const snapshot = {...input, placement: {...input.placement}};
      const key = previewKey(snapshot);
      publish({key, status: 'pending'});
      try {
        const result = await produce(snapshot, request.signal);
        if (!disposed && active === request && !request.signal.aborted) publish({key, status: 'ready', result});
      } catch {
        if (!disposed && active === request && !request.signal.aborted) publish({key, status: 'error'});
      }
    },
    dispose() { disposed = true; active?.abort(); },
  };
}
