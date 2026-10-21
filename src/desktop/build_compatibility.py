"""Reviewed static integration for exact signed desktop builds; never probe live UI."""
import hashlib
import json
import re


UPDATED_PACKAGE = 'OpenAI.Codex_26.1013.4894.0_x64__2p2nqsd0c76g0'
UPDATED_HASHES = {
    'ChatGPT.exe': '2f61eaeb01dcee7fd18d572fbb338c88b686c0d891427487fdd182afdd64b4f6',
    'resources/app.asar': 'bbec1d64e135b718a154b31655bb8ad9a39472bac1b2cabba991a9d97a339dd8',
    'resources/codex.exe': 'f6dbf48cb70f62649c645f26c87dc9bf84cc36986202dfad8e12fb5b8ca70312',
    'chrome.dll': '81c4a91d7c0480f9a41ac1d97ed7f13d3e05c06817765b4b9477aa7981427423',
}
UPDATED_ASSETS = {
    'app-primary-fe8a450b3b04.js': '2a05e25229bd7a38c12c55d90f82fb07087e80b4e16070116b215484498478f2',
    'settings-page-3320f8f55cf7.js': 'b2cd87077729d842693f267f0896a4056d82a77350255b220e6cc2ff22b90fee',
    'app-initial-5851df3f6cb1.js': 'c70d95da34ba7e5962a559dbf68d0102d10b4b47b877f5d9933629bb5a1f3a10',
    'app-shared-bbfeca5e5737.js': 'a6579611db8acf9c9908e2a29e70a88687eaa1d8f8dbcdc258de58f286051e9d',
    'general-settings-a68a0de66803.js': '91f37543c5675f5faa4accb1c3aa32285c660f33480fb92f37aa8872fbf669a9',
}

REVIEWED_PACKAGES = {
    UPDATED_PACKAGE: UPDATED_HASHES,
    'OpenAI.Codex_26.1007.2314.0_x64__2p2nqsd0c76g0': {
        'ChatGPT.exe': '13d7ee588d7ae20f04f7aa25a65ae82917ada81501304ac8f5e679d0b3306601',
        'resources/app.asar': 'c5fdef328cfa2ad9095786f9c3a7aaa447e68834d31299d6ef2592da02029038',
        'resources/codex.exe': 'd13914ced6c7af174d8d638db938284231227312104b06a25e9608c632a7daec',
        'chrome.dll': '4aeab54a054308d09540ad1ba51d21ef37d0af1cf8dd1fbadee95cad0902dd14',
    },
}


def require_known_build(manifest):
    from pathlib import Path
    expected = REVIEWED_PACKAGES.get(Path(manifest['source_app']).parent.name)
    if expected is None or manifest['installed_file_hashes'] != expected:
        raise RuntimeError('Unknown installed build; review compatibility first')


def replace_once(source, before, after):
    if source.count(before) != 1:
        raise RuntimeError('Reviewed desktop integration changed; customization refused')
    return source.replace(before, after, 1)


def require_named_imports(source, assets):
    for names, filename in re.findall(r'import\s*\{([^}]+)\}\s*from\s*["\']\./([^"\']+)', source):
        # Pinned bundles contain embedded source text with obsolete export tables.
        exports = re.search(r'\bexport\{([^{}]*)\};\s*(?://# sourceMappingURL=[^\r\n]*)?\s*\Z', assets[filename])
        available = {entry.split(' as ')[-1] for entry in exports[1].split(',')} if exports else set()
        if any(entry.strip().split(' as ')[0] not in available for entry in names.split(',')):
            raise RuntimeError('Reviewed native module export changed; customization refused')


def build_updated_overlay(root, manifest, overlay, read_asset, picker):
    """Only source reviewed for 26.1013.4894, with native callbacks left in place."""
    from pathlib import Path
    require_known_build(manifest)
    if Path(manifest['source_app']).parent.name != UPDATED_PACKAGE:
        raise RuntimeError('Unknown installed build; review compatibility first')
    assets = {}
    for name, expected in UPDATED_ASSETS.items():
        data = read_asset(name)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError('Reviewed desktop asset changed; customization refused')
        assets[name] = data.decode('utf-8')
    source = assets['app-primary-fe8a450b3b04.js']
    bridge = (root / 'src/ui/settings-bridge.js').read_text(encoding='utf-8')
    bridge = replace_once(bridge, 'zo.dispatchHostMessage', 'Hs.dispatchHostMessage')
    helper = (root / 'src/ui/provider-picker.js').read_text(encoding='utf-8')
    helper = replace_once(helper, 'const React = Z();', 'const React = Pf();')
    # These are module bindings from the reviewed primary bundle, not new state
    # or replacements for the original onSelect/effort callbacks.
    helper = helper.replace('CU.', 'YU.').replace('mh.', 'Fi.')
    helper = replace_once(helper, '? wn : undefined', '? Wu : undefined')
    helper += '\n' + (root / 'src/ui/chat-default-model.js').read_text(encoding='utf-8')
    helper += '\n' + (root / 'src/ui/restart-recovery.js').read_text(encoding='utf-8')
    # The RPC client returned by nS cannot supply synchronous state/listeners.
    # G6n exports QO in the executable module, outside its embedded source text.
    helper = 'import {G6n as gatewayNativeManagerAtom} from "./app-initial-5851df3f6cb1.js";\n' + helper
    require_named_imports(helper, assets)
    helper = 'const gatewayProviderConfig = ' + json.dumps(picker).replace('<', '\\u003c') + ';\n' + bridge + '\n' + helper
    updated = replace_once(source, 'function e8e(e){', helper + '\nfunction e8e(e){e=gatewayPickerMenuProps(e);')
    updated = replace_once(updated, 'let nt=T&&tt===',
        'globalThis.gatewaySubagentRequest=(method,params)=>{if(![`thread/list`,`thread/archive`,`thread/delete`].includes(method))throw Error(`Unsupported cleanup operation`);return nS(D,`local`).sendRequest(method,params)};gatewayChatDefaultModel(ZW,n,(w||T)&&Qe&&!We,()=>{sA(D,`default`,T);g({slug:f.defaultModelSlug,thinkingEffort:f.defaultThinkingEffortByModelSlug?.[f.defaultModelSlug]??null,versionId:Nd(f,f.defaultModelSlug)})});let nt=T&&tt===')
    updated = replace_once(updated, ';gatewayChatDefaultModel(ZW,n,',
        ';gatewayWatchRestartRecovery(D,message=>D.get(cc).danger(message,{errorAnalytics:{toastId:`betterCodex.restartRecovery`}}));gatewayChatDefaultModel(ZW,n,')

    updated = replace_once(updated, 'function cn(e){return q&&e===Pe?zv:e}',
        '(0,pG.useEffect)(()=>{if(T===`local`)gatewayWatchRestartRecovery(l,message=>l.get(cc).danger(message,{errorAnalytics:{toastId:`betterCodex.restartRecovery`}}))},[l,T]);gatewayChatDefaultModel(pG,i,!yt&&!q&&he?.isModelLocked!==!0&&jt!=null,()=>{l.set(MS,`default`);return sn(jt.model,jt.defaultReasoningEffort,{persistAsDefault:!1})},JSON.stringify([T,S.cwd]));function cn(e){return q&&e===Pe?zv:e}')

    settings_name = 'settings-page-3320f8f55cf7.js'
    settings = assets[settings_name]
    imports = '''import {tw as GatewayRow,qC as GatewayGroup,jO as GatewaySwitch,CO as GatewayDropdown,TO as GatewayMenu,$4 as GatewayButton,mO as GatewayDialog,oO as GatewayDialogContent,BV as GatewayChevron,uO as GatewayFieldStack,lO as GatewayDialogHeader,sO as GatewayDialogFooter,cO as GatewayDialogHeading,_O as GatewayDialogTitle,gO as GatewayDialogSubtitle} from "./app-shared-bbfeca5e5737.js";
import {Tk as GatewaySettingsSection,Ek as gatewayInitializeSettingsSection,QP as GatewayDropdownButton,TPn as GatewayInput,llt as GatewaySearch,ult as gatewayInitializeSearch,hF as GatewaySettingsPage,Gdt as GatewayDirtySettings,Vdt as gatewayInitializeDirtySettings} from "./app-initial-5851df3f6cb1.js";
import {s as gatewayInitializeSettingsControls} from "./general-settings-a68a0de66803.js";
'''
    sections = [{'slug': 'better-codex-' + slug, 'label': label} for slug, label in [('providers', 'Providers'), ('models', 'Models')]]
    group = {'key': 'better-codex', 'heading': {'id': 'betterCodex.settings', 'defaultMessage': 'Better Codex'}, 'sections': sections}
    settings = replace_once(settings, ':n.map(e=>(0,Q.jsxs)(Pe,{title:', ':([...n,' + json.dumps(group) + ']).map(e=>(0,Q.jsxs)(Pe,{title:')
    settings = replace_once(settings, 'e.sections.map(e=>{if(e.slug===`teams`', 'e.sections.map(e=>{if(e.slug.startsWith(`better-codex-`))return(0,Q.jsx)(K,{label:e.label,"aria-label":e.label,"data-settings-panel-slug":e.slug,isActive:s===e.slug,hideLabel:w?P:void 0,weightClassName:`font-normal`,onClick:()=>l(e.slug)},e.slug);if(e.slug===`teams`')
    replacements = {
        'function _i(){let e=(0,Ci.c)(143)': 'function _i(){let[gatewaySelection,gatewaySetSelection]=(0,wi.useState)(null);let e=(0,Ci.c)(143)',
        'let R=ve,be;': 'let R=ve;(0,wi.useEffect)(()=>{let navigate=(section,provider)=>R(()=>gatewaySetSelection({slug:`better-codex-`+section,provider}));globalThis.gatewaySettingsNavigate=navigate;let pending=globalThis.gatewaySettingsPending;if(pending){delete globalThis.gatewaySettingsPending;navigate(pending.section,pending.provider)}return()=>{if(globalThis.gatewaySettingsNavigate===navigate)delete globalThis.gatewaySettingsNavigate}},[R]);(0,wi.useEffect)(()=>gatewaySetSelection(null),[m.pathname,m.search]);let be;',
        'y!=null&&(qe=x?`rosalind`:`plugins-settings`);': 'y!=null&&(qe=x?`rosalind`:`plugins-settings`);if(gatewaySelection)qe=gatewaySelection.slug;',
        'onSelect:G,onSelectPlugin:K,onSelectTeam:Le': 'onSelect:(slug,...args)=>{if(slug.startsWith(`better-codex-`)){R(()=>gatewaySetSelection({slug,provider:null}))}else{gatewaySetSelection(null);G(slug,...args)}},onSelectPlugin:(...args)=>{gatewaySetSelection(null);K(...args)},onSelectTeam:(...args)=>{gatewaySetSelection(null);Le(...args)}',
        'let J=`${m.key}:${I?.navigationKey??0}`': 'if(gatewaySelection)Pe=(0,$.jsx)(globalThis.gatewaySettingsComponent,{section:gatewaySelection.slug.slice(13),provider:gatewaySelection.provider},gatewaySelection.slug);let J=`${m.key}:${I?.navigationKey??0}`',
    }
    for before, after in replacements.items():
        settings = replace_once(settings, before, after)
    # The native page already uses `li` for a utility. Limit the editor's React
    # alias to its own lexical block, leaving every native binding unchanged.
    editor = (root / 'src/ui/api-settings.js').read_text(encoding='utf-8')
    settings = imports + replace_once(settings, 'Ti();export{_i as SettingsPage};', 'Ti();gatewayInitializeSettingsControls();gatewayInitializeDirtySettings();gatewayInitializeSearch();gatewayInitializeSettingsSection();\n{const li=wi;\n' + editor + '\n}\nexport{_i as SettingsPage};')
    require_named_imports(imports, assets)
    overlay['filename'] = 'app-primary-fe8a450b3b04.js'
    overlay['original_source_sha256'] = UPDATED_ASSETS[overlay['filename']]
    return updated, settings, settings_name, UPDATED_ASSETS[settings_name]
