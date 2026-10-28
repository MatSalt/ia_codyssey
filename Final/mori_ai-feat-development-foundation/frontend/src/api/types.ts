export type GenerationMode = 'local_fake'|'openai'|null;
export interface MediaRef { asset_id: string; mime: string; width: number; height: number }
export interface MediaAccess { asset_id: string; url: string; expires_at: string }
export type AlbumStatus = 'draft'|'processing'|'action_required'|'review_ready'|'published'|'deleted';
export interface Album { id: string; title: string; status: AlbumStatus; version: number; page_count: number; cover: MediaRef | null; created_at: string; updated_at: string; published_at: string|null }
export interface Page { id: string; position: number; version: number; upload_status: 'reserved'|'validating'|'ready'|'rejected'|'expired'; source: MediaRef|null; thumbnail: MediaRef|null; result: MediaRef|null; caption_text: string|null; sort_date:string; sort_date_source:'exif'|'file_modified'|'reserved_at' }
export interface Detail { detail: { album: Album; pages: Page[]; order_mode: 'date'|'manual'; active_run_id: string|null; generation_mode:GenerationMode }; media_access: MediaAccess[] }
export interface Me { user: { id: string; display_name: string }; csrf_token: string; consent: { required: boolean; policy_version: string; notice: string } }
export type AuthProvider = 'google'|'kakao';
export interface Config { auth_providers: AuthProvider[]; upload_allowed_extensions: string[]; upload_allowed_mimes: string[]; upload_max_file_bytes: number; upload_max_album_bytes: number; album_max_photos: number }
export interface DevConfig { dev_auth_enabled:boolean; dev_ai_enabled:boolean; generation_enabled:boolean; generation_mode:GenerationMode }
export interface Reservation { batch_id: string; album_version: number; uploads: { client_file_id: string; upload_id: string; page_id: string; asset_id: string; method: 'PUT'; upload_url: string; required_headers: Record<string,string>; expires_at: string }[] }
export interface UploadView { upload_id: string; page_id: string; status: Page['upload_status']; error_code: string|null; album_version: number }
export type TaskStatus = 'queued'|'running'|'retry_wait'|'succeeded'|'failed'|'unknown'|'cancelled';
export interface TaskView { stage:'caption'|'image_transform'|'optimize'; status:TaskStatus; completion_kind:'provider'|'passthrough'|'local'|null; error_code:string|null; retryable:boolean }
export interface GenerationView { generation_mode:GenerationMode; run_id:string; album_id:string; album_status:AlbumStatus; run_status:'queued'|'running'|'action_required'|'succeeded'|'cancelled'; total_pages:number; completed_pages:number; failed_pages:number; unknown_pages:number; pending_pages:number; progress_percent:number; can_resume:boolean; poll_after_ms:number|null; pages:{page_id:string;tasks:TaskView[]}[] }
export interface GenerationAccepted { run_id:string; status_url:string; album_version:number }
export interface ViewerPage { id:string; position:number; image:MediaRef; caption_text:string }
export interface Viewer { generation_mode:GenerationMode; album_id:string; title:string; version:number; pages:ViewerPage[]; media_access:MediaAccess[]; music:{track_id:string;url:string;title:string}|null }

export interface UploadPreprocessing { version:1; original_width:number; original_height:number; captured_at_raw:string|null; captured_timezone:string|null }
