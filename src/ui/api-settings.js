// Rendered in the verified Settings module with its original UI primitives.
// New key values live only in this editor's memory and are cleared on save/leave.
(() => {
  const e = (...args) => li.createElement(...args);
  const DialogLayout = li.createContext(false);
  const efforts = [`none`,`minimal`,`low`,`medium`,`high`,`xhigh`,`max`,`ultra`];
  const labels = {providers:`Providers`,models:`Models`};
  function Dropdown({label,options,value,onChange,disabled,...accessibility}) {
    const inDialog=li.useContext(DialogLayout);
    const selected = options.find(option => option.value === value)?.label ?? `Choose…`;
    return e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled,
      triggerButton:e(GatewayDropdownButton,{...accessibility,"aria-label":label,disabled,className:inDialog?`w-full`:`max-w-64`,children:e(`span`,{className:`truncate`},selected)}),
      children:e(`div`,{className:`max-h-80 overflow-y-auto`},e(GatewayMenu.RadioGroup,{value},
        options.map(option => e(GatewayMenu.RadioItem,{key:option.value,value:option.value,disabled:option.disabled,onSelect:()=>onChange(option.value)},option.label))))});
  }
  function SettingsRow({label,description,control,...props}) {
    const inDialog=li.useContext(DialogLayout),id=li.useId(),labelId=li.useId(),descriptionId=li.useId();
    if(!inDialog)return e(GatewayRow,{...props,label,description,control});
    return e(GatewayDialogHeader,{spacing:`large`},e(GatewayFieldStack,null,
      e(typeof control===`function`?`label`:`span`,{id:labelId,htmlFor:typeof control===`function`?id:undefined,className:`text-sm font-medium text-default select-none`},label),
      typeof control===`function`?control({id,"aria-labelledby":labelId,"aria-describedby":description?descriptionId:undefined}):control,
      description?e(`p`,{id:descriptionId,className:`text-sm text-secondary`},description):null));
  }
  function Action(props) {
    const inDialog=li.useContext(DialogLayout);
    return e(GatewayButton,{size:inDialog?`medium`:`toolbar`,type:`button`,...props});
  }
  function Field({label,value,onChange,onBlur,onFocus,autoFocus,type=`text`,readOnly=false,placeholder,maxLength,min,max,disabled}) {
    const inDialog=li.useContext(DialogLayout);
    return e(SettingsRow,{label,control:accessibility=>e(GatewayInput,{...accessibility,variant:inDialog?`default`:`settings`,
      className:inDialog?undefined:`w-64 max-w-full`,type,value:value??``,readOnly,disabled,autoFocus,placeholder,maxLength,min,max,
      autoComplete:type===`password`?`new-password`:`off`,spellCheck:false,onFocus,onBlur,onChange:event=>onChange?.(event.target.value)})});
  }
  function Section({title,children,action,grouped=true}) {
    return e(GatewaySettingsSection,null,e(GatewaySettingsSection.Header,{title,actions:action}),
      e(GatewaySettingsSection.Content,null,grouped?e(GatewayGroup,{variant:`default`},children):children));
  }
  function ProviderDisclosure({label,open,onToggle,disabled}) {
    return e(GatewayButton,{type:`button`,size:`toolbar`,color:`ghost`,disabled,"aria-expanded":open,onClick:onToggle,
      className:`min-w-0 justify-start gap-2`},
      e(GatewayChevron,{"aria-hidden":true,className:`text-tertiary transition-transform duration-basic `+(open?`rotate-90`:``)}),
      e(`span`,{className:`truncate`},label));
  }
  function clearKeys(draft) {
    for (const entry of Object.values(draft?.keys??{})) for (const profile of entry.profiles) profile.key=``;
  }
  function makeDraft(snapshot) {
    return {providers:structuredClone(snapshot.providers),models:structuredClone(snapshot.models),
      keys:Object.fromEntries(Object.entries(snapshot.providers).map(([id,p])=>[id,{
        active:p.credential_profiles.active,profiles:p.credential_profiles.profiles.map(profile=>({...profile,key:``,existing:true}))}]))};
  }
  function newModel(provider) {
    return {provider,id:``,label:``,context:``,output:``,efforts:[],default_effort:``,metadata_mode:`provider`,reasoning_mode:`provider_default`,enabled:true};
  }
  function applyMetadata(model,info) {
    return {...model,label:model.label||info.label,context:info.context??``,output:info.output??``,
      efforts:info.efforts??[`none`],default_effort:info.efforts?.includes(model.default_effort)?model.default_effort:info.default_effort??`none`,
      reasoning_mode:info.efforts?`explicit`:`provider_default`,metadataNotes:info.notes.join(` `),metadataModelId:model.id};
  }
  function upstreamChoices(model, info) {
    const options=[{value:``,label:`Automatic`}];
    for(const p of info?.providers??[])options.push({value:p.id,label:p.id+(p.available?``:` (unavailable)`),disabled:!p.available});
    if(model.upstream_provider&&!options.some(p=>p.value===model.upstream_provider))
      options.push({value:model.upstream_provider,label:model.upstream_provider+` (saved; refresh availability)`});
    return options;
  }
  function serviceTierChoices(model, info) {
    const labels={auto:`Automatic`,default:`Standard`,flex:`Flex`,fast:`Fast`,priority:`Priority`};
    const options=[{value:``,label:`Automatic`}];
    for(const tier of info?.service_tiers??[])if(tier&&tier!==`auto`)options.push({value:tier,label:labels[tier]??tier});
    if(model.service_tier&&!options.some(p=>p.value===model.service_tier))
      options.push({value:model.service_tier,label:(labels[model.service_tier]??model.service_tier)+` (saved; refresh support)`});
    return options;
  }
  function requestBody(snapshot,draft) {
    return {action:`save`,revision:snapshot.revision,
      providers:Object.fromEntries(Object.entries(draft.providers).map(([id,p])=>[id,{label:p.label,adapter:p.adapter,endpoint:p.endpoint,default_model:p.default_model,enabled:p.enabled!==false}])),
      models:draft.models.map(m=>({id:m.id,provider:m.provider,label:m.label,context:Number(m.context),output:Number(m.output),enabled:m.enabled!==false,
        efforts:m.efforts,default_effort:m.default_effort,metadata_mode:m.metadata_mode??`custom`,reasoning_mode:m.reasoning_mode??`explicit`,
        ...(m.provider===`nanogpt`?{upstream_provider:m.upstream_provider??``,service_tier:m.service_tier??``}:{})})),
      keys:Object.fromEntries(Object.entries(draft.keys).map(([id,p])=>[id,{active:p.active,profiles:p.profiles.map(k=>({id:k.id,label:k.label.trim(),key:k.key}))}]))};
  }
  function removeEntry(draft,item) {
    if(item.kind===`provider`) {
      clearKeys({keys:{[item.id]:draft.keys[item.id]}});
      delete draft.providers[item.id];delete draft.keys[item.id];
      draft.models=draft.models.filter(m=>m.provider!==item.id);
    } else if(item.kind===`model`) {
      const model=draft.models[item.index];draft.models.splice(item.index,1);
      const p=draft.providers[model.provider];
      if(p.default_model===model.id)p.default_model=draft.models.find(m=>m.provider===model.provider)?.id??``;
    } else {
      const entry=draft.keys[item.id];
      entry.profiles=entry.profiles.filter(k=>k.id!==item.profile);
      if(entry.active===item.profile)entry.active=(entry.profiles.find(k=>k.saved||k.key.trim())??entry.profiles[0])?.id??null;
    }
  }
  function completeDraft(draft) {
    return Object.values(draft.providers).every(p=>p.label.trim()&&p.endpoint.startsWith(`https://`))&&
      draft.models.every(m=>m.id.trim()&&m.label.trim()&&Number(m.context)>=2&&Number(m.output)>=1&&Number(m.output)<=Number(m.context)&&m.efforts.length&&m.efforts.includes(m.default_effort))&&
      Object.values(draft.keys).every(entry=>entry.profiles.every(p=>p.label.trim()&&(p.existing||p.id===`default`||p.key.trim()))&&
        (!entry.profiles.length||entry.profiles.some(p=>p.id===entry.active&&(p.saved||p.key.trim()))||!entry.profiles.some(p=>p.saved||p.key.trim())));
  }
  globalThis.gatewaySettingsComponent = function BetterCodexSettingsPage({section=`providers`,provider}) {
    if(section===`keys`)section=`providers`;
    const [snapshot,setSnapshot] = li.useState(null);
    const [draft,setDraft] = li.useState(null);
    const [busy,setBusy] = li.useState(false);
    const [dirty,setDirty] = li.useState(false);
    const [status,setStatus] = li.useState(``);
    const [failed,setFailed] = li.useState(false);
    const [selectedProvider,setSelectedProvider] = li.useState(provider??``);
    const [expanded,setExpanded] = li.useState({});
    const [confirmEndpoint,setConfirmEndpoint] = li.useState(false);
    const [removal,setRemoval] = li.useState(null);
    const [newProvider,setNewProvider] = li.useState(null);
    const [modelSearch,setModelSearch] = li.useState(``);
    const [editor,setEditor] = li.useState(null);
    const [sensitiveFocus,setSensitiveFocus] = li.useState(false);
    const [newKey,setNewKey] = li.useState(null);
    const [upstreamLists,setUpstreamLists] = li.useState({});
    const latest = li.useRef(null);
    const keyDraft = li.useRef(null);
    latest.current=draft;
    keyDraft.current=newKey;
    GatewayDirtySettings(`better-codex-settings`,dirty||busy||!!newKey);
    li.useEffect(()=>{setEditor(section===`providers`&&provider?{kind:`provider`,id:provider}:null);setNewProvider(null);if(keyDraft.current)keyDraft.current.key=``;setNewKey(null)},[section,provider]);
    li.useEffect(()=>{
      let cancelled=false;
      globalThis.gatewaySettingsRequest({action:`get`}).then(value=>{
        if(cancelled)return;
        setSnapshot(value);setDraft(makeDraft(value));
        setSelectedProvider(provider in value.providers?provider:Object.keys(value.providers)[0]);
      }).catch(error=>{if(!cancelled){setStatus(error.message);setFailed(true)}});
      return()=>{cancelled=true;clearKeys(latest.current);if(keyDraft.current)keyDraft.current.key=``};
    },[]);
    function edit(change) {
      setDraft(previous=>{const next=structuredClone(previous);change(next);return next});
      setDirty(true);setStatus(``);setFailed(false);
    }
    function toggle(id) {setExpanded(previous=>({...previous,[id]:!previous[id]}))}
    const button=(text,onClick,disabled=busy,color=`secondary`,type=`button`)=>e(Action,{color,type,disabled,loading:type===`submit`&&busy,onClick:event=>{if(type===`submit`)event?.preventDefault();return onClick()}},text);
    const providerOptions=draft?Object.entries(draft.providers).map(([value,p])=>({value,label:p.label+(p.enabled===false?` (disabled)`:``)})):[];
    const menuRow=(label,options,value,onChange,description)=>e(SettingsRow,{label,description,
      control:accessibility=>e(Dropdown,{...accessibility,label,options,value,onChange,disabled:busy})});
    async function fetchMetadata(index) {
      const model=latest.current?.models[index];
      if(busy||!model?.id.trim()||model.metadata_mode!==`provider`)return;
      const pid=model.provider;
      const keys=latest.current.keys[pid];
      if(!snapshot.providers[pid]||latest.current.providers[pid].endpoint!==snapshot.providers[pid].endpoint||keys.active!==snapshot.providers[pid].credential_profiles.active||keys.profiles.some(k=>k.key)) {
        setStatus(`Let provider URL or API-key changes finish saving before fetching metadata. Existing model limits are kept until you explicitly refresh them.`);setFailed(true);return;
      }
      setBusy(true);setStatus(`Fetching provider metadata…`);setFailed(false);
      try {
        const info=await globalThis.gatewaySettingsRequest({action:`metadata`,revision:snapshot.revision,provider:pid,model:model.id.trim()});
        setDraft(previous=>{const next=structuredClone(previous);if(next.models[index]?.id===model.id&&next.models[index].provider===pid)next.models[index]=applyMetadata(next.models[index],info);return next});
        setDirty(true);setStatus(info.notes.join(` `)||`Provider metadata loaded.`);
      } catch(error){setFailed(true);setStatus(error.message)}
      finally {setBusy(false)}
    }
    async function fetchUpstreams(index) {
      const model=latest.current?.models[index];
      if(busy||model?.provider!==`nanogpt`||!model.id.trim())return;
      if(latest.current.providers.nanogpt.endpoint!==snapshot.providers.nanogpt?.endpoint) {
        setStatus(`Finish saving the NanoGPT address before loading providers.`);setFailed(true);return;
      }
      setBusy(true);setStatus(`Loading NanoGPT providers and tiers…`);setFailed(false);
      try {
        const info=await globalThis.gatewaySettingsRequest({action:`upstream_providers`,revision:snapshot.revision,provider:`nanogpt`,model:model.id.trim()});
        setUpstreamLists(previous=>({...previous,[model.id]:info}));
        setStatus(info.supported?`Providers and supported tiers loaded.`:`Supported tiers loaded. NanoGPT does not support provider selection for this model.`);
      } catch(error){setFailed(true);setStatus(error.message)}
      finally {setBusy(false)}
    }
    async function save(confirmed=false) {
      if(busy||!dirty||!draft||newKey||editor?.creating||!completeDraft(draft))return;
      if(!confirmed&&Object.entries(draft.providers).some(([id,p])=>snapshot.providers[id]&&p.endpoint!==snapshot.providers[id].endpoint)){setConfirmEndpoint(true);return}
      setConfirmEndpoint(false);
      setBusy(true);setFailed(false);setStatus(`Saving…`);
      const submitted=draft;
      let body=requestBody(snapshot,submitted);
      try {
        const result=await globalThis.gatewaySettingsRequest(body);
        if(result.live_applied)globalThis.gatewayUpdateProviderConfig?.(result.provider_config);
        const changed=latest.current!==submitted;
        setSnapshot(result.settings);
        setDraft(previous=>{
          if(previous===submitted)return makeDraft(result.settings);
          const next=structuredClone(previous);
          for(const [id,entry] of Object.entries(next.keys))for(const profile of entry.profiles) {
            const saved=result.settings.providers[id]?.credential_profiles.profiles.find(p=>p.id===profile.id);
            if(saved){profile.saved=saved.saved;profile.existing=true}
            if(profile.key===submitted.keys[id]?.profiles.find(p=>p.id===profile.id)?.key)profile.key=``;
          }
          return next;
        });
        setDirty(changed);setStatus(result.live_applied?(result.catalog_changed||result.catalog_pending?`All changes saved. Refresh models to update the picker.`:`All changes saved.`):result.message);setFailed(result.live_applied===false&&!!result.settings.live_supported);
        if(!changed&&result.live_applied!==false&&editor?.closeAfterSave)setEditor(null);
      } catch(error){setFailed(true);setStatus(error.message)}
      finally {
        clearKeys(body);body=null;
        setBusy(false);
      }
    }
    li.useEffect(()=>{
      if(!dirty||!draft||!snapshot||busy||failed||sensitiveFocus||confirmEndpoint||newProvider||newKey||editor?.creating)return;
      if(!completeDraft(draft)){setStatus(`Complete the required fields to save automatically.`);return}
      if(JSON.stringify(requestBody(snapshot,draft))===JSON.stringify(requestBody(snapshot,makeDraft(snapshot)))){setDirty(false);setStatus(`All changes saved.`);return}
      setStatus(`Changes will save automatically…`);
      const timer=setTimeout(()=>save(),400);
      return()=>clearTimeout(timer);
    },[draft,dirty,snapshot,busy,failed,sensitiveFocus,confirmEndpoint,newProvider,newKey,editor?.creating]);
    async function applyLive() {
      if(busy||dirty||!snapshot?.live_supported)return;
      setBusy(true);setStatus(`Applying verified settings for new requests…`);setFailed(false);
      try {
        const result=await globalThis.gatewaySettingsRequest({action:`apply_live`,revision:snapshot.revision});
        if(result.live_applied)globalThis.gatewayUpdateProviderConfig?.(result.provider_config);
        setSnapshot(result.settings);setDraft(makeDraft(result.settings));setStatus(result.message);
      } catch(error){setStatus(error.message);setFailed(true)}
      finally {setBusy(false)}
    }
    async function refreshModels() {
      if(busy||dirty||!snapshot?.catalog_refresh_supported)return;
      setBusy(true);setFailed(false);setStatus(`Refreshing the verified model catalog…`);
      try {
        await globalThis.gatewaySettingsRequest({action:`refresh_catalog`,revision:snapshot.revision});
        window.location.reload();
      } catch(error){setStatus(error.message);setFailed(true);setBusy(false)}
    }
    const footer=e(li.Fragment,null,
      e(`div`,{role:`status`,className:`min-w-0 flex-1 text-sm `+(failed?`text-danger`:`text-secondary`)},status),
      dirty?button(`Discard changes`,()=>{clearKeys(latest.current);setDraft(makeDraft(snapshot));setDirty(false);setStatus(``);setFailed(false)}):null,
      snapshot?.live_supported&&snapshot?.apply_pending?button(`Retry apply`,applyLive,busy||dirty):null,
      failed&&dirty?button(`Retry`,()=>save()):null);
    const modelActions=add=>e(`div`,{className:`flex flex-wrap items-center justify-end gap-2`},
      snapshot?.catalog_refresh_supported?button(`Refresh models`,refreshModels,busy||dirty):null,add);
    function popup(title,body,onClose,actions,subtitle,onSubmit) {
      return e(GatewayDialog,{open:true,size:`compact`,showDialogClose:!busy,contentProps:{"aria-describedby":undefined},onOpenChange:open=>{if(!open&&!busy)onClose()}},
        e(DialogLayout.Provider,{value:true},e(GatewayDialogContent,{as:`form`,size:`scrollable`,onSubmit:event=>{event.preventDefault();if(!busy)onSubmit?.()}},
          e(GatewayDialogHeader,{className:`shrink-0`},e(GatewayDialogHeading,{
            title:e(GatewayDialogTitle,null,title),subtitle:subtitle?e(GatewayDialogSubtitle,null,subtitle):undefined})),
          e(GatewayDialogHeader,{spacing:`large`,className:`min-h-0 overflow-y-auto`},body),
          e(GatewayDialogHeader,{spacing:`large`,className:`shrink-0`},e(GatewayDialogFooter,null,actions)))));
    }
    function credentials(id) {
      const entry=draft.keys[id];
      const open=!!expanded[`keys:${id}`];
      return e(li.Fragment,null,
        e(SettingsRow,{label:e(ProviderDisclosure,{label:`API keys`,open,disabled:busy,onToggle:()=>toggle(`keys:${id}`)}),
          description:`${entry.profiles.length} ${entry.profiles.length===1?`profile`:`profiles`} · Keys are stored encrypted on this device.`,control:button(`Add API key`,()=>{
          if(entry.profiles.length>=16){setStatus(`Store at most 16 keys per provider.`);setFailed(true);return}
          let number=entry.profiles.length+1;
          while(entry.profiles.some(p=>p.label.toLocaleLowerCase()===`key ${number}`))number++;
          setEditor(null);setStatus(``);setFailed(false);setNewKey({provider:id,label:`Key ${number}`,key:``});
        })}),
        open?e(li.Fragment,null,
        menuRow(`Active API key`,entry.profiles.map(k=>({value:k.id,label:k.label||`Unnamed key`})),entry.active,
          value=>edit(next=>{next.keys[id].active=value}),`Changes take effect automatically for new requests.`),
        ...entry.profiles.flatMap(profile=>{
          const key=`key:${id}:${profile.id}`;
          return [e(SettingsRow,{key:profile.id,label:profile.label||`Unnamed key`,description:profile.saved?`Saved: ********`:`No key saved`,
            control:button(expanded[key]?`Done`:`Edit`,()=>toggle(key))}),
            expanded[key]?e(li.Fragment,{key:profile.id+`-editor`},
              e(Field,{label:`Key name`,value:profile.label,maxLength:80,disabled:busy,
                onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).label=value})}),
              e(Field,{label:profile.saved?`Replace API key`:`API key`,type:`password`,value:profile.key,maxLength:4096,disabled:busy,
                onFocus:()=>setSensitiveFocus(true),onBlur:()=>setSensitiveFocus(false),
                placeholder:profile.saved?`Leave blank to keep saved key`:`Enter API key`,
                onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).key=value})}),
              !profile.existing?e(SettingsRow,{label:`Unsaved profile`,control:button(`Discard new key`,()=>edit(next=>{
                next.keys[id].profiles=next.keys[id].profiles.filter(k=>k.id!==profile.id);
                if(next.keys[id].active===profile.id)next.keys[id].active=next.keys[id].profiles.some(k=>k.id===profile.previousActive)?profile.previousActive:next.keys[id].profiles[0]?.id??null;
              }))}):e(SettingsRow,{label:`Remove saved key`,control:button(`Delete API key`,()=>setRemoval({kind:`key`,id,profile:profile.id,label:profile.label}))})):null];
        })):null);
    }
    let content=e(`p`,{className:`text-sm text-secondary`},failed?`Could not load local settings.`:`Loading local settings…`);
    if(draft&&section===`providers`)content=[
      e(Section,{key:`provider-management`,title:`Configured providers`,grouped:false,
        action:button(`Add provider`,()=>setNewProvider({id:``,label:``,adapter:`responses`,endpoint:``}))},
        e(GatewayGroup,{variant:`default`,key:`openai`},
          e(SettingsRow,{label:`ChatGPT`,description:`Built in · Uses your existing ChatGPT sign-in.`,
            control:button(`View`,()=>setEditor({kind:`provider`,id:`openai`}))})),
        ...Object.entries(draft.providers).map(([id,p])=>{
          const count=draft.models.filter(m=>m.provider===id).length;
          const saved=draft.keys[id].profiles.filter(k=>k.saved).length;
          return e(GatewayGroup,{key:id,variant:`default`},
            e(SettingsRow,{label:p.label,
              description:`${p.enabled===false?`Disabled`:`Enabled`} · ${count} ${count===1?`model`:`models`} · ${saved} saved ${saved===1?`key`:`keys`}`,
              control:e(`div`,{className:`flex items-center gap-3`},button(`Edit`,()=>setEditor({kind:`provider`,id})),
                e(GatewaySwitch,{checked:p.enabled!==false,disabled:busy,ariaLabel:`Enable ${p.label}`,onChange:value=>edit(next=>{next.providers[id].enabled=value})}))}),credentials(id));
        })),
    ];
    let editorDialog=null;
    const canAddProvider=newProvider&&/^[a-z][a-z0-9_-]{0,63}$/.test(newProvider.id)&&newProvider.id!==`openai`&&!draft?.providers[newProvider.id]&&newProvider.label.trim()&&newProvider.endpoint.startsWith(`https://`);
    const addProvider=()=>{
      if(!canAddProvider||busy)return;
      const p=newProvider,id=p.id;
      edit(next=>{
        next.providers[id]={label:p.label.trim(),adapter:p.adapter,endpoint:p.endpoint.trim(),default_model:``,enabled:true};
        next.keys[id]={active:`default`,profiles:[{id:`default`,label:`Default`,key:``,saved:false,existing:true}]};
      });setSelectedProvider(id);setNewProvider(null);setEditor({kind:`provider`,id});
    };
    if(draft&&section===`providers`&&newProvider)editorDialog=popup(`Add provider`,e(li.Fragment,null,
        e(Field,{label:`Provider ID`,value:newProvider.id,autoFocus:true,maxLength:64,disabled:busy,onChange:value=>setNewProvider({...newProvider,id:value.trim()})}),
        e(Field,{label:`Display name`,value:newProvider.label,maxLength:160,disabled:busy,onChange:value=>setNewProvider({...newProvider,label:value})}),
        menuRow(`API protocol`,[{value:`responses`,label:`Responses`},{value:`chat_completions`,label:`Chat Completions`}],newProvider.adapter,value=>setNewProvider({...newProvider,adapter:value})),
        e(Field,{label:`API URL`,type:`url`,value:newProvider.endpoint,disabled:busy,placeholder:`https://provider.example/v1/responses`,onChange:value=>setNewProvider({...newProvider,endpoint:value})}),
        e(SettingsRow,{label:`Models`,description:`Add this provider, then add its models in Models. OpenCode Zen uses its existing verified adapter.`})),
        ()=>setNewProvider(null),e(li.Fragment,null,
          e(`div`,{role:`status`,className:failed?`text-sm text-danger`:`text-sm text-secondary`},status),
          button(`Cancel`,()=>setNewProvider(null)),button(`Add provider`,addProvider,busy||!canAddProvider,`primary`,`submit`)),
        undefined,addProvider);
    if(draft&&section===`providers`&&!newProvider&&editor?.kind===`provider`) {
      const id=editor.id,p=draft.providers[id];
      if(id===`openai`)editorDialog=popup(`ChatGPT`,e(SettingsRow,{label:`Authentication`,description:`Managed by the app’s Account settings. No provider API key is needed.`}),
        ()=>setEditor(null),button(`Done`,()=>setEditor(null)),`Built-in provider`);
      else if(p)editorDialog=popup(p.label,e(li.Fragment,null,
        e(Field,{label:`Display name`,value:p.label,autoFocus:true,maxLength:160,disabled:busy,onChange:value=>edit(next=>{next.providers[id].label=value})}),
        e(Field,{label:`API URL`,value:p.endpoint,type:`url`,readOnly:p.adapter===`opencode`,disabled:busy,
          onFocus:()=>setSensitiveFocus(true),onBlur:()=>setSensitiveFocus(false),onChange:value=>edit(next=>{next.providers[id].endpoint=value})}),
        e(SettingsRow,{label:`API protocol`,control:e(`span`,{className:`text-sm text-secondary`},p.adapter===`responses`?`Responses`:p.adapter===`chat_completions`?`Chat Completions`:`OpenCode client`)}),
        menuRow(`Default model`,draft.models.filter(m=>m.provider===id).map(m=>({value:m.id,label:m.label,disabled:m.enabled===false})),p.default_model,
          value=>edit(next=>{next.providers[id].default_model=value}),draft.models.some(m=>m.provider===id)?undefined:`No models yet. Add a model in Models.`),
        p.enabled===false?e(SettingsRow,{label:`Provider disabled`,description:`Models and keys are kept. Enable to use this provider again.`}):null,
        e(SettingsRow,{label:`Remove provider`,control:button(`Delete provider`,()=>setRemoval({kind:`provider`,id,label:p.label}),busy,`danger`)})),
        ()=>setEditor(null),e(li.Fragment,null,footer,button(`Done`,()=>setEditor(null))));
    }
    if(draft&&section===`providers`&&newKey&&draft.providers[newKey.provider]) {
      const id=newKey.provider,profiles=draft.keys[id].profiles;
      const canAdd=profiles.length<16&&newKey.label.trim()&&newKey.key.trim()&&!/[\r\n\0]/.test(newKey.key)&&
        !profiles.some(p=>p.label.trim().toLocaleLowerCase()===newKey.label.trim().toLocaleLowerCase());
      const cancel=()=>{newKey.key=``;setNewKey(null)};
      const add=()=>{
        if(busy||!canAdd)return;
        const label=newKey.label.trim(),key=newKey.key.trim(),profileId=`key_`+crypto.randomUUID().replaceAll(`-`,``);
        edit(next=>{const entry=next.keys[id];entry.profiles.push({id:profileId,label,key,saved:false,existing:false,previousActive:entry.active});entry.active=profileId});
        setExpanded(previous=>({...previous,[`keys:${id}`]:true}));cancel();
      };
      editorDialog=popup(`Add API key`,e(li.Fragment,null,
        e(Field,{label:`Key name`,value:newKey.label,autoFocus:true,maxLength:80,disabled:busy,onChange:value=>setNewKey({...newKey,label:value})}),
        e(Field,{label:`API key`,type:`password`,value:newKey.key,maxLength:4096,disabled:busy,onChange:value=>setNewKey({...newKey,key:value})})),
        cancel,e(li.Fragment,null,button(`Cancel`,cancel),button(`Add API key`,add,busy||!canAdd,`primary`,`submit`)),draft.providers[id].label,add);
    }
    if(draft&&section===`models`&&providerOptions.length) {
      const pid=selectedProvider in draft.providers?selectedProvider:providerOptions[0].value;
      const p=draft.providers[pid];
      const query=modelSearch.trim().toLocaleLowerCase();
      const providerModels=draft.models.map((model,index)=>({model,index})).filter(({model})=>model.provider===pid);
      const matchingModels=providerModels.filter(({model})=>`${model.label} ${model.id}`.toLocaleLowerCase().includes(query));
      content=[e(GatewaySearch,{key:`model-search`,id:`better-codex-model-search`,autoFocus:false,inputRole:`searchbox`,label:`Search models`,
          placeholder:`Search models by name or ID`,searchQuery:modelSearch,onSearchQueryChange:setModelSearch}),
        e(GatewayGroup,{key:`provider-selector`,variant:`default`},menuRow(`Provider`,providerOptions,pid,setSelectedProvider)),
        e(Section,{key:pid,title:p.label+` models`,action:modelActions(button(`Add model`,()=>{
          edit(next=>{next.models.push(newModel(pid))});
          setModelSearch(``);
          setEditor({kind:`model`,index:draft.models.length,creating:true});
        }))},p.enabled===false?e(SettingsRow,{label:`Provider disabled`,description:`You can edit these models. Enable the provider in Providers to use them in chats.`}):null,
        !matchingModels.length?e(SettingsRow,{label:query?`No matching models`:`No models yet`,description:query?`Try another name or model ID, or clear the search.`:`Add a model for this provider.`}):null,
        ...matchingModels.map(({model,index})=>e(SettingsRow,{key:index,label:model.label||`New model`,description:(model.enabled===false?`Disabled · `:``)+(model.id||`Enter the provider’s API model ID`),
          control:e(`div`,{className:`flex items-center gap-3`},button(`Edit`,()=>setEditor({kind:`model`,index})),
            e(GatewaySwitch,{checked:model.enabled!==false,disabled:busy,ariaLabel:`Enable ${model.label||`new model`}`,onChange:value=>edit(next=>{next.models[index].enabled=value})}))})))];
    }
    if(draft&&section===`models`&&editor?.kind===`model`&&draft.models[editor.index]) {
      const index=editor.index,model=draft.models[index],pid=model.provider;
      const change=(field,value)=>edit(next=>{next.models[index][field]=value});
      const existing=!editor.creating&&snapshot.models.some(m=>m.id===model.id&&m.provider===pid);
      const discardNewModel=()=>{
        const next=structuredClone(draft);removeEntry(next,{kind:`model`,index});setDraft(next);
        setDirty(JSON.stringify(requestBody(snapshot,next))!==JSON.stringify(requestBody(snapshot,makeDraft(snapshot))));
        setStatus(``);setFailed(false);setEditor(null);
      };
      const automatic=model.metadata_mode===`provider`;
      const providerDefault=model.reasoning_mode===`provider_default`;
      const addModel=()=>{
        if(busy||!completeDraft(draft))return;
        setFailed(false);setEditor({kind:`model`,index,closeAfterSave:true});
      };
      editorDialog=popup(existing?model.label||`Edit model`:`Add model`,e(li.Fragment,null,
              e(Field,{label:`Model ID`,value:model.id,autoFocus:!existing,placeholder:pid===`openrouter`?`vendor/model or @preset/slug`:`Provider model ID`,readOnly:existing,disabled:busy,
                onBlur:!existing&&model.metadataModelId!==model.id?()=>fetchMetadata(index):undefined,onChange:value=>edit(next=>{
                  next.models[index].id=value.trim();
                  next.models[index].upstream_provider=``;
                  next.models[index].service_tier=``;
                  if(automatic)Object.assign(next.models[index],{context:``,output:``,efforts:[],default_effort:``,metadataNotes:``,metadataModelId:null});
                })}),
              e(Field,{label:`Display name`,value:model.label,autoFocus:existing,disabled:busy,onChange:value=>change(`label`,value)}),
              pid===`nanogpt`?menuRow(`Upstream provider`,upstreamChoices(model,upstreamLists[model.id]),model.upstream_provider??``,value=>change(`upstream_provider`,value),
                `Applies to this model across chats. Automatic uses NanoGPT routing. Explicit selection uses pay-as-you-go billing and bypasses subscription coverage.`):null,
              pid===`nanogpt`?menuRow(`Service tier`,serviceTierChoices(model,upstreamLists[model.id]),model.service_tier??``,value=>change(`service_tier`,value),
                `Automatic sends no tier override. Flex uses lower-cost, variable-capacity processing; Fast/Priority can cost more. A forced provider may ignore an unsupported tier.`):null,
              pid===`nanogpt`?e(SettingsRow,{label:`Routing options`,description:`Load current provider IDs and supported service tiers for this model. A selected provider may have different limits or availability.`,
                control:button(`Load providers and tiers`,()=>fetchUpstreams(index),busy||!model.id.trim())}):null,
              menuRow(`Limits and capabilities`,[{value:`provider`,label:`From provider`},{value:`custom`,label:`Customize`}],model.metadata_mode??`custom`,value=>{
                change(`metadata_mode`,value);
                if(value===`provider`)setStatus(`Use Refresh metadata to fetch the provider’s reported values. Routine saves keep the saved limits.`);
              },`Unreported values remain blank. Customize to supply missing limits or override them.`),
              automatic?e(SettingsRow,{label:`Provider metadata`,description:model.metadataNotes||`Fetched when adding a model. Use Refresh metadata to update saved limits.`,
                control:button(`Refresh metadata`,()=>fetchMetadata(index),busy||!model.id.trim())}):null,
              e(Field,{label:`Context tokens`,type:`number`,value:model.context,readOnly:automatic,placeholder:`Not reported`,min:2,max:4194304,disabled:busy,onChange:value=>change(`context`,value)}),
              e(Field,{label:`Maximum output tokens`,type:`number`,value:model.output,readOnly:automatic,placeholder:`Not reported`,min:1,max:1048576,disabled:busy,onChange:value=>change(`output`,value)}),
              !automatic?menuRow(`Reasoning control`,[{value:`provider_default`,label:`Provider default`},{value:`explicit`,label:`Choose supported efforts`}],model.reasoning_mode??`explicit`,value=>edit(next=>{
                const row=next.models[index];row.reasoning_mode=value;
                if(value===`provider_default`){row.efforts=[`none`];row.default_effort=`none`}
                else if(row.efforts.length===1&&row.efforts[0]===`none`){row.efforts=[];row.default_effort=``}
              })):null,
              automatic||providerDefault?e(SettingsRow,{label:`Supported efforts`,description:providerDefault?`No reasoning override is sent. This does not mean reasoning is disabled.`:`Exact levels reported by the provider.`,
                control:e(`span`,{className:`text-sm text-secondary`},providerDefault?`Provider default`:model.efforts.join(`, `)||`Not reported`)}):
              e(SettingsRow,{label:`Supported efforts`,description:`Choose only efforts supported by this provider.`,control:e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled:busy,
                triggerButton:e(GatewayDropdownButton,{disabled:busy,className:`w-full`,"aria-label":`Supported efforts`},model.efforts.join(`, `)),
                children:efforts.map(effort=>e(GatewayMenu.CheckboxItem,{key:effort,checked:model.efforts.includes(effort),onSelect:event=>{
                  event.preventDefault();const selected=model.efforts.includes(effort)?model.efforts.filter(e=>e!==effort):[...model.efforts,effort];
                  edit(next=>{next.models[index].efforts=selected;if(!selected.includes(next.models[index].default_effort))next.models[index].default_effort=selected[0]??``});
                }},effort))})}),
              !providerDefault?menuRow(`Default effort`,model.efforts.map(value=>({value,label:value})),model.default_effort,value=>change(`default_effort`,value)):null,
              existing?e(SettingsRow,{label:`Remove model`,control:button(`Delete model`,()=>setRemoval({kind:`model`,index,label:model.label}),busy,`danger`)}):null),
        ()=>existing?setEditor(null):discardNewModel(),e(li.Fragment,null,existing?footer:e(`div`,{role:`status`,className:`min-w-0 flex-1 text-sm `+(failed?`text-danger`:`text-secondary`)},status),
          existing?button(`Done`,()=>setEditor(null)):e(li.Fragment,null,button(`Cancel`,discardNewModel),button(`Add model`,addModel,busy||!completeDraft(draft),`primary`,`submit`))),
        draft.providers[pid].label+(existing?` · Changes save automatically.`:` · Closing discards this new model.`),existing?undefined:addModel);
    }
    if(draft&&!providerOptions.length&&section!==`providers`) {
      const empty=`No external providers. Add one in Better Codex → Providers. ChatGPT remains available.`;
      content=section===`models`?e(Section,{title:`Models`,action:modelActions(null)},e(SettingsRow,{label:`No external providers`,description:empty})):
        e(`p`,{className:`text-sm text-secondary`},empty);
    }
    const cancelEndpoint=()=>{setConfirmEndpoint(false);setFailed(true);setStatus(`API address change has not been saved.`)};
    const confirmation=e(GatewayDialog,{open:confirmEndpoint,size:`compact`,onOpenChange:open=>{if(!open)cancelEndpoint()}},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Use new API address?`),
        subtitle:e(GatewayDialogSubtitle,null,`The selected provider key will be sent to this new API address.`)})),
        e(GatewayDialogHeader,{spacing:`large`},e(GatewayDialogFooter,null,e(GatewayButton,{color:`secondary`,onClick:cancelEndpoint},`Cancel`),
          e(GatewayButton,{color:`primary`,onClick:()=>save(true)},`Use address`)))));
    const deleteConfirmation=e(GatewayDialog,{open:!!removal,size:`compact`,onOpenChange:open=>{if(!open)setRemoval(null)}},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Delete ${removal?.label??`entry`}?`),
        subtitle:e(GatewayDialogSubtitle,null,removal?.kind===`key`?`The key is removed automatically. If active, another remaining key is selected. Deleting the last key leaves this provider without credentials. Encrypted rollback copies are retained.`:
          `This deletion saves automatically. Existing chats and instruction files are kept. Chats using a removed model need another model selected. The remaining first model becomes the default if needed. Rollback copies are retained.`)})),
        e(GatewayDialogHeader,{spacing:`large`},e(GatewayDialogFooter,null,e(GatewayButton,{color:`secondary`,onClick:()=>setRemoval(null)},`Cancel`),e(GatewayButton,{color:`danger`,onClick:()=>{
          edit(next=>removeEntry(next,removal));
          setExpanded(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>removal.kind===`key`?key!==`key:${removal.id}:${removal.profile}`:
            removal.kind===`provider`?key!==`provider-${removal.id}`&&key!==`keys:${removal.id}`&&!key.startsWith(`key:${removal.id}:`):!key.startsWith(`model-`))));
          if(removal.kind!==`key`)setEditor(null);
          setRemoval(null);
        }},`Delete`)))));
    return e(li.Fragment,null,e(GatewaySettingsPage,{title:labels[section]??labels.providers,subtitle:`Better Codex`,footer,scrollResetKey:section},content),editorDialog,confirmation,deleteConfirmation);
  };
  globalThis.gatewayNativeSettingsControls = {DialogLayout,SettingsRow,Action,Dropdown,Field,Section,ProviderDisclosure,makeDraft,requestBody,clearKeys,newModel,applyMetadata,upstreamChoices,serviceTierChoices,removeEntry,completeDraft};
})();
