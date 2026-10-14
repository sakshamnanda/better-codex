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
  function Field({label,value,onChange,type=`text`,readOnly=false,placeholder,maxLength,min,max,disabled}) {
    return e(GatewayRow,{label,control:accessibility=>e(GatewayInput,{...accessibility,variant:`settings`,
      className:`w-64 max-w-full`,type,value:value??``,readOnly,disabled,placeholder,maxLength,min,max,
      autoComplete:type===`password`?`new-password`:`off`,spellCheck:false,onChange:event=>onChange?.(event.target.value)})});
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
  function requestBody(snapshot,draft) {
    return {action:`save`,revision:snapshot.revision,
      providers:Object.fromEntries(Object.entries(draft.providers).map(([id,p])=>[id,{endpoint:p.endpoint,default_model:p.default_model}])),
      models:draft.models.map(m=>({...m,context:Number(m.context),output:Number(m.output)})),
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
    async function save(confirmed=false) {
      if(busy||!dirty||!draft)return;
      if(!confirmed&&Object.entries(draft.providers).some(([id,p])=>p.endpoint!==snapshot.providers[id].endpoint)){setConfirmEndpoint(true);return}
      setConfirmEndpoint(false);
      setBusy(true);setFailed(false);setStatus(`Preparing the next launch…`);
      let body=requestBody(snapshot,draft);
      try {
        const result=await globalThis.gatewaySettingsRequest(body);
        clearKeys(latest.current);setSnapshot(result.settings);setDraft(makeDraft(result.settings));
        setDirty(false);setStatus(result.message);
      } catch(error){setFailed(true);setStatus(error.message)}
      finally {
        clearKeys(body);body=null;
        setDraft(previous=>{const next=structuredClone(previous);clearKeys(next);return next});setBusy(false);
      }
    }
    const footer=e(li.Fragment,null,
      e(`div`,{role:`status`,className:`min-w-0 flex-1 text-sm `+(failed?`text-danger`:`text-secondary`)},status),
      dirty?button(`Discard changes`,()=>{clearKeys(latest.current);setDraft(makeDraft(snapshot));setDirty(false);setStatus(``);setFailed(false)}):null,
      onClose?button(`Back`,onClose):null,
      e(GatewayButton,{size:`toolbar`,color:`primary`,loading:busy,disabled:busy||!dirty,onClick:()=>save()},`Save for next launch`));
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
        value=>edit(next=>{next.keys[id].active=value}),`The selected profile is used after relaunch.`),
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
          const template=draft.models.find(m=>m.provider===pid);
          edit(next=>{next.models.push({...structuredClone(template),id:``,label:``})});
          setExpanded(previous=>({...previous,[`model-`+draft.models.length]:true}));
        })},...draft.models.map((model,index)=>({model,index})).filter(({model})=>model.provider===pid).flatMap(({model,index})=>{
          const key=`model-`+index;
          const change=(field,value)=>edit(next=>{next.models[index][field]=value});
          const existing=snapshot.models.some(m=>m.id===model.id);
          return [e(GatewayRow,{key,label:model.label||`New model`,description:model.id||`Enter the provider’s API model ID`,control:button(expanded[key]?`Done`:`Edit`,()=>toggle(key))}),
            expanded[key]?e(li.Fragment,{key:key+`-editor`},
              e(Field,{label:`Model ID`,value:model.id,readOnly:existing,disabled:busy,onChange:value=>change(`id`,value)}),
              e(Field,{label:`Display name`,value:model.label,disabled:busy,onChange:value=>change(`label`,value)}),
              e(Field,{label:`Context tokens`,type:`number`,value:model.context,min:2,max:4194304,disabled:busy,onChange:value=>change(`context`,value)}),
              e(Field,{label:`Maximum output tokens`,type:`number`,value:model.output,min:1,max:1048576,disabled:busy,onChange:value=>change(`output`,value)}),
              e(GatewayRow,{label:`Supported efforts`,description:`Choose only efforts supported by this provider.`,control:e(GatewayDropdown,{align:`end`,contentWidth:`menuFixed`,disabled:busy,
                triggerButton:e(GatewayDropdownButton,{disabled:busy,"aria-label":`Supported efforts`},model.efforts.join(`, `)),
                children:efforts.map(effort=>e(GatewayMenu.CheckboxItem,{key:effort,checked:model.efforts.includes(effort),onSelect:event=>{
                  event.preventDefault();const selected=model.efforts.includes(effort)?model.efforts.filter(e=>e!==effort):[...model.efforts,effort];
                  edit(next=>{next.models[index].efforts=selected;if(!selected.includes(next.models[index].default_effort))next.models[index].default_effort=selected[0]??``});
                }},effort))})}),
              menuRow(`Default effort`,model.efforts.map(value=>({value,label:value})),model.default_effort,value=>change(`default_effort`,value))):null];
        }))];
    }
    const confirmation=e(GatewayDialog,{open:confirmEndpoint,size:`compact`,onOpenChange:setConfirmEndpoint},
      e(GatewayDialogContent,null,e(GatewayDialogHeader,null,e(GatewayDialogHeading,{
        title:e(GatewayDialogTitle,null,`Save provider URL changes?`),
        subtitle:e(GatewayDialogSubtitle,null,`The selected provider key will be sent to the new API address after relaunch.`)})),
        e(GatewayDialogFooter,null,button(`Cancel`,()=>setConfirmEndpoint(false)),
          e(GatewayButton,{size:`toolbar`,color:`primary`,onClick:()=>save(true)},`Save changes`))));
    return e(li.Fragment,null,e(GatewaySettingsPage,{title:labels[section]??labels.providers,subtitle:`Better Codex`,footer,scrollResetKey:section},content),confirmation);
  };
  globalThis.gatewayNativeSettingsControls = {Dropdown,Field,Section,makeDraft,requestBody,clearKeys};
})();
