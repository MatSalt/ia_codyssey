/** Public catalog metadata comes from the server; these IDs map approved example files. */
export const STYLE_IDS = ['photo', 'illustration', 'cutout', 'badge', 'book', 'free'] as const;
export type StyleId = typeof STYLE_IDS[number];
export type DesignStyle = {id: StyleId; label: string; hint: string};
export function exampleImage(product: string, style: string, card = false): string {
  if (!['keyring','magnet'].includes(product) || !STYLE_IDS.includes(style as StyleId)) throw new Error('Unknown goods example');
  return `/goods/examples/${product}/${style}${card ? '-card' : ''}.webp`;
}
