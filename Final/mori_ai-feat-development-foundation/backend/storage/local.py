"""Private immutable objects; canonical UUID namespaces only, bounded streaming."""
import hashlib
import os
from pathlib import Path
import re
import tempfile

MAX_BYTES = 20971520
UUID_PART = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
KEY = re.compile(rf'{UUID_PART}/{UUID_PART}/{UUID_PART}/(source|normalized|thumbnail|result|transform_output|result_thumbnail)\Z')


class LocalStorage:
    mode = 'local'
    def __init__(self, root):
        self.root=Path(root)
        self.root.mkdir(parents=True,exist_ok=True)
        if self.root.is_symlink():
            raise ValueError('symlink storage root')
        self.root=self.root.resolve()

    def path(self,key,create=False):
        if not isinstance(key,str) or not KEY.fullmatch(key):
            raise ValueError('invalid storage key')
        current=self.root
        for part in key.split('/')[:-1]:
            current=current/part
            if create:
                current.mkdir(exist_ok=True)
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ValueError('unsafe storage namespace')
        path=self.root/key
        if path.is_symlink() or not path.resolve().is_relative_to(self.root):
            raise ValueError('unsafe storage path')
        return path

    def read_bytes(self,key):
        with self.path(key).open("rb") as stream:
            data = stream.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:
            raise ValueError("object too large")
        return data

    def stat(self,key):
        return self.path(key).stat()

    def exists(self,key):
        return self.path(key).is_file()

    def checksum(self,key):
        digest=hashlib.sha256()
        with self.path(key).open('rb') as stream:
            for chunk in iter(lambda:stream.read(65536),b''):
                digest.update(chunk)
        return digest.hexdigest()

    def delete(self,key):
        self.path(key).unlink(missing_ok=True)

    async def put_stream(self,key,chunks,declared):
        path=self.path(key,create=True)
        fd,temp=tempfile.mkstemp(prefix='.put-',dir=path.parent)
        total=0
        try:
            with os.fdopen(fd,'wb') as stream:
                async for chunk in chunks:
                    total+=len(chunk)
                    if total>MAX_BYTES or total>declared:
                        raise ValueError('size mismatch')
                    stream.write(chunk)
                if total!=declared:
                    raise ValueError('size mismatch')
                stream.flush(); os.fsync(stream.fileno())
            # link is atomic and refuses replacement, unlike os.rename on POSIX.
            try:
                os.link(temp,path,follow_symlinks=False)
            except FileExistsError:
                digest=hashlib.sha256()
                with open(temp,'rb') as stream:
                    for chunk in iter(lambda:stream.read(65536),b''): digest.update(chunk)
                if self.stat(key).st_size!=declared or self.checksum(key)!=digest.hexdigest():
                    raise FileExistsError('immutable upload conflict') from None
                return False
            self._sync(path.parent)
            return True
        finally:
            os.unlink(temp)

    def write(self,key,data):
        if len(data)>MAX_BYTES:
            raise ValueError('object too large')
        path=self.path(key,create=True)
        if path.exists():
            if self.checksum(key)!=hashlib.sha256(data).hexdigest():
                raise ValueError('immutable object conflict')
            return
        fd,temp=tempfile.mkstemp(prefix='.derived-',dir=path.parent)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data); stream.flush(); os.fsync(stream.fileno())
            try:
                os.link(temp,path,follow_symlinks=False)
            except FileExistsError:
                if self.checksum(key)!=hashlib.sha256(data).hexdigest():
                    raise ValueError('immutable object conflict')
            self._sync(path.parent)
        finally:
            os.unlink(temp)

    @staticmethod
    def _sync(directory):
        fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
        try: os.fsync(fd)
        finally: os.close(fd)


def storage_key(owner,album,page,role):
    return f'{owner}/{album}/{page}/{role}'


def canonical_asset_keys(owner,album,page,role):
    if role not in {'source','normalized','thumbnail','result','transform_output'}:
        return ()
    keys=(storage_key(owner,album,page,role),)
    return keys+(storage_key(owner,album,page,'result_thumbnail'),) if role=='thumbnail' else keys
