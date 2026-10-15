// Rendered in the verified Settings module with its original UI primitives.
// New key values live only in this editor's memory and are cleared on save/leave.
(() => {
  const e = (...args) => li.createElement(...args);
  const efforts = [`none`,`minimal`,`low`,`medium`,`high`,`xhigh`,`max`,`ultra`];
  const labels = {providers:`Providers`,models:`Models`};
  function Dropdown({label,options,value,onChange,disabled}) {
    const selected = options.find(option => option.value === value)?.label ?? `Choose…`;
    return e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled,
      triggerButton:e(GatewayDropdownButton,{"aria-label":label,disabled,className:`max-w-64`,children:e(`span`,{className:`truncate`},selected)}),
      children:e(`div`,{className:`max-h-80 overflow-y-auto`},e(GatewayMenu.RadioGroup,{value},
        options.map(option => e(GatewayMenu.RadioItem,{key:option.value,value:option.value,disabled:option.disabled,onSelect:()=>onChange(option.value)},option.label))))});
  }
  function Field({label,value,onChange,onBlur,onFocus,type=`text`,readOnly=false,placeholder,maxLength,min,max,disabled}) {
    return e(GatewayRow,{label,control:accessibility=>e(GatewayInput,{...accessibility,variant:`settings`,
      className:`w-64 max-w-full`,type,value:value??``,readOnly,disabled,placeholder,maxLength,min,max,
      autoComplete:type===`password`?`new-password`:`off`,spellCheck:false,onFocus,onBlur,onChange:event=>onChange?.(event.target.value)})});
  }
  function Section({title,children,action,grouped=true}) {
    return e(`section`,{"aria-label":title},e(`div`,{className:`mb-3 flex items-center justify-between gap-3`},
      e(`h2`,{className:`text-sm font-semibold`},title),action),grouped?e(GatewayGroup,{variant:`default`},children):e(`div`,{className:`flex flex-col gap-3`},children));
  }
  function ProviderDisclosure({label,open,onToggle,disabled}) {
    return e(`button`,{type:`button`,disabled,"aria-expanded":open,onClick:onToggle,
      className:`flex min-w-0 cursor-interaction items-center gap-2 rounded-sm text-left font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`},
      e(`span`,{"aria-hidden":true,className:`shrink-0 transition-transform duration-basic `+(open?`rotate-90`:``)},`›`),
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
  function requestBody(snapshot,draft) {
    return {action:`save`,revision:snapshot.revision,
      providers:Object.fromEntries(Object.entries(draft.providers).map(([id,p])=>[id,{label:p.label,adapter:p.adapter,endpoint:p.endpoint,default_model:p.default_model,enabled:p.enabled!==false}])),
      models:draft.models.map(m=>({id:m.id,provider:m.provider,label:m.label,context:Number(m.context),output:Number(m.output),enabled:m.enabled!==false,
        efforts:m.efforts,default_effort:m.default_effort,metadata_mode:m.metadata_mode??`custom`,reasoning_mode:m.reasoning_mode??`explicit`})),
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
    const latest = li.useRef(null);
    latest.current=draft;
    GatewayDirtySettings(`better-codex-settings`,dirty||busy);
    li.useEffect(()=>{setEditor(section===`providers`&&provider?{kind:`provider`,id:provider}:null);setNewProvider(null)},[section,provider]);
    li.useEffect(()=>{
      let cancelled=false;
      globalThis.gatewaySettingsRequest({action:`get`}).then(value=>{
        if(cancelled)return;
        setSnapshot(value);setDraft(makeDraft(value));
        setSelectedProvider(provider in value.providers?provider:Object.keys(value.providers)[0]);
      }).catch(error=>{if(!cancelled){setStatus(error.message);setFailed(true)}});
      return()=>{cancelled=true;clearKeys(latest.current)};
    },[]);
    function edit(change) {
      setDraft(previous=>{const next=structuredClone(previous);change(next);return next});
      setDirty(true);setStatus(``);setFailed(false);
    }
    function toggle(id) {setExpanded(previous=>({...previous,[id]:!previous[id]}))}
    const button=(text,onClick,disabled=busy)=>e(GatewayButton,{size:`toolbar`,color:`secondary`,onClick,disabled},text);
    const providerOptions=draft?Object.entries(draft.providers).map(([value,p])=>({value,label:p.label+(p.enabled===false?` (disabled)`:``)})):[];
    const menuRow=(label,options,value,onChange,description)=>e(GatewayRow,{label,description,
      control:e(Dropdown,{label,options,value,onChange,disabled:busy})});
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
    async function save(confirmed=false) {
      if(busy||!dirty||!draft||editor?.creating||!completeDraft(draft))return;
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
      if(!dirty||!draft||!snapshot||busy||failed||sensitiveFocus||confirmEndpoint||newProvider||editor?.creating)return;
      if(!completeDraft(draft)){setStatus(`Complete the required fields to save automatically.`);return}
      if(JSON.stringify(requestBody(snapshot,draft))===JSON.stringify(requestBody(snapshot,makeDraft(snapshot)))){setDirty(false);setStatus(`All changes saved.`);return}
      setStatus(`Changes will save automatically…`);
      const timer=setTimeout(()=>save(),400);
      return()=>clearTimeout(timer);
    },[draft,dirty,snapshot,busy,failed,sensitiveFocus,confirmEndpoint,newProvider,editor?.creating]);
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
    function popup(title,body,onClose,actions,subtitle=`Changes save automatically.`) {
      return e(GatewayDialog,{open:true,size:`default`,showDialogClose:!busy,onOpenChange:open=>{if(!open&&!busy)onClose()}},
        e(GatewayDialogContent,{size:`scrollable`},
          e(GatewayDialogHeader,{className:`shrink-0`},e(GatewayDialogHeading,{
            title:e(GatewayDialogTitle,null,title),subtitle:e(GatewayDialogSubtitle,null,subtitle)})),
          e(`div`,{className:`min-h-0 overflow-y-auto`},e(GatewayGroup,{variant:`default`},body)),
          e(GatewayDialogFooter,{className:`shrink-0`},actions)));
    }
    function credentials(id) {
      const entry=draft.keys[id];
      const open=!!expanded[`keys:${id}`];
      return e(li.Fragment,null,
        e(GatewayRow,{label:e(ProviderDisclosure,{label:`API keys`,open,disabled:busy,onToggle:()=>toggle(`keys:${id}`)}),
          description:`${entry.profiles.length} ${entry.profiles.length===1?`profile`:`profiles`} · Keys are stored encrypted on this device.`,control:button(`Add API key`,()=>{
          if(entry.profiles.length>=16){setStatus(`Store at most 16 keys per provider.`);setFailed(true);return}
          const profileId=`key_`+crypto.randomUUID().replaceAll(`-`,``);
          edit(next=>{const keys=next.keys[id];keys.profiles.push({id:profileId,label:`Key ${keys.profiles.length+1}`,key:``,saved:false,existing:false,previousActive:keys.active});keys.active=profileId});
          setExpanded(previous=>({...previous,[`keys:${id}`]:true,[`key:${id}:${profileId}`]:true}));
        })}),
        open?e(li.Fragment,null,
        menuRow(`Active API key`,entry.profiles.map(k=>({value:k.id,label:k.label||`Unnamed key`})),entry.active,
          value=>edit(next=>{next.keys[id].active=value}),`Changes take effect automatically for new requests.`),
        ...entry.profiles.flatMap(profile=>{
          const key=`key:${id}:${profile.id}`;
          return [e(GatewayRow,{key:profile.id,label:profile.label||`Unnamed key`,description:profile.saved?`Saved: ********`:`No key saved`,
            control:button(expanded[key]?`Done`:`Edit`,()=>toggle(key))}),
            expanded[key]?e(li.Fragment,{key:profile.id+`-editor`},
              e(Field,{label:`Key name`,value:profile.label,maxLength:80,disabled:busy,
                onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).label=value})}),
              e(Field,{label:profile.saved?`Replace API key`:`API key`,type:`password`,value:profile.key,maxLength:4096,disabled:busy,
                onFocus:()=>setSensitiveFocus(true),onBlur:()=>setSensitiveFocus(false),
                placeholder:profile.saved?`Leave blank to keep saved key`:`Enter API key`,
                onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).key=value})}),
              !profile.existing?e(GatewayRow,{label:`Unsaved profile`,control:button(`Discard new key`,()=>edit(next=>{
                next.keys[id].profiles=next.keys[id].profiles.filter(k=>k.id!==profile.id);
                if(next.keys[id].active===profile.id)next.keys[id].active=next.keys[id].profiles.some(k=>k.id===profile.previousActive)?profile.previousActive:next.keys[id].profiles[0]?.id??null;
              }))}):e(GatewayRow,{label:`Remove saved key`,control:button(`Delete API key`,()=>setRemoval({kind:`key`,id,profile:profile.id,label:profile.label}))})):null];
        })):null);
    }
    let content=e(`p`,{className:`text-sm text-secondary`},failed?`Could not load local settings.`:`Loading local settings…`);
    if(draft&&section===`providers`)content=[
      e(Section,{key:`provider-management`,title:`Configured providers`,grouped:false,
        action:button(`Add provider`,()=>setNewProvider({id:``,label:``,adapter:`responses`,endpoint:``}))},
        e(GatewayGroup,{variant:`default`,key:`openai`},
          e(GatewayRow,{label:`ChatGPT`,description:`Built in · Uses your existing ChatGPT sign-in.`,
            control:button(`View`,()=>setEditor({kind:`provider`,id:`openai`}))})),
        ...Object.entries(draft.providers).map(([id,p])=>{
          const count=draft.models.filter(m=>m.provider===id).length;
          const saved=draft.keys[id].profiles.filter(k=>k.saved).length;
          return e(GatewayGroup,{key:id,variant:`default`},
            e(GatewayRow,{label:p.label,
              description:`${p.enabled===false?`Disabled`:`Enabled`} · ${count} ${count===1?`model`:`models`} · ${saved} saved ${saved===1?`key`:`keys`}`,
              control:e(`div`,{className:`flex items-center gap-3`},button(`Edit`,()=>setEditor({kind:`provider`,id})),
                e(GatewaySwitch,{checked:p.enabled!==false,disabled:busy,ariaLabel:`Enable ${p.label}`,onChange:value=>edit(next=>{next.providers[id].enabled=value})}))}),credentials(id));
        })),
    ];
    let editorDialog=null;
    if(draft&&section===`providers`&&newProvider)editorDialog=popup(`New provider`,e(li.Fragment,null,
        e(Field,{label:`Provider ID`,value:newProvider.id,maxLength:64,disabled:busy,onChange:value=>setNewProvider({...newProvider,id:value.trim()})}),
        e(Field,{label:`Display name`,value:newProvider.label,maxLength:160,disabled:busy,onChange:value=>setNewProvider({...newProvider,label:value})}),
        menuRow(`API protocol`,[{value:`responses`,label:`Responses`},{value:`chat_completions`,label:`Chat Completions`}],newProvider.adapter,value=>setNewProvider({...newProvider,adapter:value})),
        e(Field,{label:`API URL`,type:`url`,value:newProvider.endpoint,disabled:busy,placeholder:`https://provider.example/v1/responses`,onChange:value=>setNewProvider({...newProvider,endpoint:value})}),
        e(GatewayRow,{label:`Models`,description:`Add this provider, then add its models in Models. OpenCode Zen uses its existing verified adapter.`})),
        ()=>setNewProvider(null),e(li.Fragment,null,
          e(`div`,{role:`status`,className:failed?`text-sm text-danger`:`text-sm text-secondary`},status),
          button(`Cancel`,()=>setNewProvider(null)),button(`Add provider`,()=>{
          const p=newProvider,id=p.id;
          if(!/^[a-z][a-z0-9_-]{0,63}$/.test(id)||id===`openai`||draft.providers[id]||!p.label.trim()||!p.endpoint.startsWith(`https://`)){setStatus(`Enter a unique provider ID, name and HTTPS API URL.`);setFailed(true);return}
          edit(next=>{
            next.providers[id]={label:p.label.trim(),adapter:p.adapter,endpoint:p.endpoint.trim(),default_model:``,enabled:true};
            next.keys[id]={active:`default`,profiles:[{id:`default`,label:`Default`,key:``,saved:false,existing:true}]};
          });setSelectedProvider(id);setNewProvider(null);setEditor({kind:`provider`,id});
        })));
    if(draft&&section===`providers`&&!newProvider&&editor?.kind===`provider`) {
      const id=editor.id,p=draft.providers[id];
      if(id===`openai`)editorDialog=popup(`ChatGPT`,e(GatewayRow,{label:`Authentication`,description:`Managed by the app’s Account settings. No provider API key is needed.`}),
        ()=>setEditor(null),button(`Done`,()=>setEditor(null)),`Built-in provider`);
      else if(p)editorDialog=popup(p.label,e(li.Fragment,null,
        e(Field,{label:`Display name`,value:p.label,maxLength:160,disabled:busy,onChange:value=>edit(next=>{next.providers[id].label=value})}),
        e(Field,{label:`API URL`,value:p.endpoint,type:`url`,readOnly:p.adapter===`opencode`,disabled:busy,
          onFocus:()=>setSensitiveFocus(true),onBlur:()=>setSensitiveFocus(false),onChange:value=>edit(next=>{next.providers[id].endpoint=value})}),
        e(GatewayRow,{label:`API protocol`,control:e(`span`,{className:`text-sm text-secondary`},p.adapter===`responses`?`Responses`:p.adapter===`chat_completions`?`Chat Completions`:`OpenCode client`)}),
        menuRow(`Default model`,draft.models.filter(m=>m.provider===id).map(m=>({value:m.id,label:m.label,disabled:m.enabled===false})),p.default_model,
          value=>edit(next=>{next.providers[id].default_model=value}),draft.models.some(m=>m.provider===id)?undefined:`No models yet. Add a model in Models.`),
        p.enabled===false?e(GatewayRow,{label:`Provider disabled`,description:`Models and keys are kept. Enable to use this provider again.`}):null,
        e(GatewayRow,{label:`Remove provider`,control:button(`Delete provider`,()=>setRemoval({kind:`provider`,id,label:p.label}))})),
        ()=>setEditor(null),e(li.Fragment,null,button(`Done`,()=>setEditor(null)),footer));
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
        }))},p.enabled===false?e(GatewayRow,{label:`Provider disabled`,description:`You can edit these models. Enable the provider in Providers to use them in chats.`}):null,
        !matchingModels.length?e(GatewayRow,{label:query?`No matching models`:`No models yet`,description:query?`Try another name or model ID, or clear the search.`:`Add a model for this provider.`}):null,
        ...matchingModels.map(({model,index})=>e(GatewayRow,{key:index,label:model.label||`New model`,description:(model.enabled===false?`Disabled · `:``)+(model.id||`Enter the provider’s API model ID`),
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
      editorDialog=popup(existing?model.label||`Edit model`:`New model`,e(li.Fragment,null,
              e(Field,{label:`Model ID`,value:model.id,placeholder:pid===`openrouter`?`vendor/model or @preset/slug`:`Provider model ID`,readOnly:existing,disabled:busy,
                onBlur:!existing&&model.metadataModelId!==model.id?()=>fetchMetadata(index):undefined,onChange:value=>edit(next=>{
                  next.models[index].id=value.trim();
                  if(automatic)Object.assign(next.models[index],{context:``,output:``,efforts:[],default_effort:``,metadataNotes:``,metadataModelId:null});
                })}),
              e(Field,{label:`Display name`,value:model.label,disabled:busy,onChange:value=>change(`label`,value)}),
              menuRow(`Limits and capabilities`,[{value:`provider`,label:`From provider`},{value:`custom`,label:`Customize`}],model.metadata_mode??`custom`,value=>{
                change(`metadata_mode`,value);
                if(value===`provider`)setStatus(`Use Refresh metadata to fetch the provider’s reported values. Routine saves keep the saved limits.`);
              },`Unreported values remain blank. Customize to supply missing limits or override them.`),
              automatic?e(GatewayRow,{label:`Provider metadata`,description:model.metadataNotes||`Fetched when adding a model. Use Refresh metadata to update saved limits.`,
                control:button(`Refresh metadata`,()=>fetchMetadata(index),busy||!model.id.trim())}):null,
              e(Field,{label:`Context tokens`,type:`number`,value:model.context,readOnly:automatic,placeholder:`Not reported`,min:2,max:4194304,disabled:busy,onChange:value=>change(`context`,value)}),
              e(Field,{label:`Maximum output tokens`,type:`number`,value:model.output,readOnly:automatic,placeholder:`Not reported`,min:1,max:1048576,disabled:busy,onChange:value=>change(`output`,value)}),
              !automatic?menuRow(`Reasoning control`,[{value:`provider_default`,label:`Provider default`},{value:`explicit`,label:`Choose supported efforts`}],model.reasoning_mode??`explicit`,value=>edit(next=>{
                const row=next.models[index];row.reasoning_mode=value;
                if(value===`provider_default`){row.efforts=[`none`];row.default_effort=`none`}
                else if(row.efforts.length===1&&row.efforts[0]===`none`){row.efforts=[];row.default_effort=``}
              })):null,
              automatic||providerDefault?e(GatewayRow,{label:`Supported efforts`,description:providerDefault?`No reasoning override is sent. This does not mean reasoning is disabled.`:`Exact levels reported by the provider.`,
                control:e(`span`,{className:`text-sm text-secondary`},providerDefault?`Provider default`:model.efforts.join(`, `)||`Not reported`)}):
              e(GatewayRow,{label:`Supported efforts`,description:`Choose only efforts supported by this provider.`,control:e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled:busy,
                triggerButton:e(GatewayDropdownButton,{disabled:busy,"aria-label":`Supported efforts`},model.efforts.join(`, `)),
                children:efforts.map(effort=>e(GatewayMenu.CheckboxItem,{key:effort,checked:model.efforts.includes(effort),onSelect:event=>{
                  event.preventDefault();const selected=model.efforts.includes(effort)?model.efforts.filter(e=>e!==effort):[...model.efforts,effort];
                  edit(next=>{next.models[index].efforts=selected;if(!selected.includes(next.models[index].default_effort))next.models[index].default_effort=selected[0]??``});
                }},effort))})}),
              !providerDefault?menuRow(`Default effort`,model.efforts.map(value=>({value,label:value})),model.default_effort,value=>change(`default_effort`,value)):null,
              e(GatewayRow,{label:existing?`Remove model`:`Unsaved model`,control:button(existing?`Delete model`:`Discard new model`,()=>{
                if(existing)setRemoval({kind:`model`,index,label:model.label});
                else discardNewModel();
              })})),()=>existing?setEditor(null):discardNewModel(),e(li.Fragment,null,
                existing?button(`Done`,()=>setEditor(null)):button(`Add model`,()=>{
                  if(!completeDraft(draft)){setStatus(`Complete the model details before adding it.`);return}
                  setFailed(false);setEditor({kind:`model`,index,closeAfterSave:true});
                }),footer),
        draft.providers[pid].label+(existing?` · Changes save automatically.`:` · Complete the details and choose Add model. Closing discards this new model.`));
    }
    if(draft&&!providerOptions.length&&section!==`providers`) {
      const empty=`No external providers. Add one in Better Codex → Providers. ChatGPT remains available.`;
      content=section===`models`?e(Section,{title:`Models`,action:modelActions(null)},e(GatewayRow,{label:`No external providers`,description:empty})):
        e(`p`,{className:`text-sm text-secondary`},empty);
    }
    const cancelEndpoint=()=>{setConfirmEndpoint(false);setFailed(true);setStatus(`API address change has not been saved.`)};
    const confirmation=e(GatewayDialog,{open:confirmEndpoint,size:`compact`,onOpenChange:open=>{if(!open)cancelEndpoint()}},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Use new API address?`),
        subtitle:e(GatewayDialogSubtitle,null,`The selected provider key will be sent to this new API address.`)})),
        e(GatewayDialogFooter,null,button(`Cancel`,cancelEndpoint),
          e(GatewayButton,{size:`toolbar`,color:`primary`,onClick:()=>save(true)},`Use address`))));
    const deleteConfirmation=e(GatewayDialog,{open:!!removal,size:`compact`,onOpenChange:open=>{if(!open)setRemoval(null)}},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Delete ${removal?.label??`entry`}?`),
        subtitle:e(GatewayDialogSubtitle,null,removal?.kind===`key`?`The key is removed automatically. If active, another remaining key is selected. Deleting the last key leaves this provider without credentials. Encrypted rollback copies are retained.`:
          `This deletion saves automatically. Existing chats and instruction files are kept. Chats using a removed model need another model selected. The remaining first model becomes the default if needed. Rollback copies are retained.`)})),
        e(GatewayDialogFooter,null,button(`Cancel`,()=>setRemoval(null)),e(GatewayButton,{size:`toolbar`,color:`primary`,onClick:()=>{
          edit(next=>removeEntry(next,removal));
          setExpanded(previous=>Object.fromEntries(Object.entries(previous).filter(([key])=>removal.kind===`key`?key!==`key:${removal.id}:${removal.profile}`:
            removal.kind===`provider`?key!==`provider-${removal.id}`&&key!==`keys:${removal.id}`&&!key.startsWith(`key:${removal.id}:`):!key.startsWith(`model-`))));
          if(removal.kind!==`key`)setEditor(null);
          setRemoval(null);
        }},`Delete`))));
    return e(li.Fragment,null,e(GatewaySettingsPage,{title:labels[section]??labels.providers,subtitle:`Better Codex`,footer,scrollResetKey:section},content),editorDialog,confirmation,deleteConfirmation);
  };
  globalThis.gatewayNativeSettingsControls = {Dropdown,Field,Section,ProviderDisclosure,makeDraft,requestBody,clearKeys,newModel,applyMetadata,removeEntry,completeDraft};
})();
