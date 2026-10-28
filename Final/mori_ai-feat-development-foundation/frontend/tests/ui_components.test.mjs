import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createElement as h} from 'react';
import {renderToStaticMarkup as render} from 'react-dom/server';
await build({stdin:{contents:`export {GlassButton} from './src/components/ui/GlassButton'; export {IconButton} from './src/components/ui/IconButton'; export {PhotoThumbnail} from './src/components/media/PhotoThumbnail';`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',outfile:'ui-check.mjs'});
const {GlassButton,IconButton,PhotoThumbnail}=await import('../ui-check.mjs');
test('action buttons do not accidentally submit surrounding forms',()=>{
 assert.match(render(h(GlassButton,{},'저장')),/type="button"/);
 assert.match(render(h(GlassButton,{type:'submit'},'동의')),/type="submit"/);
 assert.match(render(h(GlassButton,{disabled:true},'저장 중')),/disabled=""/);
});
test('icon actions expose their purpose without a visible text label',()=>{
 assert.match(render(h(IconButton,{label:'책장으로'},'←')),/aria-label="책장으로"/);
});
test('photo selection exposes selected and unselected states to assistive technology',()=>{
 for(const selected of [true,false]){
  const html=render(h(PhotoThumbnail,{label:'2번째 사진',selected,onSelect:()=>{}},'사진'));
  assert.match(html,new RegExp(`aria-pressed="${selected}"`));
  assert.match(html,/aria-label="2번째 사진"/);
 }
});
