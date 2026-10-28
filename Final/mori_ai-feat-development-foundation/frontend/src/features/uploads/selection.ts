import type {Config} from '../../api/types';

export function canSelectFiles(files: readonly File[], config: Config): boolean {
  const invalid = files.some(file =>
    !config.upload_allowed_extensions.some(extension => file.name.toLowerCase().endsWith(extension)) ||
    (file.type !== '' && !config.upload_allowed_mimes.includes(file.type) &&
      !(file.type === 'application/octet-stream' && /\.(heic|heif)$/i.test(file.name))) ||
    file.size > config.upload_max_file_bytes);
  return !invalid && files.length <= config.album_max_photos &&
    files.reduce((bytes, file) => bytes + file.size, 0) <= config.upload_max_album_bytes;
}
