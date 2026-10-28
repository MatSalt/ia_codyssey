from io import BytesIO
from types import SimpleNamespace
from PIL import Image
import base64
import pytest
from backend.goods_design.provider import GoodsProvider
from backend.generation.openai_provider import ProviderFailure
from backend.settings import Settings

class Client:
    def __init__(self,data):self.data=data;self.images=self;self.options=None;self.request=None
    def with_options(self,**kwargs):self.options=kwargs;return self
    async def edit(self,**kwargs):self.request=kwargs;return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(self.data).decode())])

@pytest.mark.asyncio
async def test_goods_adapter_model_replacement_and_selected_reference_order():
    out=BytesIO();im=Image.new('RGBA',(20,20));im.putpixel((5,5),(255,0,0,255));im.save(out,format='PNG')
    client=Client(out.getvalue());p=GoodsProvider(Settings(database_url='postgresql+asyncpg://a:b@localhost/test',openai_api_key='test'),client)
    result=await p.generate(b'source',b'parent','instruction','future-model')
    assert result.image==out.getvalue() and result.cost_usd is None
    assert client.options['max_retries']==0
    assert client.request['model']=='future-model'
    assert client.request['background']=='transparent' and client.request['output_format']=='png'
    assert client.request['image'][0][1]==b'parent' and client.request['image'][1][1]==b'source'

@pytest.mark.asyncio
async def test_goods_adapter_rejects_opaque_or_invalid_output():
    out=BytesIO();Image.new('RGB',(20,20),'red').save(out,format='PNG')
    for data in (out.getvalue(),b'invalid'):
        p=GoodsProvider(Settings(database_url='postgresql+asyncpg://a:b@localhost/test',openai_api_key='test'),Client(data))
        with pytest.raises(ProviderFailure) as error:await p.generate(b'input',None,'request','gpt-image-2')
        assert error.value.dispatch_state=='responded'

@pytest.mark.parametrize('configured',[None,''])
def test_goods_defaults_to_transparent_model_without_changing_album(configured):
    values={} if configured is None else {'goods_image_model':configured}
    s=Settings(database_url='postgresql+asyncpg://a:b@localhost/test',**values)
    assert s.goods_image_model=='gpt-image-2.5-sunburst'
    assert s.openai_image_model=='gpt-image-2'

@pytest.mark.asyncio
async def test_goods_sunburst_accounts_reviewed_standard_usage():
    from decimal import Decimal
    class UsageClient(Client):
        async def edit(self,**kwargs):
            response=await super().edit(**kwargs)
            response.usage={'input_tokens':150,'output_tokens':200,'total_tokens':350,'input_tokens_details':{'text_tokens':50,'image_tokens':100}}
            return response
    out=BytesIO();im=Image.new('RGBA',(20,20));im.putpixel((5,5),(255,0,0,255));im.save(out,format='PNG')
    p=GoodsProvider(Settings(database_url='postgresql+asyncpg://a:b@localhost/test',openai_api_key='test'),UsageClient(out.getvalue()))
    result=await p.generate(b'source',None,'instruction','gpt-image-2.5-sunburst')
    assert result.cost_usd==Decimal('0.00705')
