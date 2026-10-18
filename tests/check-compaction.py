"""Offline native-checkpoint portability, DPAPI and failure-atomicity checks."""
from pathlib import Path
from dataclasses import replace
import io
import json
import sys
import contextlib
import uuid

root = Path(__file__).resolve().parent.parent
sys.path.insert(0,str(root/'src/gateway'));sys.path.insert(0,str(root/'src/desktop'))
import portable_compaction as portable
from core import GatewayCore, GatewayError, portable_history
from runtime_mixed import prepare_routed_request

checkpoint = 'owned-native-checkpoint-fixture-not-a-token'
summary = 'FIXTURE_PORTABLE_CONTEXT: user requested a verified report; no commands executed.'
item = {'type':'compaction','id':'cmp_owned_fixture','encrypted_content':checkpoint}
def frames(output):
    events = [{'type':'response.created','response':{'id':'resp_fixture','status':'in_progress','output':[]}}]
    for index,entry in enumerate(output):
        events.extend([{'type':'response.output_item.added','output_index':index,'item':entry},
            {'type':'response.output_item.done','output_index':index,'item':entry}])
    events.append({'type':'response.completed','response':{'id':'resp_fixture','status':'completed','output':output}})
    return b''.join(('data: '+json.dumps(v)+'\n\n').encode() for v in events)
def native_sparse_frames(output):
    values=[json.loads(line[5:]) for line in frames(output).splitlines() if line.startswith(b'data:')]
    values[-1]['response']['output']=[]
    return b''.join(('data: '+json.dumps(v)+'\n\n').encode() for v in values)
class Headers:
    def get_content_type(self):return 'text/plain'
class Reply(io.BytesIO):
    headers=Headers();status=200
    def read1(self,size=-1):return self.read(size)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()

scratch=root/'.local/test-work'/('compaction-'+uuid.uuid4().hex[:8]);scratch.mkdir(parents=True)
with contextlib.nullcontext(str(scratch)) as directory:
    old_cache = portable.CACHE;portable.CACHE = Path(directory)
    try:
        # Both checkpoints are issued by the mocked native origin; the gateway
        # does not invent encrypted items or change native rollback context.
        core=GatewayCore('fixture_capability_12345678901234567890',12345,{'gpt-6.1-sol'},lambda provider:'dummy-provider-fixture')
        headers=[('Host',core.host),('Authorization','Bearer dummy-native-fixture'),('Content-Type','application/json')]
        history=[{'type':'message','role':'user','content':'Owned fixture task.'},
            {'type':'function_call','id':'fc_fixture','name':'read_file','call_id':'fixture_call','arguments':'{}'},
            {'type':'function_call_output','id':'invalid_fixture_result_id','call_id':'fixture_call','output':'Owned fixture evidence.'},
            {'type':'custom_tool_call','id':'fc_wrong_type_prefix','name':'fixture_custom','call_id':'fixture_custom_call','input':'fixture'},
            {'type':'custom_tool_call_output','id':'wrong_custom_result_id','call_id':'fixture_custom_call','output':'fixture completed'},
            {'type':'compaction_trigger'}]
        payload={'model':'zai/glm-5.3-flash','input':history,'tools':[],'stream':True,
            'reasoning':{'effort':'none','summary':'auto'}}
        prepared,incoming,_=prepare_routed_request(core,core.prefix+'/backend-api/codex/responses',headers,json.dumps(payload).encode())
        native=json.loads(prepared.body)
        assert prepared.provider=='openai' and prepared.url=='https://chatgpt.com/backend-api/codex/responses'
        assert prepared.kind=='compaction' and native['model']=='gpt-6.1-sol'
        assert native['reasoning']=={'effort':'low','summary':'auto'}
        assert payload['reasoning']['effort']=='none'
        for effort in (None,'none','high'):
            request={**payload}
            if effort is None: request.pop('reasoning')
            else: request['reasoning']={'effort':effort,'summary':'auto'}
            repaired,_,_=prepare_routed_request(core,core.prefix+'/backend-api/codex/responses',headers,json.dumps(request).encode())
            assert json.loads(repaired.body)['reasoning']['effort']=='low'
            assert request.get('reasoning',{}).get('effort')==effort
        assert incoming['model']==payload['model'] and payload['input'][2]['id']=='invalid_fixture_result_id'
        assert all('id' not in v for v in native['input'])
        assert native['input'][2]['call_id']=='fixture_call' and native['input'][3]['call_id']=='fixture_custom_call'
        assert dict(prepared.headers)['authorization']=='Bearer dummy-native-fixture'
        # Native manual/automatic compaction keeps the ordinary streaming route;
        # only external-model checkpoints require a portable summary/cache.
        for model in ('gpt-6.1-sol','owned-native-model'):
            native_core=GatewayCore('fixture_capability_12345678901234567890',12345,{model},lambda provider:'dummy-provider-fixture')
            native_prepared,native_incoming,_=prepare_routed_request(native_core,core.prefix+'/backend-api/codex/responses',headers,
                json.dumps({**payload,'model':model}).encode())
            assert native_prepared.kind=='responses' and native_prepared.provider=='openai'
            assert json.loads(native_prepared.body)['model']==native_incoming['model']==model
            assert json.loads(native_prepared.body)['reasoning']==payload['reasoning']
            assert json.loads(native_prepared.body)['input'][-1]=={'type':'compaction_trigger'}
            assert not any(k.lower()=='accept-encoding' and v=='identity' for k,v in native_prepared.headers)
        calls=[]
        def native_summary(url,headers,body):
            value=json.loads(body);calls.append(value)
            assert url==prepared.url and dict(headers)['authorization']=='Bearer dummy-native-fixture'
            assert value['tools']==[] and value['tool_choice']=='none' and value['input'][0]==item
            return Reply(native_sparse_frames([{'type':'message','id':'msg_summary_fixture','role':'assistant','content':[{'type':'output_text','text':summary}]}]))
        output=list(portable.checkpoint_events(Reply(native_sparse_frames([item])),prepared,native_summary))
        assert len(calls)==1 and output[-1][1]['type']=='response.completed'
        assert output[-1][1]['response']['output']==[]
        assert any(event and event.get('type')=='response.output_item.done' and event['item']==item for frame,event in output)
        files=list(portable.CACHE.glob('*.dpapi'));assert len(files)==1
        assert summary.encode() not in files[0].read_bytes() and checkpoint.encode() not in files[0].read_bytes()
        assert portable.read_summary(checkpoint)==summary
        continued=core.prepare('POST',core.prefix+'/backend-api/codex/responses',headers,
            json.dumps({'model':'zai/glm-5.3-flash','input':[item,{'role':'user','content':'Continue.'}],'tools':[]}).encode())
        external=json.loads(continued.body)
        assert summary in json.dumps(external) and checkpoint not in json.dumps(external)
        assert dict(continued.headers)['Authorization']=='Bearer dummy-provider-fixture'
        assert 'dummy-native-fixture' not in json.dumps(external)
        # Genuine native rollback retains the original server checkpoint.
        native_continued=core.prepare('POST',core.prefix+'/backend-api/codex/responses',headers,
            json.dumps({'model':'gpt-6.1-sol','input':[item]}).encode())
        assert json.loads(native_continued.body)['input']==[item]
        routed_native,_,_=prepare_routed_request(core,core.prefix+'/backend-api/codex/responses',headers,
            json.dumps({'model':'gpt-6.1-sol','input':[item,{'type':'message','id':'wrong_plain_id','role':'user','content':'fixture continuation'}]}).encode())
        assert json.loads(routed_native.body)['input'][0]==item
        assert 'id' not in json.loads(routed_native.body)['input'][1]
        for bad in ('unknown-checkpoint-fixture',None):
            try: portable_history([dict(item,encrypted_content=bad)]);raise AssertionError('Unknown checkpoint accepted')
            except GatewayError:pass
        # If portable summary creation fails, Codex gets no committed checkpoint.
        seen=[]
        def failed_summary(*args):raise OSError('Owned offline fixture failure')
        try:
            for pair in portable.checkpoint_events(Reply(frames([dict(item,encrypted_content='other-fixture')])),prepared,failed_summary):seen.append(pair)
            raise AssertionError('Failed checkpoint completed')
        except OSError:pass
        assert not any(v and v.get('type') in {'response.completed','response.output_item.done'} for raw,v in seen)
        # DPAPI integrity prevents a corrupt cache from becoming provider input.
        saved=files[0].read_bytes();files[0].write_bytes(saved[:-1]+bytes([saved[-1]^1]))
        try:portable.read_summary(checkpoint);raise AssertionError('Corrupt checkpoint accepted')
        except ValueError:pass
        files[0].write_bytes(saved)
        try:
            prepare_routed_request(core,core.prefix+'/backend-api/codex/responses',headers,
                json.dumps({**payload,'input':[{'type':'compaction_trigger'},{'role':'user','content':'after trigger'}]}).encode())
            raise AssertionError('Misplaced trigger accepted')
        except GatewayError:pass
    finally:portable.CACHE=old_cache
print('PASS: native-issued checkpoint, Windows-encrypted portable summary, unchanged selected model/tool pairing, safe continuation and rollback; failed/corrupt/unknown checkpoints rejected. No inference or tools executed.')
