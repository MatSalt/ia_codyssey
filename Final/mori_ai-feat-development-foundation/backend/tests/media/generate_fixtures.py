"""Own synthetic content only. Run in the pinned Linux codec image."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageCms
import pillow_heif


def main():
    root=Path('tests/fixtures/media'); root.mkdir(parents=True,exist_ok=True)
    pillow_heif.register_heif_opener(thumbnails=False)
    records=[]
    def save(name,image,**kwargs):
        path=root/name; image.save(path,**kwargs)
        records.append({'path':name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'stored_size':list(image.size),'orientation':kwargs.get('exif',{}).get(274,1),
            'alpha':'A' in image.getbands(),'ownership':'generated synthetic; no user data'})
    rgb=Image.new('RGB',(40,30),'white'); rgb.paste('red',(0,0,20,15)); rgb.paste('blue',(20,15,40,30))
    for orientation in range(1,9):
        exif=Image.Exif(); exif[274]=orientation
        save(f'orientation-{orientation}.png',rgb,exif=exif)
    save('alpha.png',Image.new('RGBA',(30,40),(20,80,140,100)))
    save('photo.jpg',rgb)
    save('lossless.webp',rgb,lossless=True)
    icc=ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    save('srgb-icc.png',rgb,icc_profile=icc)
    save('primary-second.heic',rgb,save_all=True,append_images=[Image.new('RGB',(30,40),'blue')],primary_index=1,quality=-1)
    for record in records:
        width,height=record['stored_size']
        if record['orientation'] in (5,6,7,8): width,height=height,width
        if record['path']=='primary-second.heic': width,height=30,40
        record.update(expected_size=[width,height],input_is_3_4=width*4==height*3)
    (root/'manifest.json').write_text(json.dumps({'fixtures':records,'not_executed':['actual iPhone HEIC HDR/PQ/HLG/gain-map','wide-gamut reference comparison','manual iPhone visual comparison']},indent=2)+'\n')

if __name__=='__main__': main()
