import { isDirty, type CaptionDraft } from '../generation/flow.js';
// Only unsaved text survives an expired session, never media URLs or File objects.
// A different authenticated owner and explicit logout erase the entire vault.
export class ReviewDrafts {
 private owner:string|null=null;
 private albums=new Map<string,Record<string,CaptionDraft>>();
 selectOwner(owner:string) {if(this.owner!==owner){this.albums.clear();this.owner=owner;}}
 remember(owner:string,album:string,drafts:Record<string,CaptionDraft>) {
  if(this.owner!==owner)return;
  const dirty=Object.fromEntries(Object.entries(drafts).filter(([,draft])=>isDirty(draft)).map(([id,draft])=>[id,{text:draft.text,baseline:draft.baseline,version:draft.version}]));
  if(Object.keys(dirty).length)this.albums.set(album,dirty);else this.albums.delete(album);
 }
 restore(owner:string,album:string):Record<string,CaptionDraft> {
  if(this.owner!==owner)return {};
  return Object.fromEntries(Object.entries(this.albums.get(album)??{}).map(([id,draft])=>[id,{...draft}]));
 }
 forget(owner:string,album:string) {if(this.owner===owner)this.albums.delete(album);}
 clear() {this.albums.clear();this.owner=null;}
}
export const reviewDrafts=new ReviewDrafts();
