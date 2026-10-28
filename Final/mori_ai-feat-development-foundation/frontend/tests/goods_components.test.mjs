import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import {createElement as h} from 'react';
import {renderToStaticMarkup as render} from 'react-dom/server';
await build({stdin:{contents:`export {GoodsDesigner} from './src/features/goods/design/GoodsDesigner'; export {GoodsMockup} from './src/features/goods/mockup/GoodsMockup'; export {StylePicker} from './src/features/goods/design/StylePicker'; export {RevisionHistory} from './src/features/goods/design/RevisionHistory';`,resolveDir:process.cwd(),loader:'tsx'},bundle:true,platform:'node',format:'esm',packages:'external',jsx:'automatic',outfile:'goods-components-check.mjs'});
const {StylePicker,RevisionHistory,GoodsDesigner,GoodsMockup}=await import('../goods-components-check.mjs');
test('style selection is accessible and generating blocks a different choice',()=>{
 const html=render(h(StylePicker,{styles:[{id:'book',label:'책',hint:'오픈북'},{id:'free',label:'자유',hint:'자유형'}],product:'keyring',selected:'book',disabled:true,onSelect(){}}));
 assert.match(html,/aria-pressed="true"/);assert.match(html,/aria-pressed="false"/);
 assert.ok((html.match(/disabled=""/g)||[]).length>=2);assert.match(html,/type="button"/);
 assert.match(html,/\/goods\/examples\/keyring\/book-card.webp/);
});
test('failed and pending revisions do not expose selection actions',()=>{
 const html=render(h(RevisionHistory,{items:[{id:'a',label:'첫 시안',status:'ready',imageUrl:'/a.png'},{id:'b',label:'수정 중',status:'pending'},{id:'c',label:'실패',status:'failed'}],selectedId:'a',onSelect(){}}));
 assert.match(html,/aria-pressed="true"/);assert.equal((html.match(/<button/g)||[]).length,1);
 assert.match(html,/만드는 중/);assert.match(html,/생성하지 못했어요/);
});
test('empty history explains its state without inventing generated artwork',()=>{
 const html=render(h(RevisionHistory,{items:[],selectedId:null,onSelect(){}}));assert.match(html,/아직 시안이 없어요/);assert.doesNotMatch(html,/<img/);
});

test('designer begins with shape selection, before upload and hole placement',()=>{
 const html=render(h(GoodsDesigner,{styles:[{id:'book',label:'책',hint:'오픈북'}]}));
 assert.match(html,/모양을 골라 주세요/);assert.doesNotMatch(html,/type="file"/);assert.doesNotMatch(html,/<canvas/);assert.match(html,/disabled=""/);
});
test('hole placement has no range slider even when interactive',()=>{
 const html=render(h(GoodsMockup,{src:'/test.png',product:'keyring',placement:{holeX:.5,holeY:0,widthMm:50},interactive:true}));
 assert.doesNotMatch(html,/type="range"/);
});
