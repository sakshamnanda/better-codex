// Rendered in the verified Settings module with its original UI primitives.
// New key values live only in this editor's memory and are cleared on save/leave.
(() => {
  const e = (...args) => li.createElement(...args);
  const efforts = [`none`,`minimal`,`low`,`medium`,`high`,`xhigh`,`max`,`ultra`];
  const labels = {providers:`Providers`,keys:`API keys`,models:`Models`};
  function Dropdown({label,options,value,onChange,disabled}) {
    const selected = options.find(option => option.value === value)?.label ?? `Choose…`;
    return e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled,
      triggerButton:e(GatewayDropdownButton,{"aria-label":label,disabled,className:`max-w-64`,children:e(`span`,{className:`truncate`},selected)}),
      children:e(`div`,{className:`max-h-80 overflow-y-auto`},e(GatewayMenu.RadioGroup,{value},
        options.map(option => e(GatewayMenu.RadioItem,{key:option.value,value:option.value,disabled:option.disabled,onSelect:()=>onChange(option.value)},option.label))))});
  }
  function Field({label,value,onChange,onBlur,type=`text`,readOnly=false,placeholder,maxLength,min,max,disabled}) {
    return e(GatewayRow,{label,control:accessibility=>e(GatewayInput,{...accessibility,variant:`settings`,
      className:`w-64 max-w-full`,type,value:value??``,readOnly,disabled,placeholder,maxLength,min,max,
      autoComplete:type===`password`?`new-password`:`off`,spellCheck:false,onBlur,onChange:event=>onChange?.(event.target.value)})});
  }
  function Section({title,children,action}) {
    return e(`section`,{"aria-label":title},e(`div`,{className:`mb-3 flex items-center justify-between gap-3`},
      e(`h2`,{className:`text-sm font-semibold`},title),action),e(GatewayGroup,{variant:`default`},children));
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
    return {provider,id:``,label:``,context:``,output:``,efforts:[],default_effort:``,metadata_mode:`provider`,reasoning_mode:`provider_default`};
  }
  function applyMetadata(model,info) {
    return {...model,label:model.label||info.label,context:info.context??``,output:info.output??``,
      efforts:info.efforts??[`none`],default_effort:info.efforts?.includes(model.default_effort)?model.default_effort:info.default_effort??`none`,
      reasoning_mode:info.efforts?`explicit`:`provider_default`,metadataNotes:info.notes.join(` `)};
  }
  function requestBody(snapshot,draft) {
    return {action:`save`,revision:snapshot.revision,
      providers:Object.fromEntries(Object.entries(draft.providers).map(([id,p])=>[id,{endpoint:p.endpoint,default_model:p.default_model}])),
      models:draft.models.map(m=>({id:m.id,provider:m.provider,label:m.label,context:Number(m.context),output:Number(m.output),
        efforts:m.efforts,default_effort:m.default_effort,metadata_mode:m.metadata_mode??`custom`,reasoning_mode:m.reasoning_mode??`explicit`})),
      keys:Object.fromEntries(Object.entries(draft.keys).map(([id,p])=>[id,{active:p.active,profiles:p.profiles.map(k=>({id:k.id,label:k.label.trim(),key:k.key}))}]))};
  }
  globalThis.gatewaySettingsComponent = function BetterCodexSettingsPage({section=`providers`,provider,onClose}) {
    const [snapshot,setSnapshot] = li.useState(null);
    const [draft,setDraft] = li.useState(null);
    const [busy,setBusy] = li.useState(false);
    const [dirty,setDirty] = li.useState(false);
    const [status,setStatus] = li.useState(``);
    const [failed,setFailed] = li.useState(false);
    const [selectedProvider,setSelectedProvider] = li.useState(provider??``);
    const [expanded,setExpanded] = li.useState({});
    const [confirmEndpoint,setConfirmEndpoint] = li.useState(false);
    const latest = li.useRef(null);
    latest.current=draft;
    GatewayDirtySettings(`better-codex-settings`,dirty||busy);
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
    const providerOptions=draft?Object.entries(draft.providers).map(([value,p])=>({value,label:p.label})):[];
    const menuRow=(label,options,value,onChange,description)=>e(GatewayRow,{label,description,
      control:e(Dropdown,{label,options,value,onChange,disabled:busy})});
    async function fetchMetadata(index) {
      const model=latest.current?.models[index];
      if(busy||!model?.id.trim()||model.metadata_mode!==`provider`)return;
      const pid=model.provider;
      const keys=latest.current.keys[pid];
      if(latest.current.providers[pid].endpoint!==snapshot.providers[pid].endpoint||keys.active!==snapshot.providers[pid].credential_profiles.active||keys.profiles.some(k=>k.key)) {
        setStatus(`Save provider URL or API-key changes before fetching metadata. Save also refreshes automatic model metadata using your selected key.`);setFailed(true);return;
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
      if(busy||!dirty||!draft)return;
      if(!confirmed&&Object.entries(draft.providers).some(([id,p])=>p.endpoint!==snapshot.providers[id].endpoint)){setConfirmEndpoint(true);return}
      setConfirmEndpoint(false);
      setBusy(true);setFailed(false);setStatus(`Preparing the next launch…`);
      let body=requestBody(snapshot,draft);
      try {
        const result=await globalThis.gatewaySettingsRequest(body);
        if(result.live_applied)globalThis.gatewayUpdateProviderConfig?.(result.provider_config);
        clearKeys(latest.current);setSnapshot(result.settings);setDraft(makeDraft(result.settings));
        setDirty(false);setStatus(result.message);
      } catch(error){setFailed(true);setStatus(error.message)}
      finally {
        clearKeys(body);body=null;
        setDraft(previous=>{const next=structuredClone(previous);clearKeys(next);return next});setBusy(false);
      }
    }
    async function applyLive() {
      if(busy||dirty||!snapshot?.live_supported)return;
      setBusy(true);setStatus(`Applying verified settings between requests…`);setFailed(false);
      try {
        const result=await globalThis.gatewaySettingsRequest({action:`apply_live`,revision:snapshot.revision});
        if(result.live_applied)globalThis.gatewayUpdateProviderConfig?.(result.provider_config);
        setSnapshot(result.settings);setDraft(makeDraft(result.settings));setStatus(result.message);
      } catch(error){setStatus(error.message);setFailed(true)}
      finally {setBusy(false)}
    }
    const footer=e(li.Fragment,null,
      e(`div`,{role:`status`,className:`min-w-0 flex-1 text-sm `+(failed?`text-danger`:`text-secondary`)},status),
      dirty?button(`Discard changes`,()=>{clearKeys(latest.current);setDraft(makeDraft(snapshot));setDirty(false);setStatus(``);setFailed(false)}):null,
      onClose?button(`Back`,onClose):null,
      snapshot?.live_supported?button(`Apply live`,applyLive,busy||dirty):null,
      e(GatewayButton,{size:`toolbar`,color:`primary`,loading:busy,disabled:busy||!dirty,onClick:()=>save()},snapshot?.live_supported?`Save and apply`:`Save for next launch`));
    let content=e(`p`,{className:`text-sm text-secondary`},failed?`Could not load local settings.`:`Loading local settings…`);
    if(draft&&section===`providers`)content=Object.entries(draft.providers).map(([id,p])=>e(Section,{key:id,title:p.label},
      e(Field,{label:`API URL`,value:p.endpoint,type:`url`,readOnly:p.adapter===`opencode`,disabled:busy,
        onChange:value=>edit(next=>{next.providers[id].endpoint=value})}),
      menuRow(`Default model`,draft.models.filter(m=>m.provider===id).map(m=>({value:m.id,label:m.label})),p.default_model,
        value=>edit(next=>{next.providers[id].default_model=value})),
      p.adapter===`opencode`?e(GatewayRow,{label:`Endpoint management`,control:e(`span`,{className:`text-sm text-secondary`},`OpenCode client`)}):null));
    if(draft&&section===`keys`)content=Object.entries(draft.keys).map(([id,entry])=>{
      const p=draft.providers[id];
      return e(Section,{key:id,title:p.label,action:button(`Add API key`,()=>{
        if(entry.profiles.length>=16){setStatus(`Store at most 16 keys per provider.`);setFailed(true);return}
        const profileId=`key_`+crypto.randomUUID().replaceAll(`-`,``);
        edit(next=>{next.keys[id].profiles.push({id:profileId,label:`Key ${entry.profiles.length+1}`,key:``,saved:false,existing:false,previousActive:entry.active});next.keys[id].active=profileId});
        setExpanded(previous=>({...previous,[profileId]:true}));
      })},menuRow(`Active API key`,entry.profiles.map(k=>({value:k.id,label:k.label||`Unnamed key`})),entry.active,
        value=>edit(next=>{next.keys[id].active=value}),snapshot.live_supported?`The selected profile is used by new requests after Save and apply.`:`This running helper applies the selected profile after relaunch.`),
        ...entry.profiles.flatMap(profile=>[
          e(GatewayRow,{key:profile.id,label:profile.label||`Unnamed key`,description:profile.saved?`Saved: ********`:`New key`,
            control:button(expanded[profile.id]?`Done`:`Edit`,()=>toggle(profile.id))}),
          expanded[profile.id]?e(li.Fragment,{key:profile.id+`-editor`},
            e(Field,{label:`Key name`,value:profile.label,maxLength:80,disabled:busy,
              onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).label=value})}),
            e(Field,{label:profile.saved?`Replace API key`:`API key`,type:`password`,value:profile.key,maxLength:4096,disabled:busy,
              placeholder:profile.saved?`Leave blank to keep saved key`:`Enter API key`,
              onChange:value=>edit(next=>{next.keys[id].profiles.find(k=>k.id===profile.id).key=value})}),
            !profile.existing?e(GatewayRow,{label:`Unsaved profile`,control:button(`Discard new key`,()=>edit(next=>{
              next.keys[id].profiles=next.keys[id].profiles.filter(k=>k.id!==profile.id);
              if(next.keys[id].active===profile.id)next.keys[id].active=next.keys[id].profiles.some(k=>k.id===profile.previousActive)?profile.previousActive:next.keys[id].profiles[0].id;
            }))}):null):null,
        ]));
    });
    if(draft&&section===`models`) {
      const pid=selectedProvider in draft.providers?selectedProvider:providerOptions[0].value;
      const p=draft.providers[pid];
      content=[e(GatewayGroup,{key:`provider-selector`,variant:`default`},menuRow(`Provider`,providerOptions,pid,setSelectedProvider)),
        e(Section,{key:pid,title:p.label+` models`,action:button(`Add model`,()=>{
          edit(next=>{next.models.push(newModel(pid))});
          setExpanded(previous=>({...previous,[`model-`+draft.models.length]:true}));
        })},...draft.models.map((model,index)=>({model,index})).filter(({model})=>model.provider===pid).flatMap(({model,index})=>{
          const key=`model-`+index;
          const change=(field,value)=>edit(next=>{next.models[index][field]=value});
          const existing=snapshot.models.some(m=>m.id===model.id);
          const automatic=model.metadata_mode===`provider`;
          const providerDefault=model.reasoning_mode===`provider_default`;
          return [e(GatewayRow,{key,label:model.label||`New model`,description:model.id||`Enter the provider’s API model ID`,control:button(expanded[key]?`Done`:`Edit`,()=>toggle(key))}),
            expanded[key]?e(li.Fragment,{key:key+`-editor`},
              e(Field,{label:`Model ID`,value:model.id,placeholder:pid===`openrouter`?`vendor/model or @preset/slug`:`Provider model ID`,readOnly:existing,disabled:busy,
                onBlur:()=>fetchMetadata(index),onChange:value=>edit(next=>{
                  next.models[index].id=value.trim();
                  if(automatic)Object.assign(next.models[index],{context:``,output:``,efforts:[],default_effort:``,metadataNotes:``});
                })}),
              e(Field,{label:`Display name`,value:model.label,disabled:busy,onChange:value=>change(`label`,value)}),
              menuRow(`Limits and capabilities`,[{value:`provider`,label:`From provider`},{value:`custom`,label:`Customize`}],model.metadata_mode??`custom`,value=>{
                change(`metadata_mode`,value);
                if(value===`provider`)setStatus(`Use Refresh metadata to fetch the provider’s reported values. They are also refreshed when you save.`);
              },`Unreported values remain blank. Customize to supply missing limits or override them.`),
              automatic?e(GatewayRow,{label:`Provider metadata`,description:model.metadataNotes||`Fetched after entering the model ID and verified again when saving.`,
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
              !existing?e(GatewayRow,{label:`Unsaved model`,control:button(`Discard new model`,()=>edit(next=>{next.models.splice(index,1)}))}):null):null];
        }))];
    }
    const confirmation=e(GatewayDialog,{open:confirmEndpoint,size:`compact`,onOpenChange:setConfirmEndpoint},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Save provider URL changes?`),
        subtitle:e(GatewayDialogSubtitle,null,snapshot?.live_supported?`The selected provider key will be sent to the new API address after Save and apply.`:`The selected provider key will be sent to the new API address after relaunch.`)})),
        e(GatewayDialogFooter,null,button(`Cancel`,()=>setConfirmEndpoint(false)),
          e(GatewayButton,{size:`toolbar`,color:`primary`,onClick:()=>save(true)},`Save changes`))));
    return e(li.Fragment,null,e(GatewaySettingsPage,{title:labels[section]??labels.providers,subtitle:`Better Codex`,footer,scrollResetKey:section},content),confirmation);
  };
  globalThis.gatewayNativeSettingsControls = {Dropdown,Field,Section,makeDraft,requestBody,clearKeys,newModel,applyMetadata};
})();
