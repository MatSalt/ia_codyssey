import test from 'node:test';
import assert from 'node:assert/strict';

const {canSelectFiles} = await import(process.argv[2]);
const config = {
  upload_allowed_extensions: ['.jpg', '.jpeg', '.png', '.webp', '.heif', '.heic'],
  upload_allowed_mimes: ['image/jpeg', 'image/png', 'image/webp', 'image/heif', 'image/heic'],
  upload_max_file_bytes: 20 * 1024 * 1024,
  upload_max_album_bytes: 300 * 1024 * 1024,
  album_max_photos: 50,
};
const photo = (name, type = '', size = 4) => new File([new Uint8Array(size)], name, {type});

test('binary MIME HEIC and HEIF are selectable with case insensitive supported extensions', () => {
  assert.equal(canSelectFiles([photo('IMG.HEIC', 'application/octet-stream')], config), true);
  assert.equal(canSelectFiles([photo('IMG.HeIf', 'application/octet-stream')], config), true);
});

test('empty MIME and the configured image types still reach upload selection', () => {
  assert.equal(canSelectFiles([photo('IMG.HEIC'), photo('photo.png', 'image/png')], config), true);
  assert.equal(canSelectFiles([photo('photo.JPG', 'image/jpeg'), photo('photo.webp', 'image/webp')], config), true);
});

test('binary MIME exception never accepts other extensions or an arbitrary unknown MIME', () => {
  for (const file of [photo('photo.png', 'application/octet-stream'), photo('photo.jpg', 'application/octet-stream'),
    photo('photo.exe', 'image/heic'), photo('photo.heic.exe', 'image/heic'), photo('photo.heic', 'application/unknown')]) {
    assert.equal(canSelectFiles([file], config), false, file.name + ':' + file.type);
  }
});

test('invalid file in a mixed selection prevents the whole batch from being selected', () => {
  assert.equal(canSelectFiles([photo('valid.heic', 'application/octet-stream'), photo('bad.gif', 'image/gif')], config), false);
});

test('file, album bytes and slot boundaries stay enforced for the binary MIME exception', () => {
  const small = {...config, upload_max_file_bytes: 20, upload_max_album_bytes: 30, album_max_photos: 2};
  assert.equal(canSelectFiles([photo('a.heic', 'application/octet-stream', 20), photo('b.heif', '', 10)], small), true);
  assert.equal(canSelectFiles([photo('a.heic', 'application/octet-stream', 21)], small), false);
  assert.equal(canSelectFiles([photo('a.heic', 'application/octet-stream', 20), photo('b.heif', '', 11)], small), false);
  assert.equal(canSelectFiles([photo('a.heic'), photo('b.heif'), photo('c.png')], small), false);
});
