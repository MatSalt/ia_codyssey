"""Replaceable image editor; fixed transport, no SDK retries, PNG output."""
import base64
from io import BytesIO
from PIL import Image
from openai import AsyncOpenAI,DefaultAsyncHttpxClient
from backend.generation.openai_provider import OpenAIProvider,ProviderResult,ProviderFailure,_accounting,MAX_IMAGE_BYTES

class GoodsProvider:
    def __init__(self,settings,client=None):
        options=dict(api_key=settings.openai_api_key.get_secret_value(),base_url='https://api.openai.com/v1',max_retries=0,timeout=300.0,organization=settings.openai_org_id or '',project=settings.openai_project_id or '')
        self.client=client.with_options(**options) if client else AsyncOpenAI(**options,http_client=DefaultAsyncHttpxClient(follow_redirects=False,trust_env=False))
    _call=OpenAIProvider._call
    async def aclose(self):await self.client.close()
    async def generate(self,source,parent,prompt,model):
        files=[]
        if parent:files.append(('selected.png',parent,'image/png'))
        files.append(('reference.webp',source,'image/webp'))
        response=await self._call(self.client.images.edit,model=model,image=files,prompt=prompt,n=1,size='1024x1024',quality='medium',background='transparent',output_format='png',timeout=300.0)
        accounting=_accounting(response,image=True)
        # Standard pricing reviewed 2026-10-18: sunburst text/image input
        # $5/$8 and image output $30 per 1M, same as the existing profile.
        # https://developers.openai.com/api/docs/pricing (not Batch).
        # Unknown models retain reservations; cache discounts not assumed.
        if model not in ('gpt-image-2','gpt-image-2.5-sunburst'):accounting['cost_usd']=None
        try:
            encoded=response.data[0].b64_json
            if len(response.data)!=1 or len(encoded)>4*((MAX_IMAGE_BYTES+2)//3):raise ValueError()
            data=base64.b64decode(encoded,validate=True)
            with Image.open(BytesIO(data)) as im:
                if im.format!='PNG' or im.width*im.height>16_000_000 or getattr(im,'n_frames',1)!=1:raise ValueError()
                im.load()
                if 'A' not in im.getbands() or im.getchannel('A').getextrema()[0]==255 or im.getchannel('A').getbbox() is None:raise ValueError()
        except Exception:raise ProviderFailure('IMAGE_RESULT_INVALID',dispatch_state='responded',**accounting) from None
        return ProviderResult(image=data,**accounting)
